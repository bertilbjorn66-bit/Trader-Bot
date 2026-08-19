from __future__ import annotations

import argparse

from .audit import configure_logging
from .config import get_settings
from .providers import DukascopyProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="DuraPlex Trader Bot engineering CLI")
    parser.add_argument("command", choices=("health",), help="safe infrastructure checks")
    args = parser.parse_args()

    settings = get_settings()
    logger = configure_logging(settings.log_level)
    if args.command == "health":
        with DukascopyProvider(settings) as provider:
            ok = provider.health_check()
        logger.info("provider_health=%s", ok)
        return 0 if ok else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
