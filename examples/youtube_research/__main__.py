"""Allow running as: python -m examples.youtube_research <url>."""

from .app import main
import asyncio

asyncio.run(main())
