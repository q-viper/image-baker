# TODO: Use Signal and Slot for communication instead of passing objects around
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QDockWidget,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QCheckBox,
    QDialog,
)

# from imagebaker.tab_views import BaseLayer
from imagebaker.layers.canvas_layer import CanvasLayer as Canvas
from .layer_settings import LayerSettings
from imagebaker import logger
from imagebaker.layers.base_layer import BaseLayer


class LayerList(QDockWidget):

    layersSelected = Signal(list)
    messageSignal = Signal(str)

    def __init__(
        self,
        canvas: Canvas,
        layer_settings: LayerSettings,
        parent=None,
    ):
        super().__init__("Layers", parent)
        self.canvas = canvas
        self.layers: list[BaseLayer] = []
        self.layer_settings = layer_settings
        self.init_ui()

    def init_ui(self):
        logger.info("Initializing LayerList")
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        self.setMinimumWidth(150)

        # Create list widget for layers
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.MultiSelection)

        # Enable drag and drop in the list widget
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDropIndicatorShown(True)
        self.list_widget.setDragDropMode(QAbstractItemView.InternalMove)

        # Connect signals
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        self.list_widget.model().rowsMoved.connect(self.on_rows_moved)
        self.list_widget.keyPressEvent = self.list_key_press_event

        # Add list and buttons to main layout
        main_layout.addWidget(self.list_widget)
        # main_layout.addWidget(delete_button)

        # Set main widget
        self.setWidget(main_widget)
        self.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )

    def clear_layers(self):
        """Clear all layers from the list"""
        self.layers.clear()
        self.update_list()

    def on_rows_moved(self, parent, start, end, destination, row):
        """Handle rows being moved in the list widget via drag and drop"""
        # Calculate the source and destination indices
        source_index = start
        dest_index = row

        # If moving down, we need to adjust the destination index
        if dest_index > source_index:
            dest_index -= 1

        # Reorder the layers accordingly
        if 0 <= source_index < len(self.layers) and 0 <= dest_index < len(self.layers):
            # Move the layer in our internal list
            layer = self.layers.pop(source_index)
            self.layers.insert(dest_index, layer)
            layer.order = dest_index

            # Update the canvas with the new layer order
            self.canvas.layers = self.layers
            self.canvas.update()

            # Update the UI
            self.update_list()
            logger.info(
                f"BaseLayer: {layer.layer_name} moved from {source_index} to {dest_index}"
            )

    def update_list(self):
        """Update the list widget with current layers"""
        # Remember current selection
        selected_row = self.list_widget.currentRow()

        # Clear the list
        self.list_widget.clear()
        selected_layer = None

        if not self.canvas:
            # No canvas, show dialog and return
            logger.warning("No canvas found")
            QDialog.critical(
                self,
                "Error",
                "No canvas found. Please create a canvas first.",
                QDialog.StandardButton.Ok,
            )

        # Add all layers to the list
        for idx, layer in enumerate(self.layers):
            if layer.selected:
                selected_layer = layer

            # Get annotation info
            ann = layer.annotations[0]
            thumbnail = layer.get_thumbnail(annotation=ann)

            # Create widget for this layer item
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 5, 5, 5)

            # Add thumbnail
            thumbnail_label = QLabel()
            thumbnail_label.setPixmap(thumbnail)
            layout.addWidget(thumbnail_label)

            # Add text info
            text_container = QWidget()
            text_layout = QVBoxLayout(text_container)

            # Main label
            main_label = QLabel(ann.label)
            text_color = "#666" if not layer.visible else "black"
            if layer.selected:
                text_color = "blue"
            main_label.setStyleSheet(f"font-weight: bold; color: {text_color};")
            text_layout.addWidget(main_label)

            # Add secondary info if available
            secondary_text = []
            score_text = (
                f"{ann.annotator}: {ann.score:.2f}"
                if ann.score is not None
                else ann.annotator
            )
            secondary_text.append(score_text)
            short_path = ann.file_path.stem
            secondary_text.append(f"<span style='color:#666;'>{short_path}</span>")

            if secondary_text:
                info_color = "#888" if not layer.visible else "#444"
                info_label = QLabel("<br>".join(secondary_text))
                info_label.setStyleSheet(f"color: {info_color}; font-size: 10px;")
                info_label.setTextFormat(Qt.RichText)
                text_layout.addWidget(info_label)

            text_layout.addStretch()
            layout.addWidget(text_container)
            layout.addStretch()

            # Add control buttons
            btn_container = QWidget()
            btn_layout = QHBoxLayout(btn_container)

            # Visibility button
            vis_btn = QPushButton("👀" if layer.visible else "👁️")
            vis_btn.setMaximumWidth(self.canvas.config.normal_draw_config.button_width)
            vis_btn.setCheckable(True)
            vis_btn.setChecked(layer.visible)
            vis_btn.setToolTip("Visible" if layer.visible else "Hidden")

            # Store layer index for button callbacks
            vis_btn.setProperty("layer_index", idx)
            vis_btn.clicked.connect(
                lambda checked, btn=vis_btn: self.toggle_visibility(
                    btn.property("layer_index")
                )
            )
            btn_layout.addWidget(vis_btn)

            # Delete button
            del_btn = QPushButton("🗑️")
            del_btn.setMaximumWidth(self.canvas.config.normal_draw_config.button_width)
            del_btn.setToolTip("Delete annotation")
            del_btn.setProperty("layer_index", idx)
            del_btn.clicked.connect(
                lambda checked=False, idx=idx: self.confirm_delete_layer(idx)
            )
            btn_layout.addWidget(del_btn)

            # a checkbox to toggle layer annotation export
            export_checkbox = QCheckBox()
            export_checkbox.setChecked(layer.allow_annotation_export)
            export_checkbox.setToolTip("Toggle annotation export")
            export_checkbox.setProperty("layer_index", idx)
            export_checkbox.stateChanged.connect(
                lambda state, idx=idx: self.toggle_annotation_export(idx, state)
            )
            btn_layout.addWidget(export_checkbox)

            layout.addWidget(btn_container)

            # Add item to list widget
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

        # Restore selection if possible
        if selected_row >= 0 and selected_row < self.list_widget.count():
            self.list_widget.setCurrentRow(selected_row)

        # Update layer settings panel
        if selected_layer:
            self.layer_settings.set_selected_layer(selected_layer)
        else:
            self.layer_settings.set_selected_layer(None)
        self.update()

    def toggle_annotation_export(self, index, state):
        """Toggle annotation export for a layer by index"""
        if 0 <= index < len(self.layers):
            layer = self.layers[index]
            layer.allow_annotation_export = not layer.allow_annotation_export
            logger.info(
                f"BaseLayer annotation export toggled: {layer.layer_name}, {layer.allow_annotation_export}"
            )
            self.update_list()
            layer.update()
            self.canvas.update()

    def on_item_clicked(self, item):
        """Handle layer selection with:
        - Left click only: Toggle clicked layer and deselect others
        - Ctrl+Left click: Toggle clicked layer only (keep others selected)"""
        modifiers = QApplication.keyboardModifiers()
        current_row = self.list_widget.row(item)

        if 0 <= current_row < len(self.layers):
            current_layer = self.layers[current_row]

            if modifiers & Qt.ControlModifier:
                # Ctrl+Click: Toggle just this layer's selection
                current_layer.selected = not current_layer.selected
                selected_layers = [layer for layer in self.layers if layer.selected]
            else:
                # Normal click: Toggle this layer and deselect all others
                was_selected = current_layer.selected
                for layer in self.layers:
                    layer.selected = False
                current_layer.selected = not was_selected  # Toggle
                selected_layers = [current_layer] if current_layer.selected else []

            # Update UI
            self.layersSelected.emit(selected_layers)
            self.layer_settings.set_selected_layer(
                selected_layers[0] if selected_layers else None
            )
            self.canvas.update()
            self.update_list()

            logger.info(f"Selected layers: {[l.layer_name for l in selected_layers]}")

    def on_layer_selected(self, indices):
        """Select multiple layers by indices"""
        selected_layers = []
        for i, layer in enumerate(self.layers):
            if i in indices:
                layer.selected = True
                selected_layers.append(layer)
            else:
                layer.selected = False

        # Emit the selected layers
        self.layersSelected.emit(selected_layers)

        # Update UI
        self.layer_settings.set_selected_layer(
            selected_layers[0] if selected_layers else None
        )
        self.canvas.update()
        self.update_list()

    def confirm_delete_layer(self, index):
        """Show confirmation dialog before deleting a layer"""
        if 0 <= index < len(self.layers):
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Question)
            msg_box.setWindowTitle("Confirm Deletion")
            msg_box.setText("Are you sure you want to delete this layer?")
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg_box.setDefaultButton(QMessageBox.No)

            result = msg_box.exec_()
            if result == QMessageBox.Yes:
                self.delete_layer(index)

    def list_key_press_event(self, event):
        """Handle key press events in the list widget"""
        if event.key() == Qt.Key_Delete:
            current_row = self.list_widget.currentRow()
            if current_row >= 0:
                self.confirm_delete_layer(current_row)
        else:
            # Pass other key events to the parent class
            QListWidget.keyPressEvent(self.list_widget, event)

    def delete_selected_layer(self):
        """Delete the currently selected layer with confirmation"""
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            self.confirm_delete_layer(current_row)

    def delete_layer(self, index):
        """Delete a layer by index"""
        if 0 <= index < len(self.layers):
            logger.info(f"Deleting layer: {self.layers[index].layer_name}")
            del self.layers[index]
            self.update_list()
            self.canvas.layers = self.layers
            self.canvas.update()
            logger.info(f"BaseLayer deleted: {index}")

    def toggle_visibility(self, index):
        """Toggle visibility of a layer by index"""
        if 0 <= index < len(self.layers):
            layer = self.layers[index]
            layer.visible = not layer.visible
            logger.info(
                f"BaseLayer visibility toggled: {layer.layer_name}, {layer.visible}"
            )
            self.update_list()
            self.canvas.update()

    def add_layer(self, layer: BaseLayer = None):
        """Add a new layer to the list"""
        if layer is None:
            return
        self.layers.append(layer)
        self.update_list()
        self.canvas.layers = self.layers
        # self.canvas.update()

    def select_layer(self, layer):
        """Select a specific layer"""
        logger.info(f"Selecting layer: {layer.layer_name}")
        self.update_list()

    def get_selected_layers(self):
        """Returns list of currently selected BaseLayer objects"""
        selected_items = self.list_widget.selectedItems()
        return [
            self.layers[self.list_widget.row(item)]
            for item in selected_items
            if 0 <= self.list_widget.row(item) < len(self.layers)
        ]

    def keyPressEvent(self, event):
        """Handle key presses."""
        self.selected_layer = self.canvas.selected_layer
        if self.selected_layer is None:
            return
        if event.key() == Qt.Key_Delete:
            self.canvas.delete_layer()
        elif event.key() == Qt.Key_Escape:
            self.canvas.selected_layer = None
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self.canvas.copy_layer()
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self.canvas.paste_layer()
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Z:
            # self.selected_layer.undo()
            self.messageSignal.emit("Undo not implemented yet")
