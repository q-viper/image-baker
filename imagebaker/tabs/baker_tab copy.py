from imagebaker.list_views import LayerList, LayerSettings
from imagebaker.list_views.canvas_list import CanvasList
from imagebaker.layers.non_annotable_layer import NonAnnotableLayer
from imagebaker.core.defs import BakingResult
from imagebaker import logger

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QDockWidget,
)
from collections import deque


class BakerTab(QWidget):
    """Baker Tab implementation"""

    messageSignal = Signal(str)
    bakingResult = Signal(BakingResult)

    def __init__(self, main_window, config):
        super().__init__(main_window)
        self.main_window = main_window
        self.config = config
        self.toolbar = None
        self.main_layout = QVBoxLayout(self)

        # Deque to store multiple NonAnnotableLayer objects with a fixed size
        self.canvases = deque(maxlen=self.config.deque_maxlen)

        # Currently selected canvas
        self.current_canvas = None

        self.init_ui()

    def init_ui(self):
        # Create toolbar
        self.create_toolbar()

        # just create a single canvas for now
        self.current_canvas = NonAnnotableLayer(parent=self.main_window)
        self.current_canvas.setVisible(True)  # Initially hide all canvases
        self.canvases.append(self.current_canvas)
        self.main_layout.addWidget(self.current_canvas)

        # Create and add CanvasList
        self.canvas_list = CanvasList(self.canvases, parent=self.main_window)
        self.main_window.addDockWidget(Qt.LeftDockWidgetArea, self.canvas_list)

        # Create and add LayerList
        self.layer_settings = LayerSettings(parent=self.main_window)
        self.layer_list = LayerList(
            canvas=self.current_canvas,
            parent=self.main_window,
            layer_settings=self.layer_settings,
        )
        self.layer_settings.setVisible(False)
        self.main_window.addDockWidget(Qt.RightDockWidgetArea, self.layer_list)
        self.main_window.addDockWidget(Qt.RightDockWidgetArea, self.layer_settings)

        # Create a dock widget for the toolbar
        self.toolbar_dock = QDockWidget("Tools", self)
        self.toolbar_dock.setWidget(self.toolbar)
        self.toolbar_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.main_window.addDockWidget(Qt.BottomDockWidgetArea, self.toolbar_dock)

        # Connections
        self.layer_settings.messageSignal.connect(self.messageSignal.emit)
        self.layer_settings.layerState.connect(self.pass_bake_settings)
        self.current_canvas.bakingResult.connect(self.bakingResult.emit)
        self.current_canvas.layersChanged.connect(self.update_list)
        self.canvas_list.canvasSelected.connect(self.on_canvas_selected)
        self.canvas_list.canvasAdded.connect(self.on_canvas_added)
        self.canvas_list.canvasDeleted.connect(self.on_canvas_deleted)
        self.current_canvas.layerRemoved.connect(self.update_list)

    def update_list(self):
        self.layer_list.update_list()

    def pass_bake_settings(self, layer_state):
        self.current_canvas.bake_settings(layer_state)

    def on_canvas_deleted(self, canvas: NonAnnotableLayer):
        """Handle the deletion of a canvas."""
        # Ensure only the currently selected canvas is visible
        if self.canvases:
            self.current_canvas = self.canvases[-1]  # Select the last canvas
            self.current_canvas.setVisible(True)  # Show the last canvas
        else:
            self.current_canvas = None  # No canvases left
            self.messageSignal.emit("No canvases available.")  # Notify the user

    def on_canvas_selected(self, canvas: NonAnnotableLayer):
        """Handle canvas selection from the CanvasList."""
        # Hide all canvases and show only the selected one
        for layer in self.canvases:
            layer.setVisible(layer == canvas)

        # Update the current canvas
        self.current_canvas = canvas
        self.layer_list.canvas = canvas
        self.layer_list.layers = canvas.layers
        self.layer_settings.selected_layer = canvas.selected_layer
        self.layer_list.layer_settings = self.layer_settings

        self.layer_list.update_list()
        self.layer_settings.update_sliders()

        logger.info(f"Selected canvas: {canvas.layer_name}")
        self.update()

    def on_canvas_added(self, new_canvas: NonAnnotableLayer):
        """Handle the addition of a new canvas."""
        logger.info(f"New canvas added: {new_canvas.layer_name}")
        self.main_layout.addWidget(new_canvas)  # Add the new canvas to the layout
        if self.current_canvas is not None:
            self.current_canvas.setVisible(False)  # Hide the current canvas

        # self.canvases.append(new_canvas)  # Add the new canvas to the deque
        # connect it to the layer list
        self.layer_list.canvas = new_canvas
        self.current_canvas = new_canvas  # Update the current canvas
        self.canvas_list.update_canvas_list()  # Update the canvas list
        new_canvas.setVisible(True)  # Hide the new canvas initially
        # already added to the list
        # self.canvases.append(new_canvas)  # Add to the deque

        self.current_canvas.bakingResult.connect(self.bakingResult.emit)
        self.current_canvas.layersChanged.connect(self.update_list)
        self.current_canvas.layerRemoved.connect(self.update_list)

        self.current_canvas.update()
        self.layer_list.layers = new_canvas.layers
        self.layer_list.update_list()
        self.layer_settings.selected_layer = None
        self.layer_settings.update_sliders()

    def create_toolbar(self):
        """Create Baker-specific toolbar"""
        self.toolbar = QWidget()
        baker_toolbar_layout = QHBoxLayout(self.toolbar)

        baker_modes = [
            ("Export Current State", self.export_current_state),
            (
                "Save State",
                self.save_current_state,
            ),
            (
                "Predict State",
                self.predict_state,
            ),
            ("Play State", self.play_saved_state),
        ]

        for text, callback in baker_modes:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            baker_toolbar_layout.addWidget(btn)

        # Add spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        baker_toolbar_layout.addWidget(spacer)

    def play_saved_state(self):
        self.messageSignal.emit("Playing saved state...")
        self.current_canvas.play_states()

    def export_current_state(self):
        self.messageSignal.emit("Exporting current state...")
        self.current_canvas.export_current_state()

    def predict_state(self):
        self.messageSignal.emit("Predicting state...")

        self.current_canvas.predict_state()

    def add_layer(self, layer: NonAnnotableLayer):
        """Add a new layer to the canvas."""

        self.layer_list.add_layer(layer)
        self.layer_settings.selected_layer = self.current_canvas.selected_layer
        self.layer_settings.update_sliders()

    def save_current_state(self):
        self.messageSignal.emit("Saving current state...")
        self.current_canvas.save_current_state()
        self.messageSignal.emit("Current state saved.")
