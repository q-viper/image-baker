from loguru import logger  # noqa
from importlib.metadata import version, PackageNotFoundError

logger.info("imagebaker package loaded with loguru logger.")

try:
    __version__ = version("imagebaker")
except PackageNotFoundError:
    __version__ = "0.0.0"
