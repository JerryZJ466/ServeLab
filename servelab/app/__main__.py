import argparse
import logging
from pathlib import Path

import uvicorn

from servelab.app import create_app
from servelab.core.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one ServeLab gateway process (mock or vLLM HTTP backend)."
    )
    parser.add_argument("--config", type=Path, default=Path("configs/mock.toml"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run(
        create_app(Settings.from_file(args.config)),
        host=args.host,
        port=args.port,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
