from imagebaker import logger


from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
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
)
from pathlib import Path


class ImageListPanel(QDockWidget):
    imageSelected = Signal(Path)

    def __init__(
        self,
        image_entries: list["ImageEntry"],
        processed_images: set[Path],
        parent=None,
    ):
        """
        :param image_entries: List of image paths to display.
        :param processed_images: Set of image paths that have already been processed.
        """
        super().__init__("Image List", parent)
        self.image_entries: list["ImageEntry"] = image_entries
        self.processed_images = processed_images
        self.current_page = 0
        self.images_per_page = 10
        self.init_ui()

    def init_ui(self):
        """Initialize the UI for the image list panel."""
        logger.info("Initializing ImageListPanel")
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Image list widget
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.handle_item_clicked)  # Connect signal
        layout.addWidget(self.list_widget)

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

        self.update_image_list(self.image_entries)

    def show_next_page(self):
        """Show the next page of images"""
        if (self.current_page + 1) * self.images_per_page < len(self.image_entries):
            self.current_page += 1
            self.update_image_list(self.image_entries)

    def show_prev_page(self):
        """Show the previous page of images"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_image_list(self.image_entries)

    def update_image_list(self, image_entries):
        """Update the image list with image paths and baked results."""
        self.list_widget.clear()

        for idx, image_entry in enumerate(image_entries):
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 5, 5, 5)

            # Generate thumbnail
            thumbnail_label = QLabel()
            if image_entry.is_baked_result:
                thumbnail_pixmap = (
                    image_entry.data.get_thumbnail()
                )  # Baked result thumbnail
                name_label_text = f"Baked Result {idx + 1}"
            else:
                thumbnail_pixmap = QPixmap(str(image_entry.data)).scaled(
                    50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                name_label_text = Path(image_entry.data).name

            thumbnail_label.setPixmap(thumbnail_pixmap)
            item_layout.addWidget(thumbnail_label)

            # Text for image
            name_label = QLabel(name_label_text)
            name_label.setStyleSheet("font-weight: bold;")
            item_layout.addWidget(name_label)

            item_layout.addStretch()

            # Add the custom widget to the list
            list_item = QListWidgetItem(self.list_widget)
            list_item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)

            # Store metadata for the image
            list_item.setData(Qt.UserRole, image_entry)
        self.pagination_label.setText(
            f"Showing {self.current_page * self.images_per_page + 1} to "
            f"{min((self.current_page + 1) * self.images_per_page, len(image_entries))} "
            f"of {len(image_entries)}"
        )
        self.update()

    def handle_item_clicked(self, item: QListWidgetItem):
        """Handle item click and emit the imageSelected signal."""
        item_data = item.data(Qt.UserRole)
        if item_data:
            self.imageSelected.emit(item_data)
