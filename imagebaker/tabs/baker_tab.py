from imagebaker.list_views import LayerList, LayerSettings
from imagebaker.list_views.canvas_list import CanvasList
from imagebaker.layers.non_annotable_layer import NonAnnotableLayer
from imagebaker.core.defs import BakingResult
from imagebaker import logger

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QDockWidget,
    QSlider,
    QLabel,
    QSpinBox,
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

        # Create a single canvas for now
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
        self.current_canvas.bakingResult.connect(self.bakingResult.emit)
        self.current_canvas.layersChanged.connect(self.update_list)
        self.canvas_list.canvasSelected.connect(self.on_canvas_selected)
        self.canvas_list.canvasAdded.connect(self.on_canvas_added)
        self.canvas_list.canvasDeleted.connect(self.on_canvas_deleted)
        self.current_canvas.layerRemoved.connect(self.update_list)
        # self.current_canvas.thumbnailsAvailable.connect(self.generate_state_previews)

    def update_slider_range(self, steps):
        """Update the slider range based on the number of steps."""
        self.timeline_slider.setMaximum(steps - 1)
        self.messageSignal.emit(f"Updated steps to {steps}")
        self.timeline_slider.setEnabled(False)  # Disable the slider
        self.timeline_slider.update()

    def generate_state_previews(self):
        """Generate previews for each state."""
        # Clear existing previews
        for i in reversed(range(self.preview_layout.count())):
            widget = self.preview_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        # Generate a preview for each state
        for step, states in sorted(self.current_canvas.states.items()):
            # Create a container widget for the preview
            preview_widget = QWidget()
            preview_layout = QVBoxLayout(preview_widget)
            preview_layout.setContentsMargins(0, 0, 0, 0)
            preview_layout.setSpacing(2)

            # Placeholder thumbnail
            placeholder = QPixmap(50, 50)
            placeholder.fill(Qt.gray)  # Gray placeholder
            thumbnail_label = QLabel()
            thumbnail_label.setPixmap(placeholder)
            thumbnail_label.setFixedSize(50, 50)  # Set a fixed size for the thumbnail
            thumbnail_label.setScaledContents(True)

            # Add the step number on top of the thumbnail
            step_label = QLabel(f"Step {step}")
            step_label.setAlignment(Qt.AlignCenter)
            step_label.setStyleSheet("font-weight: bold; font-size: 10px;")

            # Add a button to make the preview clickable
            preview_button = QPushButton()
            preview_button.setFixedSize(
                50, 70
            )  # Match the size of the thumbnail + step label
            preview_button.setStyleSheet("background: transparent; border: none;")
            preview_button.clicked.connect(lambda _, s=step: self.seek_state(s))

            # Add the thumbnail and step label to the layout
            preview_layout.addWidget(thumbnail_label)
            preview_layout.addWidget(step_label)

            # Add the preview widget to the button
            preview_button.setLayout(preview_layout)

            # Add the button to the preview panel
            self.preview_layout.addWidget(preview_button)

            # Update the thumbnail dynamically when it becomes available
            self.current_canvas.thumbnailsAvailable.connect(
                lambda step=step, label=thumbnail_label: self.update_thumbnail(
                    step, label
                )
            )

        # Refresh the preview panel
        self.preview_panel.update()

    def update_thumbnail(self, step, thumbnail_label):
        """Update the thumbnail for a specific step."""
        if step in self.current_canvas.state_thumbnail:
            thumbnail = self.current_canvas.state_thumbnail[step]
            thumbnail_label.setPixmap(thumbnail)
            thumbnail_label.update()

    def update_list(self):
        self.layer_list.update_list()

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
        baker_toolbar_layout.setContentsMargins(5, 5, 5, 5)
        baker_toolbar_layout.setSpacing(10)

        # Add a label for "Steps"
        steps_label = QLabel("Steps:")
        steps_label.setStyleSheet("font-weight: bold;")
        baker_toolbar_layout.addWidget(steps_label)

        # Add a spin box for entering the number of steps
        self.steps_spinbox = QSpinBox()
        self.steps_spinbox.setMinimum(1)
        self.steps_spinbox.setMaximum(1000)  # Arbitrary maximum value
        self.steps_spinbox.setValue(1)  # Default value
        self.steps_spinbox.valueChanged.connect(self.update_slider_range)
        baker_toolbar_layout.addWidget(self.steps_spinbox)

        # Add buttons for Baker modes with emojis
        baker_modes = [
            ("📤 Export Current State", self.export_current_state),
            ("💾 Save State", self.save_current_state),
            ("🔮 Predict State", self.predict_state),
            ("▶️ Play States", self.play_saved_states),
            ("🗑️ Clear States", self.clear_states),  # New button
            ("📤 Annotate States", self.export_for_annotation),
            ("📤 Export States", self.export_locally),
        ]

        for text, callback in baker_modes:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            baker_toolbar_layout.addWidget(btn)

            # If the button is "Play States", add the slider beside it
            if text == "▶️ Play States":
                self.timeline_slider = QSlider(Qt.Horizontal)  # Create the slider
                self.timeline_slider.setMinimum(0)
                self.timeline_slider.setMaximum(0)  # Will be updated dynamically
                self.timeline_slider.setValue(0)
                self.timeline_slider.setSingleStep(
                    1
                )  # Set the granularity of the slider
                self.timeline_slider.setPageStep(1)  # Allow smoother jumps
                self.timeline_slider.setEnabled(False)  # Initially disabled
                self.timeline_slider.valueChanged.connect(self.seek_state)
                baker_toolbar_layout.addWidget(self.timeline_slider)

        # Add a spacer to push the rest of the elements to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        baker_toolbar_layout.addWidget(spacer)

        # Add the toolbar to the main layout
        self.main_layout.addWidget(self.toolbar)

    def export_for_annotation(self):
        self.messageSignal.emit("Exporting states for prediction...")
        self.current_canvas.play_states(export_to_annotation_tab=True, export=True)

    def export_locally(self):
        self.messageSignal.emit("Exporting baked states...")
        self.current_canvas.play_states(export=True)

    def play_saved_states(self):
        self.messageSignal.emit("Playing saved state...")

        # Enable the timeline slider
        self.timeline_slider.setEnabled(True)

        # Update the slider range based on the number of states
        if self.current_canvas.states:
            num_states = len(self.current_canvas.states)
            self.timeline_slider.setMaximum(num_states - 1)
            self.steps_spinbox.setValue(
                num_states
            )  # Sync the spinbox with the number of states
        else:
            self.timeline_slider.setMaximum(0)
            self.steps_spinbox.setValue(1)
            self.messageSignal.emit("No saved states available.")

        # Start playing the states
        self.current_canvas.play_states()

    def save_current_state(self):
        self.messageSignal.emit("Saving current state...")
        logger.info(f"Saving current state for {self.steps_spinbox.value()}...")

        self.current_canvas.save_current_state(steps=self.steps_spinbox.value())
        self.messageSignal.emit(
            "Current state saved. Total states: {}".format(
                len(self.current_canvas.states)
            )
        )

        # Disable the timeline slider
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.update()

    def clear_states(self):
        """Clear all saved states and disable the timeline slider."""
        self.messageSignal.emit("Clearing all saved states...")
        if self.current_canvas:
            self.current_canvas.previous_state = None
            self.current_canvas.current_step = 0
            self.current_canvas.states.clear()  # Clear all saved states
        self.timeline_slider.setEnabled(False)  # Disable the slider
        self.timeline_slider.setMaximum(0)  # Reset the slider range
        self.timeline_slider.setValue(0)  # Reset the slider position
        self.messageSignal.emit("All states cleared.")
        self.steps_spinbox.setValue(1)  # Reset the spinbox value

        self.steps_spinbox.update()
        self.timeline_slider.update()
        self.current_canvas.update()

    def seek_state(self, step):
        """Seek to a specific state using the timeline slider."""
        self.messageSignal.emit(f"Seeking to step {step}")
        logger.info(f"Seeking to step {step}")

        # Get the states for the selected step
        if step in self.current_canvas.states:
            states = self.current_canvas.states[step]
            for state in states:
                layer = self.current_canvas.get_layer(state.layer_id)
                if layer:
                    layer.layer_state = state
                    layer.update()

        # Update the canvas
        self.current_canvas.update()

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

    def keyPressEvent(self, event):
        """Handle key press events."""
        # if ctrl + s is pressed, save the current state
        if event.key() == Qt.Key_S and event.modifiers() == Qt.ControlModifier:
            self.save_current_state()
        else:
            pass
        return super().keyPressEvent(event)
