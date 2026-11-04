import json
from collections import deque
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QColorDialog,
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
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
from imagebaker.core.defs import (
    Annotation,
    BakingResult,
    DrawingState,
    LayerState,
    MouseMode,
)
from imagebaker.layers.canvas_layer import CanvasLayer
from imagebaker.list_views import LayerList, LayerSettings
from imagebaker.list_views.canvas_list import CanvasList
from imagebaker.plugins.discovery import discover_plugin_classes
from imagebaker.utils.annotation_formats import (
    dict_to_annotation,
    normalize_annotation_dict,
)


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
        # Restore cached baker state if present
        self.load_canvas_from_cache()

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
        if not getattr(self, "_restoring_cache", False):
            self.save_canvas_to_cache()
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
        """Create Baker-specific toolbar organized into compact, flexible rows."""
        self.toolbar = QWidget()
        main_layout = QVBoxLayout(self.toolbar)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(4)

        # ----------------- Row 1: Timeline Playback & Baking -----------------
        row1 = QWidget()
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(6)

        steps_label = QLabel("Steps:")
        steps_label.setStyleSheet("font-weight: bold;")
        row1_layout.addWidget(steps_label)

        self.steps_spinbox = QSpinBox()
        self.steps_spinbox.setMinimum(1)
        self.steps_spinbox.setMaximum(1000)
        self.steps_spinbox.setValue(1)
        self.steps_spinbox.valueChanged.connect(self.update_slider_range)
        row1_layout.addWidget(self.steps_spinbox)

        self.play_btn = QPushButton("▶ Play States")
        self.play_btn.setCheckable(True)
        self.play_btn.clicked.connect(self.play_saved_states)
        row1_layout.addWidget(self.play_btn)

        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setMinimum(0)
        self.timeline_slider.setMaximum(0)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setSingleStep(1)
        self.timeline_slider.setPageStep(1)
        self.timeline_slider.setEnabled(False)
        self.timeline_slider.valueChanged.connect(self.seek_state)
        self.timeline_slider.setMinimumWidth(100)
        row1_layout.addWidget(self.timeline_slider)

        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.setToolTip("Clear saved timeline states")
        clear_btn.clicked.connect(self.clear_states)
        row1_layout.addWidget(clear_btn)

        row1_spacer = QWidget()
        row1_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row1_layout.addWidget(row1_spacer)

        save_btn = QPushButton("💾 Save State")
        save_btn.setStyleSheet("font-weight: bold;")
        save_btn.setToolTip("Save current layers layout as keyframe state (Ctrl+S)")
        save_btn.clicked.connect(self.save_current_state)
        row1_layout.addWidget(save_btn)

        rand_btn = QPushButton("🎲 Randomize")
        rand_btn.clicked.connect(self.randomize_states)
        row1_layout.addWidget(rand_btn)

        export_curr_btn = QPushButton("📤 Export Current")
        export_curr_btn.clicked.connect(self.export_current_state)
        row1_layout.addWidget(export_curr_btn)

        export_states_btn = QPushButton("📦 Export States")
        export_states_btn.clicked.connect(self.export_locally)
        row1_layout.addWidget(export_states_btn)

        annotate_btn = QPushButton("🧅 Annotate States")
        annotate_btn.clicked.connect(self.export_for_annotation)
        row1_layout.addWidget(annotate_btn)

        main_layout.addWidget(row1)

        # ----------------- Row 2: Composition & Layer Tools -----------------
        row2 = QWidget()
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(6)

        comp_tag = QLabel("Composition:")
        comp_tag.setStyleSheet("font-weight: bold;")
        row2_layout.addWidget(comp_tag)

        group_btn = QPushButton("Group")
        group_btn.clicked.connect(self.group_layers)
        row2_layout.addWidget(group_btn)

        conv_btn = QPushButton("Convert Geometry")
        conv_btn.clicked.connect(self.convert_selected_annotation_type)
        row2_layout.addWidget(conv_btn)

        predict_state_btn = QPushButton("🔮 Predict State")
        predict_state_btn.clicked.connect(self.predict_state)
        row2_layout.addWidget(predict_state_btn)

        self.plugin_dropdown_btn = QToolButton()
        self.plugin_dropdown_btn.setText("🧩 Plugins")
        self.plugin_dropdown_btn.setPopupMode(QToolButton.InstantPopup)
        self.plugin_menu = QMenu(self.plugin_dropdown_btn)
        self.plugin_dropdown_btn.setMenu(self.plugin_menu)
        row2_layout.addWidget(self.plugin_dropdown_btn)

        row2_spacer = QWidget()
        row2_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row2_layout.addWidget(row2_spacer)

        draw_button = QPushButton("🖌️ Draw")
        draw_button.setCheckable(True)
        draw_button.clicked.connect(self.toggle_drawing_mode)
        row2_layout.addWidget(draw_button)

        erase_button = QPushButton("🧹 Erase")
        erase_button.setCheckable(True)
        erase_button.clicked.connect(self.toggle_erase_mode)
        row2_layout.addWidget(erase_button)

        color_picker_button = QPushButton("🎨 Color")
        color_picker_button.clicked.connect(self.open_color_picker)
        row2_layout.addWidget(color_picker_button)

        self.grid_btn = QPushButton("Grid")
        self.grid_btn.setCheckable(True)
        self.grid_btn.setChecked(self.config.show_gridlines)
        self.grid_btn.clicked.connect(self.toggle_gridlines)
        row2_layout.addWidget(self.grid_btn)

        self.theme_btn = QPushButton("Theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        row2_layout.addWidget(self.theme_btn)

        main_layout.addWidget(row2)
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

    def _select_export_format(
        self, title: str = "Select Annotation Format"
    ) -> str | None:
        items = [
            "default (ImageBaker JSON)",
            "coco (COCO JSON)",
            "yolo (YOLO TXT)",
        ]
        choice, ok = QInputDialog.getItem(
            self, title, "Annotation Format:", items, 0, False
        )
        if not ok or not choice:
            return None
        return choice.split()[0].strip().lower()

    def export_locally(self, annotation_format: str | None = None):
        """Export the baked states locally."""
        fmt = annotation_format
        if fmt is None and self.isVisible():
            fmt = self._select_export_format("Export Baked States Format")
            if fmt is None:
                return
        fmt = fmt or "default"
        self.messageSignal.emit(f"Exporting baked states ({fmt.upper()})...")
        self.current_canvas.export_baked_states(annotation_format=fmt)

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

    def save_current_state(self, prompt_download: bool = True):
        """Save the current state of the canvas and optionally prompt to download/export."""
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
        self.save_canvas_to_cache()

        if prompt_download and self.isVisible() and total_states > 0:
            reply = QMessageBox.question(
                self,
                "Download / Export Saved States",
                "State saved! Do you want to download/export the baked states and annotations now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                fmt = self._select_export_format("Select Download Annotation Format")
                if fmt:
                    self.export_locally(annotation_format=fmt)

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
        self.save_canvas_to_cache()

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
        self.save_canvas_to_cache()
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

    def export_current_state(self, annotation_format: str | None = None):
        """Export the current state as an image and annotations."""
        fmt = annotation_format
        if fmt is None and self.isVisible():
            fmt = self._select_export_format("Export Current State Format")
            if fmt is None:
                return
        fmt = fmt or "default"
        self.messageSignal.emit(f"Exporting current state ({fmt.upper()})...")
        self.current_canvas.export_current_state(annotation_format=fmt)

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
        self.save_canvas_to_cache()

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

    @property
    def baker_cache_file(self) -> Path:
        return self.config.cache_dir / "baker_cache.json"

    @property
    def baker_layers_dir(self) -> Path:
        folder = self.config.cache_dir / "baker_layers"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def save_canvas_to_cache(
        self, canvas: CanvasLayer | None = None, path: Path | None = None
    ) -> Path:
        """Persist Baker canvases, layers, and saved timeline states to cache."""
        cache_path = Path(path) if path else self.baker_cache_file
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _ = self.baker_layers_dir  # ensure folder exists

        target_canvases = [canvas] if canvas is not None else list(self.canvases)
        canvases_payload = []

        for idx, cv in enumerate(target_canvases, start=1):
            if cv is None:
                continue
            cv_id = str(getattr(cv, "layer_id", f"canvas_{idx}"))
            layers_payload = []
            for order, layer in enumerate(cv.layers):
                lid = str(layer.layer_id)
                img_rel = f"baker_layers/layer_{lid}.png"
                img_abs = self.config.cache_dir / img_rel
                source_img = getattr(layer, "_original_image", None)
                if source_img is None or source_img.isNull():
                    source_img = layer.image
                if source_img is not None and not source_img.isNull():
                    source_img.save(str(img_abs), "PNG")

                ann_dict = (
                    normalize_annotation_dict(layer.annotations[0], order + 1)
                    if getattr(layer, "annotations", None)
                    else None
                )
                lbl = (
                    ann_dict["label"]
                    if ann_dict
                    else getattr(layer, "current_label", "Undefined") or "Undefined"
                )
                col = (
                    ann_dict["color"]
                    if ann_dict
                    else [255, 255, 255]
                )
                drawings_payload = [
                    {
                        "x": float(d.position.x()),
                        "y": float(d.position.y()),
                        "color": [d.color.red(), d.color.green(), d.color.blue()],
                        "size": int(d.size),
                    }
                    for d in getattr(layer.layer_state, "drawing_states", [])
                ]
                plugin_names = [
                    getattr(p, "name", type(p).__name__)
                    for p in getattr(layer, "plugins", [])
                    if getattr(p, "enabled", True)
                ]
                layers_payload.append(
                    {
                        "layer_id": lid,
                        "name": layer.layer_name,
                        "label": lbl,
                        "color": col,
                        "image_file": img_rel,
                        "source_image": str(getattr(layer, "file_path", "") or ""),
                        "visible": bool(layer.visible),
                        "allow_export": bool(layer.allow_annotation_export),
                        "order": int(order),
                        "x": float(layer.position.x()),
                        "y": float(layer.position.y()),
                        "scale_x": float(layer.scale_x),
                        "scale_y": float(layer.scale_y),
                        "rotation": float(layer.rotation),
                        "opacity": float(layer.opacity),
                        "edge_opacity": int(layer.edge_opacity),
                        "edge_width": int(layer.edge_width),
                        "caption": str(layer.caption or ""),
                        "plugins": plugin_names,
                        "drawings": drawings_payload,
                        "annotation": ann_dict,
                    }
                )

            states_payload = {}
            for step_key, step_states in sorted(cv.states.items()):
                states_payload[str(step_key)] = [
                    {
                        "layer_id": str(st.layer_id),
                        "layer_name": str(st.layer_name),
                        "x": float(st.position.x()),
                        "y": float(st.position.y()),
                        "scale_x": float(st.scale_x),
                        "scale_y": float(st.scale_y),
                        "rotation": float(st.rotation),
                        "opacity": float(st.opacity),
                        "edge_opacity": int(st.edge_opacity),
                        "edge_width": int(st.edge_width),
                        "order": int(st.order),
                        "visible": bool(st.visible),
                        "allow_export": bool(st.allow_annotation_export),
                        "caption": str(st.caption or ""),
                        "drawings": [
                            {
                                "x": float(d.position.x()),
                                "y": float(d.position.y()),
                                "color": [d.color.red(), d.color.green(), d.color.blue()],
                                "size": int(d.size),
                            }
                            for d in getattr(st, "drawing_states", [])
                        ],
                    }
                    for st in step_states
                ]

            canvases_payload.append(
                {
                    "canvas_id": cv_id,
                    "name": cv.layer_name,
                    "width": max(1, cv.width()),
                    "height": max(1, cv.height()),
                    "current_step": int(getattr(cv, "current_step", 0)),
                    "layers": layers_payload,
                    "states": states_payload,
                }
            )

        active_id = (
            str(self.current_canvas.layer_id)
            if self.current_canvas is not None
            else (canvases_payload[0]["canvas_id"] if canvases_payload else "")
        )
        payload = {
            "version": 1,
            "active_canvas_id": active_id,
            "canvases": canvases_payload,
        }
        try:
            cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to write Baker cache {cache_path}: {exc}")
        return cache_path

    def load_canvas_from_cache(self, path: Path | None = None) -> bool:
        """Load Baker canvases, layers, and saved timeline states from cache."""
        cache_path = Path(path) if path else self.baker_cache_file
        if not cache_path.exists():
            return False

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Failed to read Baker cache {cache_path}: {exc}")
            return False

        canvases_data = payload.get("canvases", [])
        if not canvases_data or not self.current_canvas:
            return False

        self._restoring_cache = True
        try:
            first_cv_data = canvases_data[0]
            cv = self.current_canvas
            cv.layers.clear()
            cv.states.clear()
            cv.layer_name = first_cv_data.get("name", cv.layer_name)

            for ldata in first_cv_data.get("layers", []):
                img_rel = ldata.get("image_file", "")
                img_path = self.config.cache_dir / img_rel
                if not img_path.exists():
                    continue
                pix = QPixmap(str(img_path))
                if pix.isNull():
                    continue

                new_layer = CanvasLayer(parent=cv, config=self.config)
                try:
                    new_layer.layer_id = int(ldata["layer_id"])
                except (ValueError, TypeError):
                    new_layer.layer_id = ldata["layer_id"]
                new_layer.layer_name = ldata.get("name", "Layer")
                new_layer.set_image(pix)
                new_layer.position = QPointF(
                    float(ldata.get("x", 0.0)), float(ldata.get("y", 0.0))
                )
                new_layer.scale_x = float(ldata.get("scale_x", 1.0))
                new_layer.scale_y = float(ldata.get("scale_y", 1.0))
                new_layer.rotation = float(ldata.get("rotation", 0.0))
                new_layer.opacity = float(ldata.get("opacity", 255.0))
                new_layer.edge_opacity = int(ldata.get("edge_opacity", 255))
                new_layer.edge_width = int(ldata.get("edge_width", 1))
                new_layer.visible = bool(ldata.get("visible", True))
                new_layer.allow_annotation_export = bool(ldata.get("allow_export", True))
                new_layer.order = int(ldata.get("order", len(cv.layers)))
                new_layer.caption = str(ldata.get("caption", ""))
                new_layer.drawing_states = [
                    DrawingState(
                        position=QPointF(float(d.get("x", 0.0)), float(d.get("y", 0.0))),
                        color=QColor(*d.get("color", [255, 0, 0])),
                        size=int(d.get("size", 5)),
                    )
                    for d in ldata.get("drawings", [])
                ]
                ann_raw = ldata.get("annotation")
                if isinstance(ann_raw, dict):
                    new_layer.annotations = [dict_to_annotation(ann_raw)]
                else:
                    new_layer.annotations = [
                        Annotation(
                            annotation_id=1,
                            label=str(ldata.get("label", "Undefined")),
                            color=QColor(*ldata.get("color", [255, 255, 255])),
                        )
                    ]
                new_layer._apply_edge_opacity()
                cv.layers.append(new_layer)

            for step_str, step_states in first_cv_data.get("states", {}).items():
                try:
                    step_int = int(step_str)
                except ValueError:
                    continue
                restored_states = []
                for sdata in step_states:
                    lid_raw = sdata.get("layer_id", "")
                    try:
                        lid_val = int(lid_raw)
                    except (ValueError, TypeError):
                        lid_val = lid_raw
                    st = LayerState(
                        layer_id=lid_val,
                        state_step=step_int,
                        layer_name=str(sdata.get("layer_name", "Layer")),
                        opacity=float(sdata.get("opacity", 255.0)),
                        position=QPointF(
                            float(sdata.get("x", 0.0)), float(sdata.get("y", 0.0))
                        ),
                        rotation=float(sdata.get("rotation", 0.0)),
                        scale_x=float(sdata.get("scale_x", 1.0)),
                        scale_y=float(sdata.get("scale_y", 1.0)),
                        order=int(sdata.get("order", 0)),
                        visible=bool(sdata.get("visible", True)),
                        allow_annotation_export=bool(sdata.get("allow_export", True)),
                        edge_opacity=int(sdata.get("edge_opacity", 255)),
                        edge_width=int(sdata.get("edge_width", 1)),
                        caption=str(sdata.get("caption", "")),
                        drawing_states=[
                            DrawingState(
                                position=QPointF(
                                    float(d.get("x", 0.0)), float(d.get("y", 0.0))
                                ),
                                color=QColor(*d.get("color", [255, 0, 0])),
                                size=int(d.get("size", 5)),
                            )
                            for d in sdata.get("drawings", [])
                        ],
                    )
                    restored_states.append(st)
                cv.states[step_int] = restored_states

            if cv.states:
                cv.current_step = int(first_cv_data.get("current_step", 0))
                self.timeline_slider.setMaximum(max(0, len(cv.states) - 1))
                self.timeline_slider.setEnabled(True)

            self.layer_list.layers = cv.layers
            self.layer_list.update_list()
            self.canvas_list.update_canvas_list()
            cv.update()
            return True
        except Exception as exc:
            logger.warning(f"Failed to restore Baker cache: {exc}")
            return False
        finally:
            self._restoring_cache = False


