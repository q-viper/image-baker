from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSizePolicy,
    QDockWidget,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
)
from functools import partial
from imagebaker.layers.canvas_layer import CanvasLayer
from imagebaker import logger


class CanvasList(QDockWidget):
    canvasSelected = Signal(CanvasLayer)
    canvasDeleted = Signal(CanvasLayer)
    canvasAdded = Signal(CanvasLayer)

    def __init__(self, canvases: list[CanvasLayer], parent=None):
        """
        :param canvases: List of CanvasLayer objects to display.
        """
        super().__init__("Canvas List", parent)
        self.canvases = canvases
        self.current_page = 0
        self.canvases_per_page = 10
        self.init_ui()

    def init_ui(self):
        """Initialize the UI for the canvas list panel."""
        logger.info("Initializing CanvasList")
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Add "Create New Canvas" button
        self.create_canvas_button = QPushButton("Create New Canvas")
        self.create_canvas_button.clicked.connect(self.create_new_canvas)
        layout.addWidget(self.create_canvas_button)

        # Canvas list widget
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.handle_item_clicked)
        layout.addWidget(self.list_widget)
        # set first item as selected
        if len(self.canvases) > 0:
            self.list_widget.setCurrentRow(0)

        # Pagination controls
        pagination_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton("Prev")
        self.prev_page_btn.clicked.connect(self.show_prev_page)
        self.next_page_btn = QPushButton("Next")
        self.next_page_btn.clicked.connect(self.show_next_page)
        pagination_layout.addWidget(self.prev_page_btn)
        pagination_layout.addWidget(self.next_page_btn)
        layout.addLayout(pagination_layout)

        # Pagination info
        self.pagination_label = QLabel("Showing 0 of 0")
        layout.addWidget(self.pagination_label)

        self.setWidget(widget)
        self.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )

        self.update_canvas_list()

    def create_new_canvas(self):
        """Create a new canvas and emit the canvasAdded signal."""
        canvas_idx = len(self.canvases) + 1
        default_name = f"Canvas {canvas_idx}"

        # Show input dialog to ask for canvas name
        canvas_name, ok = QInputDialog.getText(
            self, "New Canvas", "Enter canvas name:", text=default_name
        )

        # If the user cancels or provides an empty name, use the default name
        if not ok or not canvas_name.strip():
            canvas_name = default_name

        # Create the new canvas
        new_canvas = CanvasLayer(parent=self.parent())
        new_canvas.layer_name = canvas_name  # Assign the name to the canvas
        self.canvases.append(new_canvas)  # Add the new canvas to the list
        self.canvasAdded.emit(
            new_canvas
        )  # Emit the signal to notify about the new canvas
        self.update_canvas_list()  # Refresh the canvas list

    def show_next_page(self):
        """Show the next page of canvases."""
        if (self.current_page + 1) * self.canvases_per_page < len(self.canvases):
            self.current_page += 1
            self.update_canvas_list()

    def show_prev_page(self):
        """Show the previous page of canvases."""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_canvas_list()

    def update_canvas_list(self):
        """Update the canvas list with pagination."""
        self.list_widget.clear()

        canvases_list = list(self.canvases)

        start_idx = self.current_page * self.canvases_per_page
        end_idx = min(start_idx + self.canvases_per_page, len(canvases_list))

        for idx, canvas in enumerate(canvases_list[start_idx:end_idx], start=start_idx):
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 5, 5, 5)

            # Thumbnail
            thumbnail_label = QLabel()
            thumbnail_pixmap = canvas.get_thumbnail().scaled(
                50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            thumbnail_label.setPixmap(thumbnail_pixmap)
            item_layout.addWidget(thumbnail_label)

            # Canvas name
            canvas_name = getattr(canvas, "layer_name", f"Canvas {idx + 1}")
            name_label = QLabel(canvas_name)
            name_label.setStyleSheet("font-weight: bold;")
            item_layout.addWidget(name_label)

            # Delete button
            delete_button = QPushButton("Delete")
            delete_button.setStyleSheet(
                "background-color: red; color: white; font-weight: bold;"
            )
            delete_button.clicked.connect(partial(self.delete_canvas, canvas))
            item_layout.addWidget(delete_button)

            item_layout.addStretch()

            # Add the custom widget to the list
            list_item = QListWidgetItem(self.list_widget)
            list_item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)

            # Store metadata for the canvas
            list_item.setData(Qt.UserRole, canvas)

        # Select the first item by default if it exists
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            first_item = self.list_widget.item(0)
            self.handle_item_clicked(first_item)

        self.pagination_label.setText(
            f"Showing {start_idx + 1} to {end_idx} of {len(canvases_list)}"
        )
        self.update()

    def handle_item_clicked(self, item: QListWidgetItem):
        """Handle item click and emit the canvasSelected signal."""
        canvas = item.data(Qt.UserRole)
        if canvas:
            self.canvasSelected.emit(canvas)

    def delete_canvas(self, canvas: CanvasLayer):
        """Delete a canvas from the list."""
        if canvas in self.canvases:
            canvas.layers.clear()
            logger.info(f"Deleting canvas: {canvas.layer_name}")
            canvas.setVisible(False)
            canvas.deleteLater()
            self.canvases.remove(canvas)
            self.canvasDeleted.emit(canvas)
            self.update_canvas_list()
