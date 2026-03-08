"""UniFi Protect camera entities - Media player with source switching + select.

Follows the uc-intg-cctv pattern: single media player with all cameras as sources,
10-second snapshot refresh loop, and a select entity for camera switching.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import asyncio
import base64
import io
import logging
import time
from typing import Any

from ucapi import StatusCodes
from ucapi.media_player import (
    Attributes as MediaAttributes,
    Commands as MediaCommands,
    Features as MediaFeatures,
    MediaPlayer,
    MediaType,
    States as MediaStates,
)
from ucapi.select import (
    Attributes as SelectAttributes,
    Commands as SelectCommands,
    Select,
    States as SelectStates,
)

from intg_unifi.config import UniFiConfig
from intg_unifi.device import UniFiDevice

_LOG = logging.getLogger(__name__)

SNAPSHOT_REFRESH_RATE = 10
MAX_CONSECUTIVE_FAILURES = 5
IMAGE_MAX_WIDTH = 320
IMAGE_MAX_HEIGHT = 240
IMAGE_MAX_SIZE_KB = 80


def _optimize_image(image_data: bytes) -> str | None:
    """Optimize camera snapshot for UC Remote display (320x240, <80KB JPEG, base64)."""
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(image_data))

        img_ratio = image.width / image.height
        screen_ratio = IMAGE_MAX_WIDTH / IMAGE_MAX_HEIGHT

        if img_ratio > screen_ratio:
            new_width = IMAGE_MAX_WIDTH
            new_height = int(IMAGE_MAX_WIDTH / img_ratio)
        else:
            new_height = IMAGE_MAX_HEIGHT
            new_width = int(IMAGE_MAX_HEIGHT * img_ratio)

        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        if resized.mode != "RGB":
            resized = resized.convert("RGB")

        quality = 85
        buf = io.BytesIO()
        while quality > 20:
            buf.seek(0)
            buf.truncate()
            resized.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            if buf.tell() / 1024 <= IMAGE_MAX_SIZE_KB:
                break
            quality -= 10

        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
    except Exception as err:
        _LOG.error("Image optimization failed: %s", err)
        return None


class ProtectCameraMediaPlayer(MediaPlayer):
    """Single media player displaying all Protect cameras as switchable sources."""

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice):
        self._device = device
        self._cfg = device_config

        source_list = []
        self._camera_id_by_name: dict[str, str] = {}
        for cam_id, cam in device.cameras.items():
            name = cam.get("name") or cam.get("displayName") or f"Camera {cam_id}"
            source_list.append(name)
            self._camera_id_by_name[name] = cam_id

        current_source = source_list[0] if source_list else ""
        entity_id = f"media_player.{device_config.identifier}.protect_cameras"

        super().__init__(
            entity_id,
            f"{device_config.name} - Cameras",
            [MediaFeatures.ON_OFF, MediaFeatures.SELECT_SOURCE],
            {
                MediaAttributes.STATE: MediaStates.OFF,
                MediaAttributes.MEDIA_TYPE: MediaType.VIDEO,
                MediaAttributes.SOURCE_LIST: source_list,
                MediaAttributes.SOURCE: current_source,
                MediaAttributes.MEDIA_IMAGE_URL: "",
                MediaAttributes.MEDIA_TITLE: current_source,
                MediaAttributes.MEDIA_ARTIST: "Camera View",
            },
            device_class="tv",
            cmd_handler=self.handle_command,
        )

        self.current_source = current_source
        self.is_streaming = False
        self._stream_task: asyncio.Task | None = None
        self._last_image_update = 0
        self._select_entity: Any | None = None
        self._api_ref: Any | None = None

        _LOG.info("[%s] Created camera media player with %d sources", device_config.name, len(source_list))

    def set_api(self, api: Any) -> None:
        self._api_ref = api

    def set_select_entity(self, select_entity: Any) -> None:
        self._select_entity = select_entity

    @property
    def _current_camera_id(self) -> str | None:
        return self._camera_id_by_name.get(self.current_source)

    async def handle_command(self, entity: MediaPlayer, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        try:
            if cmd_id == MediaCommands.ON:
                return await self._turn_on()
            elif cmd_id == MediaCommands.OFF:
                return await self._turn_off()
            elif cmd_id == MediaCommands.SELECT_SOURCE:
                source = params.get("source") if params else None
                return await self._select_source(source)
            return StatusCodes.NOT_IMPLEMENTED
        except Exception as err:
            _LOG.error("Command %s failed: %s", cmd_id, err, exc_info=True)
            return StatusCodes.SERVER_ERROR

    async def _turn_on(self) -> StatusCodes:
        if not self._current_camera_id:
            return StatusCodes.BAD_REQUEST
        self.attributes[MediaAttributes.STATE] = MediaStates.PLAYING
        self.attributes[MediaAttributes.MEDIA_TITLE] = self.current_source
        self._push_state()
        await self._start_streaming()
        return StatusCodes.OK

    async def _turn_off(self) -> StatusCodes:
        await self._stop_streaming()
        self.attributes[MediaAttributes.STATE] = MediaStates.OFF
        self.attributes[MediaAttributes.MEDIA_IMAGE_URL] = ""
        self._push_state()
        return StatusCodes.OK

    async def _select_source(self, source_name: str) -> StatusCodes:
        if not source_name or source_name not in self._camera_id_by_name:
            return StatusCodes.BAD_REQUEST

        was_streaming = self.is_streaming
        if was_streaming:
            await self._stop_streaming()

        self.current_source = source_name
        self.attributes[MediaAttributes.SOURCE] = source_name
        self.attributes[MediaAttributes.MEDIA_TITLE] = source_name
        self.attributes[MediaAttributes.STATE] = MediaStates.PLAYING
        self._push_state()

        if self._select_entity:
            self._select_entity.update_from_media_player(source_name)

        await asyncio.sleep(0.1)
        await self._start_streaming()
        return StatusCodes.OK

    def _push_state(self) -> None:
        api = self._api_ref
        if not api or not api.configured_entities.contains(self.id):
            return
        api.configured_entities.update_attributes(self.id, {
            MediaAttributes.STATE: self.attributes[MediaAttributes.STATE],
            MediaAttributes.SOURCE: self.attributes[MediaAttributes.SOURCE],
            MediaAttributes.MEDIA_TITLE: self.attributes[MediaAttributes.MEDIA_TITLE],
            MediaAttributes.MEDIA_IMAGE_URL: self.attributes.get(MediaAttributes.MEDIA_IMAGE_URL, ""),
            MediaAttributes.MEDIA_ARTIST: self.attributes.get(MediaAttributes.MEDIA_ARTIST, "Camera View"),
        })

    async def _start_streaming(self) -> None:
        if self.is_streaming or not self._current_camera_id:
            return
        self.is_streaming = True
        self._stream_task = asyncio.create_task(self._stream_loop())
        _LOG.info("[%s] Started streaming %s (%ds refresh)", self._cfg.name, self.current_source, SNAPSHOT_REFRESH_RATE)

    async def _stop_streaming(self) -> None:
        self.is_streaming = False
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None

    async def _stream_loop(self) -> None:
        failures = 0
        while self.is_streaming and self._current_camera_id:
            try:
                image_data = await self._device.get_camera_snapshot_bytes(self._current_camera_id)
                if image_data:
                    optimized = _optimize_image(image_data)
                    if optimized:
                        self.attributes[MediaAttributes.MEDIA_IMAGE_URL] = f"data:image/jpeg;base64,{optimized}"
                        self._last_image_update = time.time()
                        self._push_state()
                        failures = 0
                    else:
                        failures += 1
                else:
                    failures += 1

                if failures >= MAX_CONSECUTIVE_FAILURES:
                    _LOG.error("[%s] Max snapshot failures for %s", self._cfg.name, self.current_source)
                    self.attributes[MediaAttributes.STATE] = MediaStates.UNAVAILABLE
                    self.attributes[MediaAttributes.MEDIA_IMAGE_URL] = ""
                    self._push_state()
                    self.is_streaming = False
                    break

                await asyncio.sleep(SNAPSHOT_REFRESH_RATE)
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOG.error("[%s] Stream error: %s", self._cfg.name, err)
                failures += 1
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    self.is_streaming = False
                    break
                await asyncio.sleep(5)

    async def disconnect(self) -> None:
        await self._stop_streaming()


class ProtectCameraSelect(Select):
    """Select entity for switching between Protect cameras."""

    def __init__(self, device_config: UniFiConfig, device: UniFiDevice, media_player: ProtectCameraMediaPlayer):
        self._device = device
        self._media_player = media_player

        camera_options = list(media_player._camera_id_by_name.keys())
        current_option = camera_options[0] if camera_options else ""
        entity_id = f"select.{device_config.identifier}.protect_camera_selector"

        super().__init__(
            entity_id,
            f"{device_config.name} - Camera Selector",
            {
                SelectAttributes.STATE: SelectStates.ON,
                SelectAttributes.OPTIONS: camera_options,
                SelectAttributes.CURRENT_OPTION: current_option,
            },
            cmd_handler=self.handle_command,
        )
        self._api_ref: Any | None = None

    def set_api(self, api: Any) -> None:
        self._api_ref = api

    async def handle_command(self, entity: Select, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        try:
            if cmd_id == SelectCommands.SELECT_OPTION:
                option = params.get("option") if params else None
                return await self._select_camera(option)
            elif cmd_id == SelectCommands.SELECT_NEXT:
                return await self._cycle(1)
            elif cmd_id == SelectCommands.SELECT_PREVIOUS:
                return await self._cycle(-1)
            elif cmd_id == SelectCommands.SELECT_FIRST:
                options = self.attributes[SelectAttributes.OPTIONS]
                return await self._select_camera(options[0]) if options else StatusCodes.BAD_REQUEST
            elif cmd_id == SelectCommands.SELECT_LAST:
                options = self.attributes[SelectAttributes.OPTIONS]
                return await self._select_camera(options[-1]) if options else StatusCodes.BAD_REQUEST
            return StatusCodes.NOT_IMPLEMENTED
        except Exception as err:
            _LOG.error("Select command %s failed: %s", cmd_id, err, exc_info=True)
            return StatusCodes.SERVER_ERROR

    async def _select_camera(self, camera_name: str) -> StatusCodes:
        if not camera_name or camera_name not in self.attributes[SelectAttributes.OPTIONS]:
            return StatusCodes.BAD_REQUEST
        self.attributes[SelectAttributes.CURRENT_OPTION] = camera_name
        self._push_state()
        return await self._media_player._select_source(camera_name)

    async def _cycle(self, direction: int) -> StatusCodes:
        options = self.attributes[SelectAttributes.OPTIONS]
        current = self.attributes[SelectAttributes.CURRENT_OPTION]
        try:
            idx = options.index(current)
            new_idx = (idx + direction) % len(options)
            return await self._select_camera(options[new_idx])
        except (ValueError, IndexError):
            return StatusCodes.SERVER_ERROR

    def _push_state(self) -> None:
        api = self._api_ref
        if not api or not api.configured_entities.contains(self.id):
            return
        api.configured_entities.update_attributes(self.id, {
            SelectAttributes.STATE: SelectStates.ON,
            SelectAttributes.CURRENT_OPTION: self.attributes[SelectAttributes.CURRENT_OPTION],
        })

    def update_from_media_player(self, camera_name: str) -> None:
        if camera_name in self.attributes[SelectAttributes.OPTIONS]:
            self.attributes[SelectAttributes.CURRENT_OPTION] = camera_name
            self._push_state()
