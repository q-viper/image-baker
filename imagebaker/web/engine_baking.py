from __future__ import annotations

import math
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QTransform,
)

from imagebaker.core.defs import (
    Annotation,
    AnnotationFormat,
    BakingResult,
    LayerState,
)
from imagebaker.utils.annotation_formats import (
    export_annotations_data,
    save_annotations_to_path,
)
from imagebaker.utils.image import draw_annotations, qpixmap_to_numpy
from imagebaker.utils.transform_mask import mask_to_polygons, mask_to_rectangles
from imagebaker.web.models import WebImageEntry, WebLayerItem


class WebEngineBakingMixin:
    """Baking, z-order occlusion masking, brush mask export, and zip/annotation generation."""

    # -------------------------------------------------------------------------
    # Baking & Exporting (Exact BakerWorker + CanvasLayer.handle_baker_results)
    # -------------------------------------------------------------------------
    @staticmethod
    def _layer_scene_transform(
        pos: QPointF,
        width: float,
        height: float,
        scale_x: float,
        scale_y: float,
        rotation: float,
        origin_offset: QPointF | None = None,
    ) -> QTransform:
        if origin_offset is None:
            origin_offset = QPointF(0.0, 0.0)
        cx = (width * scale_x) / 2.0
        cy = (height * scale_y) / 2.0
        tf = QTransform()
        tf.translate(pos.x() - origin_offset.x() + cx, pos.y() - origin_offset.y() + cy)
        tf.rotate(rotation)
        tf.translate(-cx, -cy)
        tf.scale(scale_x, scale_y)
        return tf

    def bake_and_export(self, mode: str, annotation_format: str = "default") -> dict[str, Any]:
        """
        Modes:
        - "current_local": Export Current State locally to assets/exports
        - "states_local" / "all_local": Export all saved states locally to assets/exports
        - "predict_state": Bake current state and add to Layerify tab
        - "annotate_states": Bake all saved states and add to Layerify tab
        """
        with self.lock:
            canvas = self.current_canvas
            if canvas is None or not canvas.layers:
                return {
                    "ok": False,
                    "message": "No layers are available to export. Please add layers before exporting.",
                }

            fmt_enum = AnnotationFormat.from_value(annotation_format or "default")
            fmt_norm = fmt_enum.value
            class_names = [lbl.name for lbl in self.layer_config.predefined_labels]

            is_current_only = mode in {"current_local", "predict_state"}
            export_to_annotation_tab = mode in {"predict_state", "annotate_states"}

            timeline_total_steps = max(1, len(canvas.states)) if canvas.states else 1
            if is_current_only or not canvas.states:
                if canvas.states:
                    step_key = (
                        int(canvas.current_step)
                        if int(canvas.current_step) in canvas.states
                        else canvas.step_key_for_index(canvas._current_step_index)
                    )
                    if step_key is None:
                        step_key = min(canvas.states.keys())
                else:
                    step_key = 0
                export_states = {
                    int(step_key): canvas.build_states_for_step(
                        step=int(step_key), total_steps=timeline_total_steps
                    )
                }
            else:
                export_states = {}
                for raw_step_key, raw_step_states in sorted(canvas.states.items()):
                    step_int = int(raw_step_key)
                    resolved_list: list[LayerState] = []
                    seen_lids: set[int] = set()
                    for st in raw_step_states:
                        lyr = canvas.get_layer(st.layer_id, st.layer_name)
                        if lyr is not None and lyr.layer_id not in seen_lids:
                            st_copy = st.copy()
                            st_copy.layer_id = lyr.layer_id
                            resolved_list.append(st_copy)
                            seen_lids.add(lyr.layer_id)
                    for order_idx, lyr in enumerate(canvas.layers):
                        if lyr.layer_id not in seen_lids:
                            fallback_st = lyr.layer_state.copy()
                            fallback_st.order = order_idx
                            fallback_st.selected = False
                            fallback_st = canvas.apply_plugins_to_state(
                                lyr, fallback_st, step_int, timeline_total_steps
                            )
                            resolved_list.append(fallback_st)
                            seen_lids.add(lyr.layer_id)
                    export_states[step_int] = resolved_list

            self.canvas_config.export_folder.mkdir(parents=True, exist_ok=True)
            base_filename = self.canvas_config.filename_format.format(
                project_name=self.canvas_config.project_name,
                timestamp=datetime.now().strftime("%Y%m%d_%H%M%S"),
            )
            base_filepath = self.canvas_config.export_folder / f"{base_filename}.png"

            # Snapshot current layer states before baking
            state_snapshots = {lyr.layer_id: lyr.layer_state.copy() for lyr in canvas.layers}
            image_snapshots = {lyr.layer_id: lyr.image.copy() for lyr in canvas.layers}

            results: list[BakingResult] = []
            try:
                for step_key, step_states in sorted(export_states.items()):
                    timeline_step = int(step_key)
                    top_left = QPointF(sys.maxsize, sys.maxsize)
                    bottom_right = QPointF(-sys.maxsize, -sys.maxsize)
                    rendered_images: dict[int, QImage] = {}

                    for st in step_states:
                        layer = canvas.get_layer(st.layer_id, st.layer_name)
                        if layer and st.visible and not layer.image.isNull():
                            st.layer_id = layer.layer_id
                            update_edge = (
                                layer.edge_width != st.edge_width
                                or layer.edge_opacity != st.edge_opacity
                            )
                            layer.layer_state = st
                            if update_edge:
                                layer._apply_edge_opacity()

                            pix = canvas.get_layer_render_pixmap(
                                layer, timeline_step, timeline_total_steps
                            )
                            qimg = pix.toImage().convertToFormat(QImage.Format_RGBA8888)
                            rendered_images[layer.layer_id] = qimg

                            tf = self._layer_scene_transform(
                                layer.position,
                                qimg.width(),
                                qimg.height(),
                                layer.scale_x,
                                layer.scale_y,
                                layer.rotation,
                            )
                            t_rect = tf.mapRect(QRectF(QPointF(0, 0), qimg.size()))

                            top_left.setX(min(top_left.x(), t_rect.left()))
                            top_left.setY(min(top_left.y(), t_rect.top()))
                            bottom_right.setX(max(bottom_right.x(), t_rect.right()))
                            bottom_right.setY(max(bottom_right.y(), t_rect.bottom()))

                    width = int(math.ceil(bottom_right.x() - top_left.x()))
                    height = int(math.ceil(bottom_right.y() - top_left.y()))
                    if width <= 0 or height <= 0:
                        continue

                    out_image = QImage(width, height, QImage.Format_ARGB32)
                    out_image.fill(Qt.transparent)
                    masks = []
                    mask_names = []
                    new_annotations = []

                    painter = QPainter(out_image)
                    painter.setRenderHints(
                        QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                    )
                    layer_entries: list[dict[str, Any]] = []
                    try:
                        for st in step_states:
                            layer = canvas.get_layer(st.layer_id, st.layer_name)
                            if not layer:
                                continue
                            render_image = rendered_images.get(layer.layer_id)
                            if not st.visible or render_image is None:
                                continue

                            layer_tf = self._layer_scene_transform(
                                layer.position,
                                render_image.width(),
                                render_image.height(),
                                layer.scale_x,
                                layer.scale_y,
                                layer.rotation,
                                top_left,
                            )

                            painter.save()
                            painter.setTransform(layer_tf, combine=False)
                            painter.setOpacity(layer.opacity / 255.0)
                            painter.drawImage(QPoint(0, 0), render_image)
                            painter.restore()

                            if st.drawing_states:
                                painter.save()
                                painter.setTransform(layer_tf, combine=False)
                                for ds in st.drawing_states:
                                    painter.setPen(
                                        QPen(
                                            ds.color,
                                            ds.size,
                                            Qt.SolidLine,
                                            Qt.RoundCap,
                                            Qt.RoundJoin,
                                        )
                                    )
                                    painter.drawPoint(ds.position)
                                painter.restore()

                            # Layer mask
                            layer_mask = QImage(width, height, QImage.Format_ARGB32)
                            layer_mask.fill(Qt.transparent)
                            mp = QPainter(layer_mask)
                            mp.setRenderHints(
                                QPainter.Antialiasing | QPainter.SmoothPixmapTransform
                            )
                            mp.setTransform(layer_tf, combine=False)
                            mp.drawImage(QPoint(0, 0), render_image)
                            if st.drawing_states:
                                for ds in st.drawing_states:
                                    mp.setPen(
                                        QPen(
                                            Qt.black,
                                            ds.size,
                                            Qt.SolidLine,
                                            Qt.RoundCap,
                                            Qt.RoundJoin,
                                        )
                                    )
                                    mp.drawPoint(ds.position)
                            mp.end()

                            mask_arr = qpixmap_to_numpy(layer_mask)
                            raw_alpha = mask_arr[:, :, 3].copy()
                            alpha_ch = np.where(raw_alpha > 0, 255, 0).astype(np.uint8)
                            occluder_mask = (
                                raw_alpha.astype(np.float32) * (layer.opacity / 255.0)
                            ) >= 128.0

                            child_entries: list[dict[str, Any]] = []
                            brush_mask = None
                            base_ann = None
                            if layer.allow_annotation_export:
                                base_ann = (
                                    layer.annotations[0]
                                    if layer.annotations
                                    else (
                                        layer.layers[0].annotations[0]
                                        if (layer.layers and layer.layers[0].annotations)
                                        else None
                                    )
                                )
                                if layer.layers and len(layer.layers) >= 2:
                                    for child in layer.layers:
                                        if not child.annotations:
                                            continue
                                        child_mask_img = QImage(
                                            width, height, QImage.Format_ARGB32
                                        )
                                        child_mask_img.fill(Qt.transparent)
                                        cmp = QPainter(child_mask_img)
                                        cmp.setRenderHints(
                                            QPainter.Antialiasing
                                            | QPainter.SmoothPixmapTransform
                                        )
                                        cmp.setTransform(layer_tf, combine=False)
                                        cmp.translate(
                                            child.position.x(), child.position.y()
                                        )
                                        cmp.rotate(child.rotation)
                                        cmp.scale(child.scale_x, child.scale_y)
                                        cmp.drawPixmap(0, 0, child.image)
                                        cmp.end()

                                        c_mask_arr = qpixmap_to_numpy(child_mask_img)
                                        c_raw_alpha = c_mask_arr[:, :, 3].copy()
                                        c_alpha = np.where(
                                            c_raw_alpha > 0, 255, 0
                                        ).astype(np.uint8)
                                        c_occ = (
                                            c_raw_alpha.astype(np.float32)
                                            * (layer.opacity / 255.0)
                                            * (child.opacity / 255.0)
                                        ) >= 128.0
                                        child_entries.append(
                                            {
                                                "child": child,
                                                "alpha_ch": c_alpha,
                                                "occluder_mask": c_occ,
                                            }
                                        )

                                brush_mask = self._render_brush_mask(
                                    width, height, layer, st, top_left
                                )

                            layer_entries.append(
                                {
                                    "layer": layer,
                                    "alpha_ch": alpha_ch,
                                    "occluder_mask": occluder_mask,
                                    "base_ann": base_ann,
                                    "children": child_entries,
                                    "brush_mask": brush_mask,
                                }
                            )
                    finally:
                        painter.end()

                    # Compute true visible (occluded) masks top-to-bottom across z-order
                    upper_occluder = np.zeros((height, width), dtype=bool)
                    resolved_entries: list[dict[str, Any]] = []
                    for entry in reversed(layer_entries):
                        vis_alpha = np.where(
                            upper_occluder, 0, entry["alpha_ch"]
                        ).astype(np.uint8)
                        vis_brush = (
                            np.where(upper_occluder, 0, entry["brush_mask"]).astype(
                                np.uint8
                            )
                            if entry["brush_mask"] is not None
                            else None
                        )
                        vis_children: list[tuple[Any, np.ndarray]] = []
                        if entry["children"]:
                            group_occ = upper_occluder.copy()
                            rev_children: list[tuple[Any, np.ndarray]] = []
                            for ch in reversed(entry["children"]):
                                c_vis = np.where(
                                    group_occ, 0, ch["alpha_ch"]
                                ).astype(np.uint8)
                                rev_children.append((ch["child"], c_vis))
                                group_occ |= ch["occluder_mask"]
                            vis_children = list(reversed(rev_children))

                        resolved_entries.append(
                            {
                                "layer": entry["layer"],
                                "base_ann": entry["base_ann"],
                                "vis_alpha": vis_alpha,
                                "vis_brush": vis_brush,
                                "vis_children": vis_children,
                            }
                        )
                        upper_occluder |= entry["occluder_mask"]

                    for item in reversed(resolved_entries):
                        layer = item["layer"]
                        alpha_ch = item["vis_alpha"]
                        masks.append(alpha_ch)
                        mask_names.append(layer.layer_name)

                        if layer.allow_annotation_export:
                            if item["vis_children"]:
                                for child, c_alpha in item["vis_children"]:
                                    masks.append(c_alpha)
                                    mask_names.append(child.layer_name)
                                    if np.any(c_alpha):
                                        for child_ann in child.annotations:
                                            gen_ann = (
                                                self._generate_annotation_from_mask(
                                                    child_ann, c_alpha
                                                )
                                            )
                                            gen_ann.caption = (
                                                child.caption or layer.caption
                                            )
                                            new_annotations.append(gen_ann)
                            elif np.any(alpha_ch):
                                for base_ann_item in layer.annotations:
                                    gen_ann = self._generate_annotation_from_mask(
                                        base_ann_item, alpha_ch
                                    )
                                    gen_ann.caption = layer.caption
                                    new_annotations.append(gen_ann)

                            vis_brush = item["vis_brush"]
                            if vis_brush is not None and np.any(vis_brush):
                                brush_ann = self._generate_brush_annotation(
                                    item["base_ann"],
                                    vis_brush,
                                    layer.layer_name,
                                    layer.caption,
                                )
                                if brush_ann is not None:
                                    new_annotations.append(brush_ann)

                    for ann_idx, gen_ann in enumerate(new_annotations, start=1):
                        gen_ann.annotation_id = ann_idx

                    step_filename = base_filepath.parent / f"{base_filepath.stem}_{step_key}.png"
                    results.append(
                        BakingResult(
                            filename=step_filename,
                            step=step_key,
                            image=out_image,
                            masks=masks,
                            mask_names=mask_names,
                            annotations=new_annotations,
                        )
                    )
            finally:
                for layer in canvas.layers:
                    if layer.layer_id in state_snapshots:
                        layer.layer_state = state_snapshots[layer.layer_id]
                    if layer.layer_id in image_snapshots:
                        layer._image = image_snapshots[layer.layer_id]

            if not results:
                return {"ok": False, "message": "Baking produced no visible output."}

            exported_files = []
            annotation_exports = []
            for res in results:
                if not export_to_annotation_tab:
                    res.image.save(str(res.filename))
                    exported_files.append(str(res.filename))

                    if self.canvas_config.is_debug:
                        if self.canvas_config.write_masks:
                            for i, m in enumerate(res.masks):
                                m_name = res.mask_names[i]
                                write_to = res.filename.parent / f"{m_name}_{res.filename.name}"
                                cv2.imwrite(str(write_to), m)
                        if self.canvas_config.write_annotations:
                            img_np = qpixmap_to_numpy(res.image.copy())
                            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGRA)
                            drawn = draw_annotations(img_bgr, res.annotations)
                            write_to = res.filename.parent / f"annotated_{res.filename.name}"
                            cv2.imwrite(str(write_to), drawn)

                    if fmt_norm == "coco":
                        ann_out = res.filename.parent / f"{res.filename.stem}_coco.json"
                    elif fmt_norm == "yolo":
                        ann_out = res.filename.parent / f"{res.filename.stem}.txt"
                    else:
                        ann_out = res.filename.parent / f"{res.filename.stem}.json"

                    if fmt_norm == "default":
                        Annotation.save_as_json(res.annotations, str(ann_out))
                        content = ann_out.read_text(encoding="utf-8")
                        classes_txt = None
                    else:
                        exported_data = export_annotations_data(
                            annotations=res.annotations,
                            fmt=fmt_norm,
                            image_name=res.filename.name,
                            image_width=res.image.width(),
                            image_height=res.image.height(),
                            class_names=class_names,
                        )
                        save_annotations_to_path(
                            annotations=res.annotations,
                            output_path=ann_out,
                            fmt=fmt_norm,
                            image_name=res.filename.name,
                            image_width=res.image.width(),
                            image_height=res.image.height(),
                            class_names=class_names,
                        )
                        content = exported_data["content"]
                        classes_txt = (
                            exported_data["data"].get("classes_txt")
                            if fmt_norm == "yolo"
                            else None
                        )
                    annotation_exports.append(
                        {
                            "filename": ann_out.name,
                            "path": str(ann_out),
                            "format": fmt_norm,
                            "content": content,
                            "classes_txt": classes_txt,
                        }
                    )
                else:
                    # Add to Layerify Tab (bake_dir + cache_dir)
                    self.save_current_image_annotations(delete_if_empty=False)
                    filepath = (self.layer_config.bake_dir / res.filename.name).resolve()
                    res.image.save(str(filepath))
                    for idx, a in enumerate(res.annotations):
                        a.annotation_id = idx
                        a.file_path = filepath
                        self.ensure_label_available(a.label, a.color)
                    Annotation.save_as_json(
                        res.annotations, str(self._cache_path_for_file(filepath))
                    )
                    w, h = res.image.width(), res.image.height()
                    entry = WebImageEntry(
                        is_baked_result=True, file_path=filepath, width=w, height=h
                    )
                    self.image_entries.append(entry)
                    self._select_image_by_index(len(self.image_entries) - 1, save_previous=False)
                    self.active_tab = "Layerify"
                    exported_files.append(str(filepath))

            download_url = None
            download_filename = None
            if export_to_annotation_tab:
                self.last_message = f"Baked result added ({len(results)} state(s))"
            else:
                zip_filename = f"{base_filename}_{fmt_norm}.zip"
                zip_path = self.canvas_config.export_folder / zip_filename
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for img_path_str in exported_files:
                        img_p = Path(img_path_str)
                        if img_p.is_file():
                            zf.write(img_p, arcname=img_p.name)
                    for ann_exp in annotation_exports:
                        ann_p = Path(ann_exp["path"])
                        if ann_p.is_file():
                            zf.write(ann_p, arcname=ann_p.name)
                    if fmt_norm == "yolo" and annotation_exports:
                        classes_content = annotation_exports[-1].get("classes_txt") or ""
                        zf.writestr("classes.txt", classes_content)
                download_filename = zip_filename
                download_url = f"/api/baker/exported-file?name={zip_filename}"
                self.last_message = (
                    f"Exported {len(results)} baked state(s) ({fmt_norm.upper()}) "
                    f"to {self.canvas_config.export_folder}"
                )

            return {
                "ok": True,
                "message": self.last_message,
                "count": len(results),
                "format": fmt_norm,
                "exported_files": exported_files,
                "annotation_exports": annotation_exports,
                "download_url": download_url,
                "download_filename": download_filename,
                "switched_to_layerify": export_to_annotation_tab,
            }

    @staticmethod
    def _generate_annotation_from_mask(ann: Annotation, alpha_channel: np.ndarray) -> Annotation:
        new_ann = Annotation(
            label=ann.label,
            color=ann.color,
            annotation_id=ann.annotation_id,
            is_complete=True,
            visible=True,
            caption=ann.caption,
            is_model_generated=ann.is_model_generated,
        )
        raw_polygons = mask_to_polygons(
            alpha_channel, min_polygon_area=2, merge_polygons=False
        )
        is_brush_or_split = (
            (ann.mask is not None and np.any(ann.mask) and (ann.polygon is None or len(ann.polygon) == 0))
            or len(raw_polygons) > 1
        )
        if is_brush_or_split:
            # Brush mask or occluded instance split into multiple parts: keep unified RLE mask
            new_ann.mask = (alpha_channel > 0).astype(np.uint8)
        elif ann.polygon and len(ann.polygon) >= 3:
            polygons = mask_to_polygons(alpha_channel, merge_polygons=True)
            if polygons:
                new_ann.polygon = QPolygonF([QPointF(p[0], p[1]) for p in polygons[0]])
            else:
                xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
                if xywhs:
                    new_ann.rectangle = QRectF(*xywhs[0])
        elif ann.rectangle:
            xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
            if xywhs:
                new_ann.rectangle = QRectF(*xywhs[0])
        else:
            polygons = mask_to_polygons(alpha_channel, merge_polygons=True)
            if polygons:
                new_ann.polygon = QPolygonF([QPointF(p[0], p[1]) for p in polygons[0]])
            else:
                xywhs = mask_to_rectangles(alpha_channel, merge_rectangles=True)
                if xywhs:
                    new_ann.rectangle = QRectF(*xywhs[0])
        return new_ann

    @staticmethod
    def _render_brush_mask(
        width: int, height: int, layer: WebLayerItem, state: LayerState, top_left: QPointF
    ) -> np.ndarray | None:
        if not state.drawing_states:
            return None
        brush_mask = QImage(width, height, QImage.Format_ARGB32)
        brush_mask.fill(Qt.transparent)
        bp = QPainter(brush_mask)
        bp.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        bp.translate(layer.position - top_left)
        bp.rotate(layer.rotation)
        bp.scale(layer.scale_x, layer.scale_y)
        for ds in state.drawing_states:
            bp.setPen(QPen(Qt.white, ds.size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            bp.drawPoint(ds.position)
        bp.end()

        arr = qpixmap_to_numpy(brush_mask)
        alpha = arr[:, :, 3].copy()
        alpha[alpha > 0] = 255
        if not np.any(alpha):
            return None
        return alpha

    @staticmethod
    def _generate_brush_annotation(
        base_ann: Annotation | None,
        brush_mask: np.ndarray | None,
        fallback_name: str,
        caption: str = "",
    ) -> Annotation | None:
        if brush_mask is None:
            return None
        label = f"{base_ann.label}_brush" if base_ann is not None else "Brush"
        color = base_ann.color if base_ann is not None else QColor(255, 255, 255)
        ann_id = (
            base_ann.annotation_id * 1000 + 1
            if base_ann is not None
            else abs(hash((fallback_name, "brush"))) % 1_000_000
        )
        brush_ann = Annotation(
            annotation_id=ann_id,
            label=label,
            color=color,
            mask=(brush_mask > 0).astype(np.uint8),
            is_complete=True,
            visible=True,
            caption=caption or (base_ann.caption if base_ann is not None else ""),
        )
        return brush_ann
