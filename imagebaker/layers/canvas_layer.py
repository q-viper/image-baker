from PySide6.QtCore import QSizeF, Signal
from PySide6.QtWidgets import QSizePolicy

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig
from imagebaker.core.defs import Annotation, BakingResult
from imagebaker.layers.base_layer import BaseLayer
from imagebaker.layers.canvas_grouping_export import CanvasGroupingExportMixin
from imagebaker.layers.canvas_interaction import CanvasInteractionMixin
from imagebaker.layers.canvas_states_plugins import CanvasStatesPluginsMixin


class CanvasLayer(
    CanvasStatesPluginsMixin,
    CanvasInteractionMixin,
    CanvasGroupingExportMixin,
    BaseLayer,
):
    """Multi-layer composite canvas with transform handles, timeline states, plugins, and baking."""

    layersChanged = Signal()
    layerSelected = Signal(BaseLayer)
    annotationAdded = Signal(Annotation)
    annotationUpdated = Signal(Annotation)
    bakingResult = Signal(BakingResult)
    thumbnailsAvailable = Signal(int)

    def __init__(self, parent=None, config=None):
        if config is None:
            config = CanvasConfig()
        super().__init__(parent, config)
        self.is_annotable = False
        self.last_pan_point = None
        self.state_thumbnail = {}

        self._last_draw_point = None
        self._undo_stack = []
        self._redo_stack = []
        self._max_history = 100
        self._interaction_undo_pushed = False
        self._plugin_render_cache = {}
        self._current_step_index = 0
        self.is_playing = False

    def init_ui(self):
        """Initialize size policies and store the original image size."""
        logger.info(f"Initializing Layer UI of {self.layer_name}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.original_size = QSizeF(self.image.size())
