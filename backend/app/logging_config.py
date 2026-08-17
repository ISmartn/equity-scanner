from __future__ import annotations

import logging
import os
import sys


def setup_logging() -> None:
    level = logging.DEBUG if os.getenv("FORECAST_DEBUG", "").lower() in ("1", "true", "yes") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    # Quiet noisy libraries unless debug
    if level > logging.DEBUG:
        for name in ("httpx", "httpcore", "urllib3", "aiohttp"):
            logging.getLogger(name).setLevel(logging.WARNING)
