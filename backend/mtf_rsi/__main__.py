from __future__ import annotations

import logging
import sys


def main(argv: list[str] | None = None) -> int:
    from .config import build_config
    from .service import MtfRsiService

    config = build_config(argv)
    if not config.access_token:
        print(
            "ERROR: UPSTOX_ACCESS_TOKEN not set. Add it to .env or the environment.",
            file=sys.stderr,
        )
        return 1

    config.cache_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.cache_dir / "service.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    # Keep the live table readable: only warnings+ on stderr.
    logging.getLogger().handlers[1].setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("upstox_client").setLevel(logging.WARNING)

    service = MtfRsiService(config)
    try:
        service.run_forever()
    except KeyboardInterrupt:
        service.stop()
        print("\nInterrupted.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
