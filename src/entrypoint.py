from __future__ import annotations

from .config import load_config
from .logger import setup_logger
from .main import run as run_pipeline
from .trigger_server import start_trigger_server


def main() -> None:
    logger = setup_logger()
    config = load_config()

    if config.run_mode == "webhook":
        logger.info("ENTRYPOINT: starting in webhook trigger mode")
        start_trigger_server(config)
        return

    logger.info("ENTRYPOINT: starting in oneshot mode")
    run_pipeline()


if __name__ == "__main__":
    main()
