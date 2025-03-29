from imagebaker.core.configs import LayerConfig, CursorDef, CanvasConfig
from imagebaker.core.defs import Annotation, MouseMode
from imagebaker.layers import BaseLayer
from imagebaker.layers.canvas_layer import CanvasLayer
from imagebaker import logger
from imagebaker.workers import LayerifyWorker

from PySide6.QtCore import (
    QPointF,
    QPoint,
    Qt,
    Signal,
    QRectF,
    QLineF,
    QThread,
)
from PySide6.QtGui import (
    QColor,
    QPixmap,
    QPainter,
    QBrush,
    QPen,
    QPolygonF,
    QWheelEvent,
    QMouseEvent,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QSizePolicy,
    QMessageBox,
    QProgressDialog,
)
from pathlib import Path


class AnnotableLayer(BaseLayer):
    annotationAdded = Signal(Annotation)
    annotationRemoved = Signal()
    annotationUpdated = Signal(Annotation)
    annotationCleared = Signal()
    annotationMoved = Signal()
    layersChanged = Signal()

    def __init__(self, parent, config: LayerConfig, canvas_config: CanvasConfig):
        super().__init__(parent, config)
        self.canvas_config = canvas_config

        self.image = QPixmap()
        self.mouse_mode = MouseMode.POINT

        self.label_rects = []
        self.file_path: Path = Path("Runtime")
        self.layers: list[BaseLayer] = []
        self.is_annotable = True

    def init_ui(self):
        logger.info(f"Initializing Layer UI of {self.layer_name}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def clear_annotations(self):
        self.annotations.clear()
        self.selected_annotation = None
        self.current_annotation = None
        self.annotationCleared.emit()
        self.update()

    def handle_key_press(self, event: QKeyEvent):
        # Handle Ctrl key for panning
        if event.key() == Qt.Key_Control:
            if (
                self.mouse_mode != MouseMode.POLYGON
            ):  # Only activate pan mode when not drawing polygons

                self.mouse_mode = MouseMode.PAN

        # Handle Ctrl+C for copy
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_C:
            self._copy_annotation()

        # Handle Ctrl+V for paste
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_V:
            self._paste_annotation()

    def handle_key_release(self, event):
        if event.key() == Qt.Key_Control:
            if self.mouse_mode == MouseMode.PAN:
                self.mouse_mode = MouseMode.IDLE

    def apply_opacity(self):
        """Apply opacity to the QPixmap image."""
        if self.image and self.opacity < 255:
            # Create a new transparent pixmap with the same size
            transparent_pixmap = QPixmap(self.image.size())
            transparent_pixmap.fill(Qt.transparent)

            # Create a painter to draw on the new pixmap
            painter = QPainter(transparent_pixmap)
            try:
                # Set the opacity
                painter.setOpacity(self.opacity / 255.0)

                # Draw the original image onto the new pixmap
                painter.drawPixmap(0, 0, self.image)
            finally:
                # Ensure the painter is properly ended
                painter.end()

            # Replace the original image with the transparent version
            self.image = transparent_pixmap

    def paint_layer(self, painter: QPainter):
        with QPainter(self) as painter:
            painter.fillRect(
                self.rect(),
                self.config.normal_draw_config.background_color,
            )
            painter.setRenderHints(
                QPainter.Antialiasing | QPainter.SmoothPixmapTransform
            )

            if not self.image.isNull():
                painter.save()
                painter.translate(self.offset)
                painter.scale(self.scale, self.scale)
                painter.drawPixmap(0, 0, self.image)

                # Draw all annotations
                for annotation in self.annotations:
                    self.draw_annotation(painter, annotation)

                # Draw current annotation
                if self.current_annotation:
                    self.draw_annotation(painter, self.current_annotation, is_temp=True)

                painter.restore()

    def draw_annotation(self, painter, annotation: Annotation, is_temp=False):
        """
        Draw annotation on the image.
        """
        if not annotation.visible:
            return
        painter.save()
        base_color = annotation.color
        pen_color = QColor(
            base_color.red(),
            base_color.green(),
            base_color.blue(),
            self.config.normal_draw_config.pen_alpha,
        )
        brush_color = QColor(
            base_color.red(),
            base_color.green(),
            base_color.blue(),
            self.config.normal_draw_config.brush_alpha,
        )

        pen = QPen(pen_color, self.config.normal_draw_config.line_width)
        brush = QBrush(brush_color, Qt.DiagCrossPattern)

        if annotation.selected:
            painter.setPen(
                QPen(
                    self.config.selected_draw_config.color,
                    self.config.selected_draw_config.line_width,
                )
            )
            painter.setBrush(
                QBrush(
                    QColor(
                        self.config.selected_draw_config.color.red(),
                        self.config.selected_draw_config.color.green(),
                        self.config.selected_draw_config.color.blue(),
                        self.config.selected_draw_config.brush_alpha,
                    )
                )
            )
            if annotation.rectangle:
                painter.drawRect(annotation.rectangle)
            elif annotation.polygon:
                painter.drawPolygon(annotation.polygon)
            elif annotation.points:
                painter.drawEllipse(
                    annotation.points[0],
                    self.config.selected_draw_config.ellipse_size,
                    self.config.selected_draw_config.ellipse_size,
                )

        if is_temp:
            pen.setStyle(Qt.DashLine)
            brush.setStyle(Qt.Dense4Pattern)

        painter.setPen(pen)
        painter.setBrush(brush)

        # Draw main shape
        if annotation.points:
            for point in annotation.points:
                painter.drawEllipse(
                    point,
                    self.config.normal_draw_config.point_size,
                    self.config.normal_draw_config.point_size,
                )
        elif annotation.rectangle:
            painter.drawRect(annotation.rectangle)
        elif annotation.polygon:
            if len(annotation.polygon) > 1:
                if annotation.is_complete:
                    painter.drawPolygon(annotation.polygon)
                else:
                    painter.drawPolyline(annotation.polygon)

        # Draw control points
        if annotation.rectangle:
            rect = annotation.rectangle
            corners = [
                rect.topLeft(),
                rect.topRight(),
                rect.bottomLeft(),
                rect.bottomRight(),
            ]
            painter.save()
            painter.setPen(
                QPen(Qt.black, self.config.normal_draw_config.control_point_size)
            )
            painter.setBrush(QBrush(Qt.white))
            for corner in corners:
                painter.drawEllipse(
                    corner,
                    self.config.normal_draw_config.point_size,
                    self.config.normal_draw_config.point_size,
                )
            painter.restore()

        if annotation.polygon and len(annotation.polygon) > 0:
            painter.save()
            painter.setPen(
                QPen(Qt.white, self.config.normal_draw_config.control_point_size)
            )
            painter.setBrush(QBrush(Qt.darkGray))
            for point in annotation.polygon:
                painter.drawEllipse(
                    point,
                    self.config.normal_draw_config.point_size,
                    self.config.normal_draw_config.point_size,
                )
            painter.restore()

        # Draw labels
        if annotation.is_complete and annotation.label:
            painter.save()
            label_pos = self.get_label_position(annotation)
            text = annotation.label

            # Convert to widget coordinates
            widget_pos = QPointF(
                label_pos.x() * self.scale + self.offset.x(),
                label_pos.y() * self.scale + self.offset.y(),
            )

            if annotation.points:
                widget_pos += QPointF(10, 10)

            # Set up font
            font = painter.font()
            font.setPixelSize(
                self.config.normal_draw_config.label_font_size
            )  # Fixed screen size
            painter.setFont(font)

            # Calculate text size
            metrics = painter.fontMetrics()
            text_width = metrics.horizontalAdvance(text)
            text_height = metrics.height()

            # Draw background
            bg_rect = QRectF(
                widget_pos.x() - text_width / 2 - 2,
                widget_pos.y() - text_height / 2 - 2,
                text_width + 4,
                text_height + 4,
            )
            painter.resetTransform()
            painter.setBrush(self.config.normal_draw_config.label_font_background_color)
            painter.setPen(Qt.NoPen)
            painter.drawRect(bg_rect)

            # Draw text
            painter.setPen(Qt.white)
            painter.drawText(bg_rect, Qt.AlignCenter, text)
            painter.restore()
            self.label_rects.append((bg_rect, annotation))

        painter.restore()

        # Draw transformation handles for selected annotations
        if annotation.selected and annotation.is_complete:
            painter.save()
            handle_color = self.config.selected_draw_config.handle_color
            painter.setPen(
                QPen(handle_color, self.config.selected_draw_config.handle_width)
            )
            painter.setBrush(QBrush(handle_color))

            if annotation.rectangle:
                rect = annotation.rectangle
                # Draw corner handles
                for corner in [
                    rect.topLeft(),
                    rect.topRight(),
                    rect.bottomLeft(),
                    rect.bottomRight(),
                ]:
                    painter.drawEllipse(
                        corner,
                        self.config.selected_draw_config.handle_point_size,
                        self.config.selected_draw_config.handle_point_size,
                    )
                # Draw edge handles
                for edge in [
                    QPointF(rect.center().x(), rect.top()),
                    QPointF(rect.center().x(), rect.bottom()),
                    QPointF(rect.left(), rect.center().y()),
                    QPointF(rect.right(), rect.center().y()),
                ]:
                    painter.drawEllipse(
                        edge,
                        self.config.selected_draw_config.handle_edge_size,
                        self.config.selected_draw_config.handle_edge_size,
                    )

            elif annotation.polygon:
                # Draw vertex handles
                for point in annotation.polygon:
                    painter.drawEllipse(
                        point,
                        self.config.selected_draw_config.handle_point_size,
                        self.config.selected_draw_config.handle_point_size,
                    )

            painter.restore()

    def get_label_position(self, annotation: Annotation):
        if annotation.points:
            return annotation.points[0]
        if annotation.rectangle:
            return annotation.rectangle.center()
        if annotation.polygon:
            return annotation.polygon.boundingRect().center()
        return QPointF()

    def handle_wheel(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            # Get mouse position before zoom
            old_pos = self.widget_to_image_pos(event.position())

            # Calculate zoom factor
            zoom_factor = (
                self.config.zoom_in_factor
                if event.angleDelta().y() > 0
                else self.config.zoom_out_factor
            )
            new_scale = max(0.1, min(self.scale * zoom_factor, 10.0))

            # Calculate position shift to keep cursor over same image point
            self.offset += old_pos * self.scale - old_pos * new_scale
            self.scale = new_scale

            # is wheel going forward or backward
            if event.angleDelta().y() > 0:
                self.mouse_mode = MouseMode.ZOOM_IN
            else:
                self.mouse_mode = MouseMode.ZOOM_OUT

            self.zoomChanged.emit(self.scale)

    def handle_mouse_release(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            if self.mouse_mode == MouseMode.RECTANGLE and self.current_annotation:
                self.finalize_annotation()
            elif self.mouse_mode == MouseMode.POLYGON and self.current_annotation:
                pass
            elif self.mouse_mode in [
                MouseMode.PAN,
                MouseMode.ZOOM_IN,
                MouseMode.ZOOM_OUT,
            ]:
                self.mouse_mode = MouseMode.IDLE

        # Clean up transformation state
        if hasattr(self, "selected_annotation"):
            self.selected_annotation = None
        if hasattr(self, "active_handle"):
            del self.active_handle
        if hasattr(self, "active_point_index"):
            del self.active_point_index
        if hasattr(self, "initial_rect"):
            del self.initial_rect
        if hasattr(self, "initial_polygon"):
            del self.initial_polygon

        self.pan_start = None
        self.drag_start = None

    def handle_mouse_move(self, event: QMouseEvent):
        # logger.info(f"Mouse move event: {event.position()} with {self.mouse_mode}")
        img_pos = self.widget_to_image_pos(event.position())
        clamped_pos = QPointF(
            max(0, min(self.image.width(), img_pos.x())),
            max(0, min(self.image.height(), img_pos.y())),
        )
        self.mouseMoved.emit(img_pos)
        self.messageSignal.emit(f"X: {img_pos.x()}, Y: {img_pos.y()}")

        # if we are not clicking
        if not event.buttons():
            annotation, handle = self.find_annotation_and_handle_at(img_pos)
            if annotation and handle and self.mouse_mode == MouseMode.IDLE:
                if "point_" in handle or handle in [
                    "top_left",
                    "top_right",
                    "bottom_left",
                    "bottom_right",
                ]:
                    self.mouse_mode = MouseMode.RESIZE
                elif "center" in handle:
                    if "top" in handle or "bottom" in handle:
                        self.mouse_mode = MouseMode.RESIZE_HEIGHT
                    else:
                        self.mouse_mode = MouseMode.RESIZE_WIDTH
                elif handle == "move":
                    self.mouse_mode = MouseMode.GRAB

            elif not handle and self.mouse_mode in [
                MouseMode.RESIZE,
                MouseMode.RESIZE_HEIGHT,
                MouseMode.RESIZE_WIDTH,
                MouseMode.GRAB,
            ]:
                self.mouse_mode = MouseMode.IDLE
                # self.mouse_mode = MouseMode.IDLE
                pass
            self.update_cursor()
        else:
            if (
                event.buttons() & Qt.LeftButton
                and self.selected_annotation
                and self.active_handle
            ):
                if self.active_handle == "move":
                    self.setCursor(CursorDef.GRABBING_CURSOR)
                    new_pos = img_pos - self.drag_offset
                    self.move_annotation(self.selected_annotation, new_pos)
                elif self.selected_annotation.rectangle:
                    rect = QRectF(self.initial_rect)

                    if "top" in self.active_handle:
                        rect.setTop(img_pos.y())
                    if "bottom" in self.active_handle:
                        rect.setBottom(img_pos.y())
                    if "left" in self.active_handle:
                        rect.setLeft(img_pos.x())
                    if "right" in self.active_handle:
                        rect.setRight(img_pos.x())

                    self.selected_annotation.rectangle = rect.normalized()
                elif self.selected_annotation.polygon and hasattr(
                    self, "active_point_index"
                ):
                    self.selected_annotation.polygon[self.active_point_index] = (
                        clamped_pos
                    )
                self.annotationMoved.emit()
                self.annotationUpdated.emit(self.selected_annotation)
                self.update()
                return
            if self.mouse_mode == MouseMode.PAN and event.buttons() & Qt.LeftButton:
                if self.pan_start:
                    delta = event.position() - self.pan_start
                    self.offset += delta
                    self.pan_start = event.position()
                    self.update()
            elif self.mouse_mode == MouseMode.RECTANGLE and self.drag_start:
                self.current_annotation.rectangle = QRectF(
                    self.drag_start, clamped_pos
                ).normalized()
                self.update()
            elif self.mouse_mode == MouseMode.POLYGON and self.current_annotation:
                if self.current_annotation.polygon:
                    temp_points = QPolygonF(self.current_annotation.polygon)
                    if temp_points:
                        temp_points[-1] = clamped_pos
                        self.current_annotation.polygon = temp_points
                        self.update()

    def move_annotation(self, annotation, new_pos: QPointF):
        delta = new_pos - self.get_annotation_position(annotation)

        if annotation.rectangle:
            annotation.rectangle.translate(delta)
        elif annotation.polygon:
            annotation.polygon.translate(delta)
        elif annotation.points:
            annotation.points = [p + delta for p in annotation.points]

    def handle_mouse_press(self, event: QMouseEvent):
        # logger.info(f"Mouse press event: {event.position()} with {self.mouse_mode}")
        img_pos = self.widget_to_image_pos(event.position())
        clamped_pos = QPointF(
            max(0, min(self.image.width(), img_pos.x())),
            max(0, min(self.image.height(), img_pos.y())),
        )

        # If right-clicked
        if event.button() == Qt.RightButton:
            # If polygon drawing, remove the last point
            if self.current_annotation and self.mouse_mode == MouseMode.POLYGON:
                if len(self.current_annotation.polygon) > 0:
                    self.current_annotation.polygon = QPolygonF(
                        [p for p in self.current_annotation.polygon][:-1]
                    )
                    self.update()

                # If the polygon is now empty, reset to idle mode
                if len(self.current_annotation.polygon) == 0:
                    self.current_annotation = None
                    self.mouse_mode = MouseMode.IDLE
                    self.update()

            # If not drawing a polygon, go to idle mode
            if not self.current_annotation:
                self.mouse_mode = MouseMode.IDLE
                for ann in self.annotations:
                    ann.selected = False
                self.update()

        # If left-clicked
        if event.button() == Qt.LeftButton:
            self.selected_annotation, self.active_handle = (
                self.find_annotation_and_handle_at(img_pos)
            )
            # Handle dragging later on
            if self.selected_annotation:
                self.drag_offset = img_pos - self.get_annotation_position(
                    self.selected_annotation
                )
                self.selected_annotation.selected = True

                # Make all other annotations unselected
                for ann in self.annotations:
                    if ann != self.selected_annotation:
                        ann.selected = False
                    self.annotationUpdated.emit(ann)

                if self.selected_annotation.rectangle:
                    self.initial_rect = QRectF(self.selected_annotation.rectangle)
                elif self.selected_annotation.polygon:
                    self.initial_polygon = QPolygonF(self.selected_annotation.polygon)
                    if "point_" in self.active_handle:
                        self.active_point = int(self.active_handle.split("_")[1])

            # If pan mode
            if self.mouse_mode == MouseMode.PAN:
                self.pan_start = event.position()
                return

            # If drawing mode
            if self.mouse_mode == MouseMode.POINT:
                self.current_annotation = Annotation(
                    label=self.current_label,
                    annotation_id=len(self.annotations),
                    points=[clamped_pos],
                )
                self.finalize_annotation()
            elif self.mouse_mode == MouseMode.RECTANGLE:
                # The incomplete annotation
                self.current_annotation = Annotation(
                    file_path=self.file_path,
                    annotation_id=len(self.annotations),
                    label="Incomplete",
                    color=self.current_color,
                    rectangle=QRectF(clamped_pos, clamped_pos),
                )
                self.drag_start = clamped_pos
            elif self.mouse_mode == MouseMode.POLYGON:
                # If not double-click
                if not self.current_annotation:
                    self.current_annotation = Annotation(
                        file_path=self.file_path,
                        annotation_id=len(self.annotations),
                        label="Incomplete",
                        color=self.current_color,
                        polygon=QPolygonF([clamped_pos]),
                    )
                else:
                    logger.info(f"Adding point to polygon: {clamped_pos}")
                    # Add point to polygon
                    self.current_annotation.polygon.append(clamped_pos)

            self.update()

    def get_annotation_position(self, annotation: Annotation):
        if annotation.rectangle:
            return annotation.rectangle.center()
        elif annotation.polygon:
            return annotation.polygon.boundingRect().center()
        elif annotation.points:
            return annotation.points[0]
        return QPointF()

    def find_annotation_and_handle_at(self, pos: QPointF, margin=10.0):
        """Find annotation and specific handle at given position"""
        for annotation in reversed(self.annotations):
            if not annotation.visible or not annotation.is_complete:
                continue

            # Check rectangle handles
            if annotation.rectangle:
                rect = annotation.rectangle
                handles = {
                    "top_left": rect.topLeft(),
                    "top_right": rect.topRight(),
                    "bottom_left": rect.bottomLeft(),
                    "bottom_right": rect.bottomRight(),
                    "top_center": QPointF(rect.center().x(), rect.top()),
                    "bottom_center": QPointF(rect.center().x(), rect.bottom()),
                    "left_center": QPointF(rect.left(), rect.center().y()),
                    "right_center": QPointF(rect.right(), rect.center().y()),
                }

                for handle_name, handle_pos in handles.items():
                    if (handle_pos - pos).manhattanLength() < margin:
                        return annotation, handle_name

                if rect.contains(pos):
                    return annotation, "move"

            # Check polygon points
            elif annotation.polygon:
                for i, point in enumerate(annotation.polygon):
                    if (point - pos).manhattanLength() < margin:
                        return annotation, f"point_{i}"

                if annotation.polygon.containsPoint(pos, Qt.OddEvenFill):
                    return annotation, "move"

        return None, None

    def handle_mouse_double_click(self, event: QMouseEvent, pos: QPoint):
        pos = event.position()
        for rect, annotation in self.label_rects:
            if rect.contains(pos):
                self.edit_annotation_label(annotation)
                break
        # if left double click
        if event.button() == Qt.LeftButton:
            # if drawing a polygon, close the polygon
            if (
                self.current_annotation
                and self.mouse_mode == MouseMode.POLYGON
                and len(self.current_annotation.polygon) >= 3
            ):
                self.current_annotation.is_complete = True
                self.finalize_annotation()
                self.annotationAdded.emit(self.current_annotation)
                self.current_annotation = None

                return

            # did we click on an annotation?
            annotation = self.find_annotation_at(self.widget_to_image_pos(pos))
            if annotation:
                # toggle selection
                annotation.selected = not annotation.selected

                # make all other annotations unselected
                for ann in self.annotations:
                    if ann != annotation:
                        ann.selected = False
            else:
                # we clicked on the background
                # make all annotations unselected
                for ann in self.annotations:
                    ann.selected = False
            # update the view
            for ann in self.annotations:
                self.annotationUpdated.emit(ann)
            self.update()

    def find_annotation_at(self, pos: QPointF):
        for ann in reversed(self.annotations):
            if ann.rectangle and ann.rectangle.contains(pos):
                return ann
            elif ann.polygon and ann.polygon.containsPoint(pos, Qt.OddEvenFill):
                return ann
            elif ann.points:
                for p in ann.points:
                    if QLineF(pos, p).length() < 5:
                        return ann
        return None

    def edit_annotation_label(self, annotation: Annotation):
        new_label, ok = QInputDialog.getText(
            self, "Edit Label", "Enter new label:", text=annotation.label
        )
        if ok and new_label:
            annotation.label = new_label
            self.annotationUpdated.emit(annotation)  # Emit signal
            self.update()

    def finalize_annotation(self):
        if self.current_label:
            # Use predefined label
            self.current_annotation.annotation_id = len(self.annotations)
            self.current_annotation.label = self.current_label
            self.current_annotation.color = self.current_color
            self.current_annotation.is_complete = True
            self.annotations.append(self.current_annotation)

            self.thumbnails[self.current_annotation.annotation_id] = self.get_thumbnail(
                self.current_annotation
            )
            self.annotationAdded.emit(self.current_annotation)
            self.current_annotation = None
            self.update()
        else:
            # Show custom label dialog
            label, ok = QInputDialog.getText(self, "Label", "Enter label name:")
            if ok:
                if self.current_annotation:
                    self.current_annotation.annotation_id = len(self.annotations)
                    self.current_annotation.label = label or "Unlabeled"
                    self.current_annotation.is_complete = True
                    self.annotations.append(self.current_annotation)
                    self.thumbnails[self.current_annotation.annotation_id] = (
                        self.get_thumbnail(self.current_annotation)
                    )
                    self.annotationAdded.emit(self.current_annotation)
                    self.current_annotation.annotation_id = len(self.annotations)
                    self.current_annotation = None
                    self.update()

    # in update, update cursor

    def _copy_annotation(self):
        self.selected_annotation = self._get_selected_annotation()
        if self.selected_annotation:
            self.copied_annotation = self.selected_annotation
            self.messageSignal.emit(
                f"Copied annotation: {self.selected_annotation.label}"
            )
            self.mouse_mode = MouseMode.IDLE
        else:
            self.messageSignal.emit("No annotation selected to copy.")

    def _paste_annotation(self):
        if self.copied_annotation:
            new_annotation = self.copied_annotation.copy()
            new_annotation.annotation_id = len(self.annotations)
            self.annotations.append(new_annotation)
            self.annotationAdded.emit(new_annotation)
            self.thumbnails[new_annotation.annotation_id] = self.get_thumbnail(
                new_annotation
            )
            self.messageSignal.emit(f"Annotation {new_annotation.label} pasted")
            self.update()
        else:
            self.messageSignal.emit("No annotation copied to paste.")

    def _get_selected_annotation(self):
        for annotation in self.annotations:
            if annotation.selected:
                return annotation

    def layerify_annotation(self, annotations: list[Annotation]):
        annotations = [ann for ann in annotations if ann.visible]

        if len(annotations) == 0:
            QMessageBox.information(
                self.parentWidget(), "Info", "No visible annotations to layerify"
            )
            return
        # Create and configure loading dialog
        self.loading_dialog = QProgressDialog(
            "Processing annotation...",
            "Cancel",  # Optional cancel button
            0,
            0,
            self.parentWidget(),
        )
        self.loading_dialog.setWindowTitle("Please Wait")
        self.loading_dialog.setWindowModality(Qt.WindowModal)
        # self.loading_dialog.setCancelButton()
        self.loading_dialog.show()

        # Force UI update
        QApplication.processEvents()

        # Setup worker thread
        self.worker_thread = QThread()
        self.worker = LayerifyWorker(self.image, annotations, self.config)
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(self.handle_layerify_result)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.handle_layerify_error)

        # Cleanup connections
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self.loading_dialog.close)

        # Start processing
        self.worker_thread.start()

    def handle_layerify_result(self, annotation: Annotation, cropped_image: QPixmap):
        # Create new canvas with results
        new_layer = CanvasLayer(parent=self.parent_obj, config=self.canvas_config)
        # get top left corner of the annotation

        new_layer.set_image(cropped_image)
        new_layer.annotations = [annotation]
        new_layer.layer_name = (
            f"{annotation.label} {annotation.annotation_id} {annotation.annotator}"
        )

        self.messageSignal.emit(f"Layerified: {new_layer.layer_name}")
        logger.info(f"Num annotations: {len(self.annotations)}")

        self.layerSignal.emit(new_layer)

    def handle_layerify_error(self, error_msg: str):
        self.loading_dialog.close()
        QMessageBox.critical(
            self.parentWidget(), "Error", f"Processing failed: {error_msg}"
        )

    @property
    def selected_annotation_index(self):
        for idx, annotation in enumerate(self.annotations):
            if annotation.selected:
                return idx
        return -1
