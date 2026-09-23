from importlib.util import find_spec

from imagebaker import logger

from .base_plugin import BasePlugin  # noqa: F401
from .gaussian_blur import GaussianBlur  # noqa: F401
from .perspective_transform import PerspectiveTransform  # noqa: F401
from .sine_movement import SineMovement  # noqa: F401

if find_spec("smokesim") is not None:
    try:
        from .smokesim_plugin import SmokeSim  # noqa: F401
    except Exception as error:
        logger.warning(f"SmokeSim plugin is unavailable: {error}")
