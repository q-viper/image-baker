import sys
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF, QTransform

from imagebaker import logger
from imagebaker.core.defs.defs import Annotation, BakingResult, LayerState
from imagebaker.plugins.runtime import apply_pixel_plugins
from imagebaker.utils.image import qpixmap_to_numpy
from imagebaker.utils.transform_mask import mask_to_polygons, mask_to_rectangles

if TYPE_CHECKING:
    from imagebaker.layers.base_layer import BaseLayer


class BakerWorker(QObject):
    finished = Signal(list)  # Emit a list of BakingResult objects
    error = Signal(str)

    def __init__(
        self,
        states: dict[int, list["LayerState"]],
        layers: list["BaseLayer"],
        filename: Path,
        render_cache: dict[tuple[int, int], QImage] | None = None,
        timeline_total_steps: int | None = None,
    ):
        """
        Worker to bake the images and masks for a given set of states.

        Args:
            states: Dictionary of step -> list of LayerState objects
            layers: List of Layer objects
            filename: Path to the output file
        """
        super().__init__()
        self.states = states  # Dictionary of step -> list of states
        self.layers = layers
        self.filename = filename
        self.render_cache = render_cache or {}
        self.timeline_total_steps = (
            None if timeline_total_steps is None else int(timeline_total_steps)
        )
        self._fallback_render_cache: dict[tuple[int, int], QImage] = {}

        # logger.info(f"Received States: {self.states}")

    @staticmethod
    def _normalize_rgba_image(image: QImage) -> QImage:
        if image.format() != QImage.Format_RGBA8888:
            return image.convertToFormat(QImage.Format_RGBA8888)
        return image

    def _resolve_render_image(
        self,
        layer: "BaseLayer",
        state: "LayerState",
        timeline_step: int,
        total_steps: int,
    ) -> QImage:
        key = (int(timeline_step), int(state.layer_id))
        cached = self.render_cache.get(key)
        if cached is not None:
            return self._normalize_rgba_image(cached).copy()

        fallback = self._fallback_render_cache.get(key)
        if fallback is not None:
            return fallback

        try:
            render_pixmap = apply_pixel_plugins(
                layer=layer,
                step=timeline_step,
                total_steps=total_steps,
                canvas=None,
            )
            image = self._normalize_rgba_image(render_pixmap.toImage()).copy()
        except Exception as error:
            logger.error(
                f"Failed to render pixel plugins for layer {layer.layer_name}: {error}"
            )
            image = self._normalize_rgba_image(layer.image.toImage()).copy()

        self._fallback_render_cache[key] = image
        return image

    def process(self):
        results = []
        try:
            if self.timeline_total_steps is None:
                total_steps = max(1, len(self.states))
            else:
                total_steps = max(1, int(self.timeline_total_steps))

            for step, states in sorted(self.states.items()):
                timeline_step = int(step)
                logger.info(f"Processing step {step}")

                # Calculate bounding box for all layers in this step
                top_left = QPointF(sys.maxsize, sys.maxsize)
                bottom_right = QPointF(-sys.maxsize, -sys.maxsize)

                # contains all states in currenct step
                for state in states:
                    layer = self._get_layer(state.layer_id)
                    if layer and layer.visible and not layer.image.isNull():
                        update_opacities = False
                        logger.debug(
                            f"Updating layer {layer.layer_name} with state: {state}"
                        )

                        if (
                            layer.edge_width != state.edge_width
                            or layer.edge_opacity != state.edge_opacity
                        ):
                            update_opacities = True
                        layer.layer_state = state
                        if update_opacities:
                            layer._apply_edge_opacity()

                        render_image = self._resolve_render_image(
                            layer=layer,
                            state=state,
                            timeline_step=timeline_step,
                            total_steps=total_steps,
                        )

                        transform = QTransform()
                        transform.translate(layer.position.x(), layer.position.y())
                        transform.rotate(layer.rotation)
                        transform.scale(layer.scale_x, layer.scale_y)

                        original_rect = QRectF(QPointF(0, 0), render_image.size())
                        transformed_rect = transform.mapRect(original_rect)

                        top_left.setX(min(top_left.x(), transformed_rect.left()))
                        top_left.setY(min(top_left.y(), transformed_rect.top()))
                        bottom_right.setX(
                            max(bottom_right.x(), transformed_rect.right())
                        )
                        bottom_right.setY(
                            max(bottom_right.y(), transformed_rect.bottom())
                        )

                # Create the output image for this step
                width = int(bottom_right.x() - top_left.x())
                height = int(bottom_right.y() - top_left.y())
                if width <= 0 or height <= 0:
                    continue

                image = QImage(width, height, QImage.Format_ARGB32)
                image.fill(Qt.transparent)
                masks = []
                mask_names = []
                new_annotations = []

                painter = QPainter(image)
                try:
                    painter.setRenderHints(
                        QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                    )
                    for state in states:
                        layer = self._get_layer(state.layer_id)

                        if layer and layer.visible and not layer.image.isNull():
                            render_image = self._resolve_render_image(
                                layer=layer,
                                state=state,
                                timeline_step=timeline_step,
                                total_steps=total_steps,
                            )
                            # Draw the layer image with transformations
                            painter.save()
                            try:
                                painter.translate(layer.position - top_left)
                                painter.rotate(layer.rotation)
                                painter.scale(layer.scale_x, layer.scale_y)
                                painter.setOpacity(layer.opacity / 255.0)
                                painter.drawImage(QPoint(0, 0), render_image)
                            finally:
                                painter.restore()

                            # Draw the drawing states
                            logger.debug(
                                f"Drawing states for layer {layer.layer_name}: {state.drawing_states}"
                            )
                            if state.drawing_states:
                                painter.save()
                                try:
                                    painter.translate(layer.position - top_left)
                                    painter.rotate(layer.rotation)
                                    painter.scale(layer.scale_x, layer.scale_y)
                                    for drawing_state in state.drawing_states:
                                        painter.setPen(
                                            QPen(
                                                drawing_state.color,
                                                drawing_state.size,
                                                Qt.SolidLine,
                                                Qt.RoundCap,
                                                Qt.RoundJoin,
                                            )
                                        )
                                        painter.drawPoint(
                                            drawing_state.position - top_left
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"Error drawing state for layer {layer.layer_name}: {e}"
                                    )
                                finally:
                                    painter.restore()

                            # Generate the layer mask
                            layer_mask = QImage(width, height, QImage.Format_ARGB32)
                            layer_mask.fill(Qt.transparent)
                            mask_painter = QPainter(layer_mask)
                            try:
                                mask_painter.setRenderHints(
                                    QPainter.Antialiasing
                                    | QPainter.SmoothPixmapTransform
                                )
                                mask_painter.translate(layer.position - top_left)
                                mask_painter.rotate(layer.rotation)
                                mask_painter.scale(layer.scale_x, layer.scale_y)
                                mask_painter.drawImage(QPoint(0, 0), render_image)

                                if state.drawing_states:
                                    mask_painter.save()
                                    try:
                                        for drawing_state in state.drawing_states:
                                            mask_painter.setPen(
                                                QPen(
                                                    Qt.black,
                                                    drawing_state.size,
                                                    Qt.SolidLine,
                                                    Qt.RoundCap,
                                                    Qt.RoundJoin,
                                                )
                                            )
                                            mask_painter.drawPoint(
                                                drawing_state.position
                                            )
                                    finally:
                                        mask_painter.restore()
                            finally:
                                mask_painter.end()

                            # Convert mask to 8-bit
                            mask_arr = qpixmap_to_numpy(layer_mask)
                            alpha_channel = mask_arr[:, :, 3].copy()  # Extract alpha

                            # Binarize the mask (0 or 255)
                            alpha_channel[alpha_channel > 0] = 255

                            masks.append(alpha_channel)
                            mask_names.append(layer.layer_name)

                            # Generate annotations
                            if layer.allow_annotation_export:
                                base_ann: Annotation | None = (
                                    layer.annotations[0] if layer.annotations else None
                                )
                                if base_ann is not None:
                                    new_annotation = self._generate_annotation(
                                        base_ann, alpha_channel
                                    )
                                    new_annotation.caption = layer.caption
                                    new_annotations.append(new_annotation)

                                brush_mask = self._render_brush_mask(
                                    width=width,
                                    height=height,
                                    layer=layer,
                                    state=state,
                                    top_left=top_left,
                                )
                                brush_annotation = self._generate_brush_annotation(
                                    base_ann=base_ann,
                                    brush_mask=brush_mask,
                                    fallback_name=layer.layer_name,
                                    caption=layer.caption,
                                )
                                if brush_annotation is not None:
                                    new_annotations.append(brush_annotation)
                finally:
                    painter.end()

                # Save the image
                filename = self.filename.parent / f"{self.filename.stem}_{step}.png"

                # Append the result
                results.append(
                    BakingResult(
                        filename=filename,
                        step=step,
                        image=image,
                        masks=masks,
                        mask_names=mask_names,
                        annotations=new_annotations,
                    )
                )

            # Emit all results
            self.finished.emit(results)

        except Exception as e:
            import traceback

            logger.error(f"Error in BakerWorker: {e}")
            self.error.emit(str(e))
            traceback.print_exc()

    def _get_layer(self, layer_id):
        for layer in self.layers:
            if layer.layer_id == layer_id:
                return layer
        return None

    def _generate_annotation(self, ann: Annotation, alpha_channel):
        """Generate an annotation based on the alpha channel."""
        new_annotation = Annotation(
            label=ann.label,
            color=ann.color,
            annotation_id=ann.annotation_id,
            is_complete=True,
            visible=True,
            caption=ann.caption,
            is_model_generated=ann.is_model_generated,
        )

        if ann.points:
            # Avoid exporting point clouds for baked results; use shape geometry.
            polygons = mask_to_polygons(alpha_channel, merge_polygons=True)
            if polygons:
                new_annotation.polygon = QPolygonF(
                    [QPointF(p[0], p[1]) for p in polygons[0]]
                )
            else:
                xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
                if xywhs:
                    new_annotation.rectangle = QRectF(
                        xywhs[0][0], xywhs[0][1], xywhs[0][2], xywhs[0][3]
                    )
        elif ann.rectangle:
            xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
            if len(xywhs) == 0:
                logger.info("No rectangles found")
                # return None
            else:
                logger.info(f"Found {len(xywhs)} rectangles")
                new_annotation.rectangle = QRectF(
                    xywhs[0][0], xywhs[0][1], xywhs[0][2], xywhs[0][3]
                )
        elif ann.polygon:
            polygon = mask_to_polygons(alpha_channel, merge_polygons=True)
            if polygon:
                poly = QPolygonF([QPointF(p[0], p[1]) for p in polygon[0]])
                new_annotation.polygon = poly
            else:
                xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
                if xywhs:
                    new_annotation.rectangle = QRectF(
                        xywhs[0][0], xywhs[0][1], xywhs[0][2], xywhs[0][3]
                    )
        else:
            logger.info("No annotation found")
        return new_annotation

    def _render_brush_mask(self, width, height, layer, state, top_left):
        if not state.drawing_states:
            return None

        brush_mask = QImage(width, height, QImage.Format_ARGB32)
        brush_mask.fill(Qt.transparent)
        brush_painter = QPainter(brush_mask)

        try:
            brush_painter.setRenderHints(
                QPainter.Antialiasing | QPainter.SmoothPixmapTransform
            )
            brush_painter.translate(layer.position - top_left)
            brush_painter.rotate(layer.rotation)
            brush_painter.scale(layer.scale_x, layer.scale_y)
            for drawing_state in state.drawing_states:
                brush_painter.setPen(
                    QPen(
                        Qt.white,
                        drawing_state.size,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.RoundJoin,
                    )
                )
                brush_painter.drawPoint(drawing_state.position)
        finally:
            brush_painter.end()

        mask_arr = qpixmap_to_numpy(brush_mask)
        alpha_channel = mask_arr[:, :, 3].copy()
        alpha_channel[alpha_channel > 0] = 255
        if not np.any(alpha_channel):
            return None
        return alpha_channel

    def _generate_brush_annotation(
        self,
        base_ann: Annotation | None,
        brush_mask: np.ndarray | None,
        fallback_name: str,
        caption: str = "",
    ) -> Annotation | None:
        if brush_mask is None:
            return None

        label = f"{base_ann.label}_brush" if base_ann is not None else "Brush"
        color = base_ann.color if base_ann is not None else QColor(255, 255, 255)
        annotation_id = (
            base_ann.annotation_id * 1000 + 1
            if base_ann is not None
            else abs(hash((fallback_name, "brush"))) % 1_000_000
        )

        brush_annotation = Annotation(
            annotation_id=annotation_id,
            label=label,
            color=color,
            mask=brush_mask,
            is_complete=True,
            visible=True,
            caption=caption or (base_ann.caption if base_ann is not None else ""),
        )

        polygons = mask_to_polygons(brush_mask, merge_polygons=True)
        if polygons:
            brush_annotation.polygon = QPolygonF(
                [QPointF(p[0], p[1]) for p in polygons[0]]
            )
        else:
            xywhs = mask_to_rectangles(brush_mask, merge_rectangles=True)
            if xywhs:
                x, y, w, h = xywhs[0]
                brush_annotation.rectangle = QRectF(x, y, w, h)

        return brush_annotation
