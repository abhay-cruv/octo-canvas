from orchestrator.app import app
from orchestrator.lib.env import settings
from orchestrator.lib.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
logger.info("orchestrator.starting", port=settings.orchestrator_port)

__all__ = ["app"]
