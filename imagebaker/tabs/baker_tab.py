from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QColorDialog,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig
from imagebaker.core.defs import Annotation, BakingResult, MouseMode
from imagebaker.layers.canvas_layer import CanvasLayer
from imagebaker.list_views import LayerList, LayerSettings
from imagebaker.list_views.canvas_list import CanvasList
from imagebaker.plugins.discovery import discover_plugin_classes


class BakerTab(QWidget):
    """Baker Tab implementation"""

    messageSignal = Signal(str)
    bakingResult = Signal(BakingResult)
    requestTabSwitch = Signal(int)

    def __init__(self, main_window, config: CanvasConfig):
        """Initialize the Baker Tab."""
        super().__init__(main_window)
        self.main_window = main_window
        self.config = config
        self.toolbar = None
        self.plugin_registry = {}
        self.plugin_actions: dict[str, QAction] = {}
        self._updating_plugin_menu = False
        self.main_layout = QVBoxLayout(self)

        # Deque to store multiple CanvasLayer objects with a fixed size
        self.canvases = deque(maxlen=self.config.deque_maxlen)

        # Currently selected canvas
        self.current_canvas = None

        self.init_ui()

    def init_ui(self):
        """Initialize the UI components."""
        # Create toolbar
        self.create_toolbar()

        # Create a single canvas for now
        self.current_canvas = CanvasLayer(parent=self.main_window, config=self.config)
        self.current_canvas.setVisible(True)  # Initially hide all canvases
        self.canvases.append(self.current_canvas)
        self.main_layout.addWidget(self.current_canvas)

        # Create and add CanvasList
        self.canvas_list = CanvasList(self.canvases, parent=self.main_window)
        self.main_window.addDockWidget(Qt.LeftDockWidgetArea, self.canvas_list)

        # Create and add LayerList
        self.layer_settings = LayerSettings(
            parent=self.main_window,
            max_xpos=self.config.max_xpos,
            max_ypos=self.config.max_ypos,
            max_scale=self.config.max_scale,
            max_edge_width=self.config.max_edge_width,
        )
        self.layer_list = LayerList(
            canvas=self.current_canvas,
            parent=self.main_window,
            layer_settings=self.layer_settings,
        )
        self.layer_list.layersSelected.connect(self.sync_plugin_menu_with_selection)
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
        self.layer_settings.beforeLayerEdit.connect(self.capture_undo_state)
        self.current_canvas.messageSignal.connect(self.messageSignal.emit)
        self.current_canvas.bakingResult.connect(self.bakingResult.emit)
        self.current_canvas.layersChanged.connect(self.update_list)
        self.current_canvas.layerRemoved.connect(self.update_list)

        self.canvas_list.canvasSelected.connect(self.on_canvas_selected)
        self.canvas_list.canvasAdded.connect(self.on_canvas_added)
        self.canvas_list.canvasDeleted.connect(self.on_canvas_deleted)
        # self.current_canvas.thumbnailsAvailable.connect(self.generate_state_previews)

    def capture_undo_state(self):
        """Capture an undo snapshot for settings edits."""
        if self.current_canvas is not None:
            self.current_canvas.push_undo_state()

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
        for step, _states in sorted(self.current_canvas.states.items()):
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

    def update_list(self, layer=None):
        """Update the layer list and layer settings."""
        if layer:
            self.layer_list.layers = self.current_canvas.layers
        self.layer_list.update_list()
        selected_layers = (
            [layer for layer in self.current_canvas.layers if layer.selected]
            if self.current_canvas
            else []
        )
        self.sync_plugin_menu_with_selection(selected_layers)
        self.layer_settings.update_sliders()
        self.update()

    def on_canvas_deleted(self, canvas: CanvasLayer):
        """Handle the deletion of a canvas."""
        # Ensure only the currently selected canvas is visible
        if self.canvases:
            self.layer_list.canvas = self.canvases[-1]
            self.layer_list.layers = self.canvases[-1].layers
            self.current_canvas = self.canvases[-1]  # Select the last canvas
            self.current_canvas.setVisible(True)  # Show the last canvas
        else:
            self.current_canvas = None  # No canvases left
            self.messageSignal.emit("No canvases available.")  # Notify the user
            self.layer_list.canvas = None
            self.layer_list.layers = []
            self.layer_settings.selected_layer = None
        self.layer_settings.update_sliders()
        self.canvas_list.update_canvas_list()  # Update the canvas list
        self.layer_list.update_list()
        self.update()

    def on_canvas_selected(self, canvas: CanvasLayer):
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

    def on_canvas_added(self, new_canvas: CanvasLayer):
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

        self.current_canvas.messageSignal.connect(self.messageSignal.emit)
        self.current_canvas.bakingResult.connect(self.bakingResult.emit)
        self.current_canvas.layersChanged.connect(self.update_list)
        self.current_canvas.layerRemoved.connect(self.update_list)

        self.current_canvas.update()
        self.layer_list.layers = new_canvas.layers
        self.layer_list.update_list()
        self.layer_settings.selected_layer = None
        self.layer_settings.update_sliders()

    def create_toolbar(self):
        """Create Baker-specific toolbar."""
        self.toolbar = QWidget()
        baker_toolbar_layout = QHBoxLayout(self.toolbar)
        baker_toolbar_layout.setContentsMargins(5, 5, 5, 5)
        baker_toolbar_layout.setSpacing(10)

        steps_label = QLabel("Steps:")
        steps_label.setStyleSheet("font-weight: bold;")
        baker_toolbar_layout.addWidget(steps_label)

        self.steps_spinbox = QSpinBox()
        self.steps_spinbox.setMinimum(1)
        self.steps_spinbox.setMaximum(1000)
        self.steps_spinbox.setValue(1)
        self.steps_spinbox.valueChanged.connect(self.update_slider_range)
        baker_toolbar_layout.addWidget(self.steps_spinbox)

        baker_modes = [
            ("Export Current State", self.export_current_state),
            ("Save State", self.save_current_state),
            ("Randomize States", self.randomize_states),
            ("Group Layers", self.group_layers),
            ("Convert Ann Type", self.convert_selected_annotation_type),
            ("Predict State", self.predict_state),
            ("Play States", self.play_saved_states),
            ("Clear States", self.clear_states),
            ("Annotate States", self.export_for_annotation),
            ("Export States", self.export_locally),
        ]

        for text, callback in baker_modes:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            baker_toolbar_layout.addWidget(btn)

            if text == "Play States":
                self.timeline_slider = QSlider(Qt.Horizontal)
                self.timeline_slider.setMinimum(0)
                self.timeline_slider.setMaximum(0)
                self.timeline_slider.setValue(0)
                self.timeline_slider.setSingleStep(1)
                self.timeline_slider.setPageStep(1)
                self.timeline_slider.setEnabled(False)
                self.timeline_slider.valueChanged.connect(self.seek_state)
                baker_toolbar_layout.addWidget(self.timeline_slider)

        self.plugin_dropdown_btn = QToolButton()
        self.plugin_dropdown_btn.setText("Plugin Options")
        self.plugin_dropdown_btn.setPopupMode(QToolButton.InstantPopup)
        self.plugin_menu = QMenu(self.plugin_dropdown_btn)
        self.plugin_dropdown_btn.setMenu(self.plugin_menu)
        baker_toolbar_layout.addWidget(self.plugin_dropdown_btn)

        draw_button = QPushButton("Draw")
        draw_button.setCheckable(True)
        draw_button.clicked.connect(self.toggle_drawing_mode)
        baker_toolbar_layout.addWidget(draw_button)

        erase_button = QPushButton("Erase")
        erase_button.setCheckable(True)
        erase_button.clicked.connect(self.toggle_erase_mode)
        baker_toolbar_layout.addWidget(erase_button)

        color_picker_button = QPushButton("Color")
        color_picker_button.clicked.connect(self.open_color_picker)
        baker_toolbar_layout.addWidget(color_picker_button)

        self.grid_btn = QPushButton("Grid")
        self.grid_btn.setCheckable(True)
        self.grid_btn.setChecked(self.config.show_gridlines)
        self.grid_btn.clicked.connect(self.toggle_gridlines)
        baker_toolbar_layout.addWidget(self.grid_btn)

        self.theme_btn = QPushButton("Theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        baker_toolbar_layout.addWidget(self.theme_btn)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        baker_toolbar_layout.addWidget(spacer)

        self.main_layout.addWidget(self.toolbar)

    def toggle_drawing_mode(self):
        """Toggle drawing mode on the current canvas."""
        if self.current_canvas:
            self.current_canvas.mouse_mode = (
                MouseMode.DRAW
                if self.current_canvas.mouse_mode != MouseMode.DRAW
                else MouseMode.IDLE
            )
            mode = self.current_canvas.mouse_mode.name.lower()
            self.messageSignal.emit(f"Drawing mode {mode}.")

    def toggle_erase_mode(self):
        """Toggle drawing mode on the current canvas."""
        if self.current_canvas:
            self.current_canvas.mouse_mode = (
                MouseMode.ERASE
                if self.current_canvas.mouse_mode != MouseMode.ERASE
                else MouseMode.IDLE
            )
            mode = self.current_canvas.mouse_mode.name.lower()
            self.messageSignal.emit(f"Erasing mode {mode}.")

    def open_color_picker(self):
        """Open a color picker dialog to select a custom color."""
        color = QColorDialog.getColor()
        if color.isValid():
            self.current_canvas.drawing_color = color
            self.messageSignal.emit(f"Selected custom color: {color.name()}")

    def toggle_gridlines(self):
        """Toggle lightweight grid overlay."""
        checked = self.grid_btn.isChecked() if hasattr(self, "grid_btn") else False
        self.config.show_gridlines = checked
        if hasattr(self.main_window, "layerify_config"):
            self.main_window.layerify_config.show_gridlines = checked
        if self.current_canvas:
            self.current_canvas.update()
        if hasattr(self.main_window, "layerify_tab") and self.main_window.layerify_tab.layer:
            self.main_window.layerify_tab.layer.update()
        self.messageSignal.emit(f"Gridlines {'enabled' if checked else 'disabled'}.")

    def toggle_theme(self):
        """Toggle app theme."""
        if hasattr(self.main_window, "toggle_theme"):
            self.main_window.toggle_theme()

    def export_for_annotation(self):
        """Export the baked states for annotation."""
        self.messageSignal.emit("Exporting states for prediction...")
        self.requestTabSwitch.emit(0)
        self.current_canvas.export_baked_states(export_to_annotation_tab=True)

    def export_locally(self):
        """Export the baked states locally."""
        self.messageSignal.emit("Exporting baked states...")
        self.current_canvas.export_baked_states()

    def play_saved_states(self):
        """Play the saved states in sequence."""
        self.messageSignal.emit("Playing saved state...")

        # Enable the timeline slider

        # Update the slider range based on the number of states
        if self.current_canvas.states:
            num_states = len(self.current_canvas.states)
            self.timeline_slider.setMaximum(num_states - 1)
            self.steps_spinbox.setValue(
                num_states
            )  # Sync the spinbox with the number of states
            self.timeline_slider.setEnabled(True)
        else:
            self.timeline_slider.setMaximum(0)
            self.steps_spinbox.setValue(1)
            self.messageSignal.emit("No saved states available.")
            self.timeline_slider.setEnabled(False)

        self.timeline_slider.update()
        # Start playing the states
        self.current_canvas.play_states()

    def save_current_state(self):
        """Save the current state of the canvas."""
        self.messageSignal.emit("Saving current state...")
        logger.info(f"Saving current state for {self.steps_spinbox.value()}...")

        self.current_canvas.save_current_state(steps=self.steps_spinbox.value())

        self._reset_steps_input()

        total_states = len(self.current_canvas.states)
        if total_states > 0:
            self.timeline_slider.setMaximum(total_states - 1)
            self.timeline_slider.setEnabled(True)
            self.timeline_slider.setValue(
                self.current_canvas._state_step_index(self.current_canvas.current_step)
            )
        else:
            self.timeline_slider.setMaximum(0)
            self.timeline_slider.setEnabled(False)
        self.timeline_slider.update()

    def _reset_steps_input(self):
        """Reset steps control back to 1 after saving a state."""
        self.steps_spinbox.setValue(1)
        self.steps_spinbox.update()

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

    def randomize_states(self):
        """Randomize states for the current canvas."""
        if not self.current_canvas or not self.current_canvas.layers:
            self.messageSignal.emit("No layers available to randomize.")
            return

        num_states = max(1, self.steps_spinbox.value())
        self.current_canvas.randomize_states(num_states=num_states)
        self.timeline_slider.setMaximum(num_states - 1)
        self.timeline_slider.setEnabled(True)
        self.timeline_slider.setValue(0)
        self.update_list()
        self.messageSignal.emit(f"Created {num_states} randomized state(s).")

    def convert_selected_annotation_type(self):
        """
        Convert annotation type for selected layers.
        rectangle -> polygon, polygon -> rectangle
        """
        if not self.current_canvas or not self.current_canvas.layers:
            self.messageSignal.emit("No layers available.")
            return

        target_layers = [layer for layer in self.current_canvas.layers if layer.selected]
        if not target_layers:
            self.messageSignal.emit("Select one or more layers to convert annotation type.")
            return

        converted = 0
        skipped = 0

        for layer in target_layers:
            if not layer.annotations:
                skipped += 1
                continue

            ann = layer.annotations[0]
            if ann.polygon is not None and len(ann.polygon) >= 3:
                rect = ann.polygon.boundingRect()
                ann.rectangle = rect
                ann.polygon = None
                ann.points = []
                ann.mask = None
                converted += 1
            elif ann.rectangle is not None:
                rect = ann.rectangle
                ann.polygon = QPolygonF(
                    [
                        rect.topLeft(),
                        rect.topRight(),
                        rect.bottomRight(),
                        rect.bottomLeft(),
                    ]
                )
                ann.rectangle = None
                ann.points = []
                ann.mask = None
                converted += 1
            else:
                skipped += 1

            layer._apply_edge_opacity()
            layer.update()

        self.current_canvas.update()
        self.layer_list.update_list()
        self.layer_settings.update_sliders()
        self.messageSignal.emit(
            f"Converted {converted} annotation(s). Skipped {skipped} layer(s)."
        )

    def seek_state(self, step):
        """Seek to a specific state using the timeline slider."""
        self.messageSignal.emit(f"Seeking to step {step}")
        logger.info(f"Seeking to step {step}")
        self.current_canvas.seek_state(step)

        # Update the canvas
        self.current_canvas.update()

    def export_current_state(self):
        """Export the current state as an image."""
        self.messageSignal.emit("Exporting current state...")
        self.current_canvas.export_current_state()

    def predict_state(self):
        """Pass the current state to predict."""
        self.messageSignal.emit("Predicting state...")

        self.current_canvas.predict_state()

    def group_layers(self):
        """Group exactly two selected layers on the current canvas."""
        if self.current_canvas is None:
            return
        grouped = self.current_canvas.group_selected_layers()
        if grouped:
            self.layer_list.update_list()
            self.layer_settings.selected_layer = self.current_canvas.selected_layer
            self.layer_settings.update_sliders()

    def reload_plugins(self):
        """Reload discoverable plugins from project root."""
        self.plugin_registry = discover_plugin_classes(Path.cwd())
        self.plugin_actions.clear()
        self.plugin_menu.clear()

        if not self.plugin_registry:
            placeholder = QAction("No plugins discovered", self.plugin_menu)
            placeholder.setEnabled(False)
            self.plugin_menu.addAction(placeholder)
            self.messageSignal.emit("No plugins discovered in project root.")
            return

        for plugin_name in sorted(self.plugin_registry):
            action = QAction(plugin_name, self.plugin_menu)
            action.setCheckable(True)
            action.toggled.connect(self.on_plugin_selection_changed)
            self.plugin_menu.addAction(action)
            self.plugin_actions[plugin_name] = action

        self.messageSignal.emit(
            f"Discovered {len(self.plugin_registry)} plugin option(s)."
        )
        self.sync_plugin_menu_with_selection()

    def _selected_plugin_classes(self):
        selected = []
        for plugin_name, action in self.plugin_actions.items():
            if action.isChecked() and plugin_name in self.plugin_registry:
                selected.append(self.plugin_registry[plugin_name])
        return selected

    def on_plugin_selection_changed(self, _checked: bool):
        if self._updating_plugin_menu:
            return
        self.apply_plugin_selection()

    def apply_plugin_selection(self):
        """Apply currently checked plugin options to selected layers."""
        if self.current_canvas is None:
            return

        plugin_classes = self._selected_plugin_classes()
        selected_layers = [layer for layer in self.current_canvas.layers if layer.selected]
        if selected_layers:
            self.current_canvas.set_plugins_for_selected_layers(plugin_classes)
        else:
            if not self.current_canvas.layers:
                return
            for layer in self.current_canvas.layers:
                layer.selected = True
            try:
                self.current_canvas.set_plugins_for_selected_layers(plugin_classes)
                self.messageSignal.emit(
                    "No layer selected. Applied plugin options to all layers."
                )
            finally:
                for layer in self.current_canvas.layers:
                    layer.selected = False
                self.current_canvas.selected_layer = None
        self.layer_list.update_list()
        self.layer_settings.update_sliders()

    def sync_plugin_menu_with_selection(self, selected_layers=None):
        """Sync dropdown checks from selected layers' current plugin set."""
        if self.current_canvas is None or not self.plugin_actions:
            return

        if selected_layers is None:
            selected_layers = [
                layer for layer in self.current_canvas.layers if layer.selected
            ]
        if not selected_layers:
            return

        intersection = None
        for layer in selected_layers:
            layer_types = {
                type(plugin)
                for plugin in getattr(layer, "plugins", [])
                if getattr(plugin, "enabled", True)
            }
            if intersection is None:
                intersection = set(layer_types)
            else:
                intersection &= layer_types

        intersection = intersection or set()
        self._updating_plugin_menu = True
        try:
            for plugin_name, action in self.plugin_actions.items():
                plugin_class = self.plugin_registry.get(plugin_name)
                action.setChecked(plugin_class in intersection)
        finally:
            self._updating_plugin_menu = False

    def add_layer(self, layer: CanvasLayer):
        """Add a new layer to the canvas."""
        self.current_canvas.add_layer(layer, center=True, on_top=True)
        self.layer_list.update_list()
        self.layer_settings.selected_layer = self.current_canvas.selected_layer
        self.layer_settings.update_sliders()

    def keyPressEvent(self, event):
        """Handle key press events."""
        handled_by_canvas = (
            event.key() in {Qt.Key_Delete, Qt.Key_H, Qt.Key_W, Qt.Key_S}
            or (
                event.modifiers() == Qt.ControlModifier
                and event.key()
                in {
                    Qt.Key_C,
                    Qt.Key_V,
                    Qt.Key_D,
                    Qt.Key_E,
                    Qt.Key_S,
                    Qt.Key_G,
                    Qt.Key_Z,
                    Qt.Key_Y,
                }
            )
        )
        if handled_by_canvas and self.current_canvas is not None:
            self.current_canvas.handle_key_press(event)
            if event.isAccepted() and event.key() == Qt.Key_S:
                self._reset_steps_input()
            self.current_canvas.update()
            self.layer_list.update_list()
            self.layer_settings.update_sliders()
            if event.isAccepted():
                self.update()
                return

        # Ctrl + N: Add a new layer to the current canvas
        if event.key() == Qt.Key_N and event.modifiers() == Qt.ControlModifier:
            new_layer = CanvasLayer(parent=self.current_canvas)
            new_layer.layer_name = f"Layer {len(self.current_canvas.layers) + 1}"
            new_layer.annotations = [
                Annotation(annotation_id=0, label="New Annotation"),
            ]
            balnk_qimage = QPixmap(self.current_canvas.size())
            balnk_qimage.fill(Qt.transparent)
            new_layer.set_image(balnk_qimage)
            self.current_canvas.add_layer(new_layer, center=True, on_top=True)
            self.current_canvas.update()
            self.layer_list.update_list()
            self.messageSignal.emit(f"Added new layer: {new_layer.layer_name}")
        self.update()
        return super().keyPressEvent(event)

    def save_canvas_to_cache(self, canvas: CanvasLayer, path: Path | None = None):
        """Save the current canvas state to a file."""
        logger.warning("save_canvas_to_cache is not implemented yet.")


