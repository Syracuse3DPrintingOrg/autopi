"""Entry point: ``python -m autopi_streamdeck``."""
from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import load


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="autopi-streamdeck",
        description="Run a Stream Deck as an AutoPi controller.",
    )
    p.add_argument("--config", help="Path to a TOML config file.")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    from .controller import run
    return run(load(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
