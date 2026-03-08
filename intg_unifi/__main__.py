"""Entry point for python -m intg_unifi.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0
"""
import asyncio

from intg_unifi import main

if __name__ == "__main__":
    asyncio.run(main())
