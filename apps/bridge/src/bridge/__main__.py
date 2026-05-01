from bridge.lib.logger import configure_logging, get_logger


def main() -> None:
    configure_logging()
    logger = get_logger(__name__)
    logger.info("bridge.started")


if __name__ == "__main__":
    main()
