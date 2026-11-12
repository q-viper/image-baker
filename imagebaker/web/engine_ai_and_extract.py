from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QPolygonF

from imagebaker import logger
from imagebaker.core.defs import Annotation, PredictionResult
from imagebaker.utils.image import qpixmap_to_numpy
from imagebaker.utils.transform_mask import mask_to_polygons
from imagebaker.web.models import WebLayerItem


class WebEngineAiExtractMixin:
    """AI prediction execution and annotation-to-Baker-layer extraction helpers."""

    # -------------------------------------------------------------------------
    # Model Prediction & Layerify
    # -------------------------------------------------------------------------
    def run_prediction(self, text_prompt: str | None = None) -> tuple[bool, str]:
        with self.lock:
            if text_prompt is not None:
                self.current_predict_prompt = text_prompt.strip()
            effective_prompt = self.current_predict_prompt if self.current_predict_prompt else None

            model = self.loaded_models.get(self.current_model_name)
            if model is None:
                # Check if user stored None key
                model = self.loaded_models.get(None)
            if model is None:
                self.last_message = "No model selected/or loaded to predict"
                return False, self.last_message

            if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
                return False, "No image loaded to predict."

            entry = self.image_entries[self.curr_image_idx]
            pixmap = QPixmap(str(entry.file_path))
            if pixmap.isNull():
                return False, "Failed to read image for prediction."

            image_np = qpixmap_to_numpy(pixmap)
            selected_anns = [
                ann
                for ann in self.current_annotations
                if getattr(ann, "selected", False) and ann.visible
            ]
            if selected_anns:
                prompt_anns = selected_anns
            else:
                prompt_anns = [
                    ann
                    for ann in self.current_annotations
                    if not ann.is_model_generated and ann.visible
                ]

            points = []
            polygons = []
            rectangles = []
            label_hints = []
            for ann in prompt_anns:
                if ann.points:
                    points.append([[p.x(), p.y()] for p in ann.points])
                if ann.polygon:
                    polygons.append([[p.x(), p.y()] for p in ann.polygon])
                if ann.rectangle:
                    rectangles.append(
                        [
                            ann.rectangle.x(),
                            ann.rectangle.y(),
                            ann.rectangle.x() + ann.rectangle.width(),
                            ann.rectangle.y() + ann.rectangle.height(),
                        ]
                    )
                label_hints.append([0])
                ann.visible = False

            points_arg = points if points else None
            polygons_arg = polygons if polygons else None
            rectangles_arg = [rectangles] if rectangles else None
            label_hints_arg = label_hints if label_hints else None

            self._current_history().push(self.current_annotations)
            try:
                predictions: list[PredictionResult] = model.predict(
                    image_np,
                    points_arg,
                    rectangles_arg,
                    polygons_arg,
                    label_hints_arg,
                    prompt=effective_prompt,
                    text_prompt=effective_prompt,
                )
            except Exception as err:
                logger.exception(err)
                return False, f"Model error: {err}"

            model_name = getattr(model, "name", self.current_model_name)
            img_w = max(1, pixmap.width())
            img_h = max(1, pixmap.height())
            selected_label = (self.current_label or "").strip() or "Undefined"
            self.ensure_label_available(selected_label)
            pred_color = self._label_color(selected_label)
            for pred in predictions or []:
                cls_name = selected_label
                rect: QRectF | None = None
                if pred.rectangle:
                    r = pred.rectangle
                    # Handle xywh from PredictionResult and clamp into image bounds if out-of-range
                    if len(r) == 4:
                        rx, ry, rw, rh = float(r[0]), float(r[1]), float(r[2]), float(r[3])
                        rect_candidate = QRectF(rx, ry, rw, rh).normalized()
                        intersected = rect_candidate.intersected(QRectF(0, 0, img_w, img_h))
                        if intersected.width() >= 2 and intersected.height() >= 2:
                            rect = intersected
                        else:
                            # Fallback for dummy models generating coordinates larger than small images
                            rect = QRectF(
                                img_w * 0.15,
                                img_h * 0.15,
                                max(4.0, img_w * 0.7),
                                max(4.0, img_h * 0.7),
                            )
                    else:
                        rect = QRectF(0, 0, min(50, img_w), min(50, img_h))

                if pred.polygon is not None and len(pred.polygon) >= 3:
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            polygon=QPolygonF(
                                [QPointF(float(p[0]), float(p[1])) for p in pred.polygon]
                            ),
                            rectangle=rect,
                            mask=pred.mask,
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )
                elif pred.mask is not None:
                    mask_arr = np.asarray(pred.mask)
                    poly_q: QPolygonF | None = None
                    bin_mask: np.ndarray | None = None
                    if (
                        mask_arr.ndim == 2
                        and mask_arr.shape[1] == 2
                        and 3 <= mask_arr.shape[0] <= 256
                    ):
                        # Vertex list in pred.mask (e.g. get_dummy_prediction_result)
                        pts = []
                        for p in mask_arr:
                            px = min(float(img_w), max(0.0, float(p[0])))
                            py = min(float(img_h), max(0.0, float(p[1])))
                            pts.append(QPointF(px, py))
                        poly_q = QPolygonF(pts)
                    elif mask_arr.ndim == 2 and mask_arr.shape[0] > 2 and mask_arr.shape[1] > 2:
                        # 2D binary mask
                        bin_mask = (mask_arr > 0).astype(np.uint8)
                        polys = mask_to_polygons(bin_mask * 255, merge_polygons=True)
                        if polys and len(polys[0]) >= 3:
                            poly_q = QPolygonF(
                                [QPointF(float(p[0]), float(p[1])) for p in polys[0]]
                            )
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            polygon=poly_q,
                            rectangle=rect,
                            mask=bin_mask,
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )
                elif rect is not None:
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            rectangle=rect,
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )
                else:
                    cx, cy = entry.width // 2, entry.height // 2
                    self.current_annotations.append(
                        Annotation(
                            annotation_id=len(self.current_annotations),
                            label=cls_name,
                            color=pred_color,
                            points=[QPointF(cx, cy)],
                            is_complete=True,
                            score=pred.score,
                            annotator=model_name,
                            annotation_time=str(pred.annotation_time or ""),
                            file_path=entry.file_path,
                            is_model_generated=True,
                            model_name=model_name,
                        )
                    )

            self.normalize_annotation_colors(self.current_annotations, add_missing_labels=False)
            self.save_current_image_annotations()
            self.last_message = f"Prediction complete ({len(predictions or [])} result(s))"
            return True, self.last_message

    def layerify_annotations(
        self,
        annotation_ids: list[int] | None = None,
        layerify_all: bool = True,
    ) -> tuple[bool, str]:
        with self.lock:
            if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
                return False, "No image loaded to layerify."
            entry = self.image_entries[self.curr_image_idx]
            source_pixmap = QPixmap(str(entry.file_path))
            if source_pixmap.isNull():
                return False, "Failed to load source image for layerifying."

            if annotation_ids is not None and len(annotation_ids) > 0:
                target_ids = {int(i) for i in annotation_ids}
                targets = [
                    ann
                    for ann in self.current_annotations
                    if ann.annotation_id in target_ids and ann.visible
                ]
            elif layerify_all:
                targets = [ann for ann in self.current_annotations if ann.visible]
            else:
                selected = [ann for ann in self.current_annotations if ann.selected and ann.visible]
                targets = selected if selected else [ann for ann in self.current_annotations if ann.visible]

            if not targets:
                return False, "No visible annotations to layerify"

            if self.current_canvas is None:
                return False, "No active Baker canvas."

            self.current_canvas.push_undo_state()
            created_names = []

            for ann in targets:
                local_ann = ann.copy()
                if ann.mask is not None and np.any(ann.mask):
                    raw_mask = np.asarray(ann.mask)
                    if raw_mask.ndim == 3:
                        raw_mask = (
                            raw_mask[:, :, -1]
                            if raw_mask.shape[2] == 4
                            else raw_mask[:, :, 0]
                        )
                    img_h, img_w = source_pixmap.height(), source_pixmap.width()
                    mask_u8 = np.zeros((img_h, img_w), dtype=np.uint8)
                    mh = min(img_h, raw_mask.shape[0])
                    mw = min(img_w, raw_mask.shape[1])
                    mask_u8[:mh, :mw] = (raw_mask[:mh, :mw] > 0).astype(np.uint8) * 255
                    ys, xs = np.nonzero(mask_u8)
                    if len(xs) == 0 or len(ys) == 0:
                        continue
                    x0, x1 = max(0, int(xs.min())), min(img_w, int(xs.max()) + 1)
                    y0, y1 = max(0, int(ys.min())), min(img_h, int(ys.max()) + 1)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    raw_arr = qpixmap_to_numpy(source_pixmap)[y0:y1, x0:x1].copy()
                    src_alpha = raw_arr[:, :, 3].astype(np.uint16)
                    msk_alpha = mask_u8[y0:y1, x0:x1].astype(np.uint16)
                    raw_arr[:, :, 3] = ((src_alpha * msk_alpha) // 255).astype(np.uint8)
                    raw_arr = np.ascontiguousarray(raw_arr)
                    qimg = QImage(
                        raw_arr.data,
                        raw_arr.shape[1],
                        raw_arr.shape[0],
                        raw_arr.shape[1] * 4,
                        QImage.Format_RGBA8888,
                    )
                    cropped_pixmap = QPixmap.fromImage(qimg.copy())
                    local_ann.mask = (mask_u8[y0:y1, x0:x1] > 0).astype(np.uint8)
                    local_ann.rectangle = None
                    local_ann.polygon = None
                elif ann.polygon and len(ann.polygon) >= 3:
                    bounding_rect = ann.polygon.boundingRect().toRect().intersected(source_pixmap.rect())
                    if bounding_rect.width() <= 0 or bounding_rect.height() <= 0:
                        continue
                    cropped_raw = source_pixmap.copy(bounding_rect).toImage().convertToFormat(
                        QImage.Format_ARGB32
                    )
                    mask_img = QImage(cropped_raw.size(), QImage.Format_ARGB32)
                    mask_img.fill(Qt.transparent)
                    translated_poly = ann.polygon.translated(-bounding_rect.topLeft())

                    painter = QPainter(mask_img)
                    painter.setRenderHint(QPainter.Antialiasing, False)
                    painter.setBrush(QColor(255, 255, 255, 255))
                    painter.setPen(Qt.NoPen)
                    painter.drawPolygon(translated_poly)
                    painter.end()

                    raw_arr = qpixmap_to_numpy(cropped_raw).copy()
                    mask_arr = qpixmap_to_numpy(mask_img)
                    raw_arr[:, :, 3] = np.where(mask_arr[:, :, 3] > 0, 255, 0).astype(np.uint8)
                    raw_arr = np.ascontiguousarray(raw_arr)
                    qimg = QImage(
                        raw_arr.data,
                        raw_arr.shape[1],
                        raw_arr.shape[0],
                        raw_arr.shape[1] * 4,
                        QImage.Format_RGBA8888,
                    )
                    cropped_pixmap = QPixmap.fromImage(qimg.copy())
                    local_ann.polygon = translated_poly
                    local_ann.rectangle = None
                elif ann.rectangle:
                    rect = ann.rectangle.toRect().intersected(source_pixmap.rect())
                    if rect.width() <= 0 or rect.height() <= 0:
                        continue
                    cropped_pixmap = source_pixmap.copy(rect)
                    local_ann.rectangle = QRectF(0, 0, rect.width(), rect.height())
                else:
                    cropped_pixmap = source_pixmap.copy()

                new_layer = WebLayerItem(self.canvas_config)
                new_layer.set_image(cropped_pixmap)
                new_layer.file_path = entry.file_path
                new_layer.annotations = [local_ann]
                base_name = f"{ann.label} {ann.annotation_id} {ann.annotator}"
                new_layer.layer_name = f"{len(self.current_canvas.layers) + 1}_{base_name}"
                new_layer.caption = ann.caption
                new_layer._apply_edge_opacity()

                # Center in viewport
                vw = self.current_canvas.viewport_width
                vh = self.current_canvas.viewport_height
                cx = max(0.0, (vw - cropped_pixmap.width()) / 2.0)
                cy = max(0.0, (vh - cropped_pixmap.height()) / 2.0)
                new_layer.position = QPointF(cx, cy)
                new_layer.order = len(self.current_canvas.layers)

                self.current_canvas.layers.append(new_layer)
                created_names.append(new_layer.layer_name)

            if not created_names:
                return False, "Could not layerify selected annotation(s)."

            self.save_baker_cache()
            self.last_message = f"Layerified: {created_names[-1]}"
            return True, f"Layerified {len(created_names)} layer(s): {', '.join(created_names)}"
