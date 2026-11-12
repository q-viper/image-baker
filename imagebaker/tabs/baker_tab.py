from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QPixmap
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
from imagebaker.core.defs import (
    Annotation,
    BakingResult,
    MouseMode,
)
from imagebaker.layers.canvas_layer import CanvasLayer
from imagebaker.list_views import LayerList, LayerSettings
from imagebaker.list_views.canvas_list import CanvasList
from imagebaker.tabs.baker_cache import BakerCacheMixin
from imagebaker.tabs.baker_states_plugins import BakerStatesPluginsMixin


class BakerTab(BakerStatesPluginsMixin, BakerCacheMixin, QWidget):
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
        self.canvas_list.blankLayerRequested.connect(self.add_blank_layer)
        # Discover plugins immediately and restore cached baker state if present
        self.reload_plugins()
        self.load_canvas_from_cache()
        self._update_timeline_step_label()

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

        undo_btn = QPushButton("↶ Undo")
        undo_btn.setToolTip("Undo layer change (Ctrl+Z)")
        undo_btn.clicked.connect(self.undo_canvas)
        row1_layout.addWidget(undo_btn)

        redo_btn = QPushButton("↷ Redo")
        redo_btn.setToolTip("Redo layer change (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_canvas)
        row1_layout.addWidget(redo_btn)

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

        self.timeline_step_label = QLabel("0 / 0")
        self.timeline_step_label.setMinimumWidth(36)
        row1_layout.addWidget(self.timeline_step_label)

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
        group_btn.setToolTip("Merge 2 selected layers into a single layer (Ctrl+G)")
        group_btn.clicked.connect(self.group_layers)
        row2_layout.addWidget(group_btn)

        ungroup_btn = QPushButton("Ungroup")
        ungroup_btn.setToolTip("Ungroup selected grouped layer back into individual layers")
        ungroup_btn.clicked.connect(self.ungroup_layers)
        row2_layout.addWidget(ungroup_btn)

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

    def add_layer(self, layer: CanvasLayer):
        """Add a new layer to the canvas."""
        self.current_canvas.add_layer(layer, center=True, on_top=True)
        self.layer_list.update_list()
        self.layer_settings.selected_layer = self.current_canvas.selected_layer
        self.layer_settings.update_sliders()
        self.save_canvas_to_cache()

    def keyPressEvent(self, event):
        """Handle key press events."""
        if event.key() == Qt.Key_Space and event.modifiers() == Qt.NoModifier:
            self.play_saved_states()
            event.accept()
            return

        handled_by_canvas = (
            event.key()
            in {
                Qt.Key_Delete,
                Qt.Key_Backspace,
                Qt.Key_Escape,
                Qt.Key_H,
                Qt.Key_W,
                Qt.Key_S,
                Qt.Key_D,
                Qt.Key_E,
                Qt.Key_R,
                Qt.Key_P,
                Qt.Key_Up,
                Qt.Key_Down,
                Qt.Key_Left,
                Qt.Key_Right,
            }
            or (
                bool(event.modifiers() & Qt.ControlModifier)
                and event.key()
                in {
                    Qt.Key_A,
                    Qt.Key_C,
                    Qt.Key_V,
                    Qt.Key_D,
                    Qt.Key_E,
                    Qt.Key_S,
                    Qt.Key_W,
                    Qt.Key_G,
                    Qt.Key_Z,
                    Qt.Key_Y,
                    Qt.Key_Up,
                    Qt.Key_Down,
                }
            )
        )
        if handled_by_canvas and self.current_canvas is not None:
            self.current_canvas.handle_key_press(event)
            if (
                event.isAccepted()
                and event.key() == Qt.Key_S
                and (event.modifiers() & Qt.ControlModifier)
            ):
                self._reset_steps_input()
                total_states = len(self.current_canvas.states)
                if total_states > 0:
                    self.timeline_slider.setMaximum(total_states - 1)
                    self.timeline_slider.setEnabled(True)
                    self.timeline_slider.setValue(
                        self.current_canvas._state_step_index(
                            self.current_canvas.current_step
                        )
                    )
            self.current_canvas.update()
            self.layer_list.update_list()
            self.layer_settings.update_sliders()
            if event.isAccepted():
                self.update()
                return

        # Ctrl + N: Add a new layer to the current canvas
        if event.key() == Qt.Key_N and event.modifiers() == Qt.ControlModifier:
            self.add_blank_layer()
        self.update()
        return super().keyPressEvent(event)

    def add_blank_layer(self):
        """Add a blank drawable layer to the current canvas."""
        if self.current_canvas is None:
            return
        new_layer = CanvasLayer(parent=self.current_canvas)
        new_layer.layer_name = f"Layer {len(self.current_canvas.layers) + 1}"
        new_layer.annotations = [
            Annotation(annotation_id=0, label="New Annotation"),
        ]
        blank_pixmap = QPixmap(self.current_canvas.size())
        blank_pixmap.fill(Qt.transparent)
        new_layer.set_image(blank_pixmap)
        self.current_canvas.add_layer(new_layer, center=True, on_top=True)
        self.current_canvas.update()
        self.layer_list.update_list()
        self.messageSignal.emit(f"Added new layer: {new_layer.layer_name}")
