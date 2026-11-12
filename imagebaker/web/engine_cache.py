from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPixmap

from imagebaker import logger
from imagebaker.core.defs import Annotation, DrawingState, Label, LayerState
from imagebaker.utils.annotation_formats import (
    dict_to_annotation,
    normalize_annotation_dict,
)
from imagebaker.web.annotation_ops import (
    deserialize_annotation as _deserialize_ann,
)
from imagebaker.web.annotation_ops import (
    serialize_annotation as _serialize_ann,
)
from imagebaker.web.models import WebCanvasItem, WebLayerItem


class WebEngineCacheMixin:
    """Cache persistence, label registry helpers, and per-image annotation storage."""

    @property
    def baker_cache_file(self) -> Path:
        return self.canvas_config.cache_dir / "baker_cache.json"

    @property
    def baker_layers_dir(self) -> Path:
        d = self.canvas_config.cache_dir / "baker_layers"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_baker_cache(self) -> Path:
        """Persist Baker canvases, layers, and saved timeline states to .imagebaker/cache."""
        with self.lock:
            cache_file = self.baker_cache_file
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            _ = self.baker_layers_dir

            canvases_payload = []
            for cv in self.canvases:
                layers_payload = []
                for order, layer in enumerate(cv.layers):
                    lid = str(layer.layer_id)
                    img_rel = f"baker_layers/layer_{lid}.png"
                    img_abs = self.canvas_config.cache_dir / img_rel
                    source_img = layer._original_image if not layer._original_image.isNull() else layer.image
                    if not source_img.isNull():
                        source_img.save(str(img_abs), "PNG")

                    ann_dict = (
                        normalize_annotation_dict(layer.annotations[0], order + 1)
                        if layer.annotations
                        else None
                    )
                    lbl = ann_dict["label"] if ann_dict else "Undefined"
                    col = ann_dict["color"] if ann_dict else [255, 255, 255]
                    drawings_payload = [
                        {
                            "x": float(d.position.x()),
                            "y": float(d.position.y()),
                            "color": [d.color.red(), d.color.green(), d.color.blue()],
                            "size": int(d.size),
                        }
                        for d in layer.drawing_states
                    ]
                    plugin_names = [
                        getattr(p, "plugin_name", getattr(p, "name", type(p).__name__))
                        for p in getattr(layer, "plugins", [])
                        if getattr(p, "enabled", True)
                    ]
                    layers_payload.append(
                        {
                            "layer_id": int(layer.layer_id),
                            "name": layer.layer_name,
                            "label": lbl,
                            "color": col,
                            "image_file": img_rel,
                            "source_image": str(layer.file_path or ""),
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
                            "layer_id": int(st.layer_id),
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
                                for d in st.drawing_states
                            ],
                        }
                        for st in step_states
                    ]

                canvases_payload.append(
                    {
                        "canvas_id": int(cv.canvas_id),
                        "name": cv.layer_name,
                        "width": int(cv.viewport_width),
                        "height": int(cv.viewport_height),
                        "current_step": int(cv.current_step),
                        "layers": layers_payload,
                        "states": states_payload,
                    }
                )

            payload = {
                "version": 1,
                "active_canvas_id": int(self.current_canvas.canvas_id) if self.current_canvas else 1,
                "canvases": canvases_payload,
            }
            try:
                cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning(f"Failed to write Baker cache {cache_file}: {exc}")
            return cache_file

    def load_baker_cache(self) -> bool:
        """Restore Baker canvases, layers, and saved timeline states from .imagebaker/cache."""
        with self.lock:
            cache_file = self.baker_cache_file
            if not cache_file.exists():
                return False
            try:
                payload = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning(f"Failed to read Baker cache {cache_file}: {exc}")
                return False

            canvases_data = payload.get("canvases", [])
            if not canvases_data:
                return False

            restored_canvases: list[WebCanvasItem] = []
            max_layer_id = 0
            for cdata in canvases_data:
                cv = WebCanvasItem(str(cdata.get("name", "Canvas 1")), self.canvas_config)
                try:
                    cv.canvas_id = int(cdata.get("canvas_id", cv.canvas_id))
                    WebCanvasItem._next_id = max(WebCanvasItem._next_id, cv.canvas_id + 1)
                except (ValueError, TypeError):
                    pass
                cv.viewport_width = int(cdata.get("width", 960))
                cv.viewport_height = int(cdata.get("height", 640))
                cv.current_step = int(cdata.get("current_step", 0))

                for ldata in cdata.get("layers", []):
                    img_rel = ldata.get("image_file", "")
                    img_abs = self.canvas_config.cache_dir / img_rel
                    if not img_abs.exists():
                        continue
                    pix = QPixmap(str(img_abs))
                    if pix.isNull():
                        continue

                    item = WebLayerItem(self.canvas_config)
                    try:
                        lid = int(ldata.get("layer_id", item.id))
                    except (ValueError, TypeError):
                        lid = item.id
                    item.id = lid
                    item.layer_id = lid
                    max_layer_id = max(max_layer_id, lid)
                    item.layer_name = str(ldata.get("name", f"Layer {lid}"))
                    item.set_image(pix)
                    src_img = ldata.get("source_image", "")
                    if src_img:
                        item.file_path = Path(src_img)
                    item.position = QPointF(float(ldata.get("x", 0.0)), float(ldata.get("y", 0.0)))
                    item.scale_x = float(ldata.get("scale_x", 1.0))
                    item.scale_y = float(ldata.get("scale_y", 1.0))
                    item.rotation = float(ldata.get("rotation", 0.0))
                    item.opacity = float(ldata.get("opacity", 255.0))
                    item.edge_opacity = int(ldata.get("edge_opacity", 255))
                    item.edge_width = int(ldata.get("edge_width", 1))
                    item.visible = bool(ldata.get("visible", True))
                    item.allow_annotation_export = bool(ldata.get("allow_export", True))
                    item.order = int(ldata.get("order", len(cv.layers)))
                    item.caption = str(ldata.get("caption", ""))
                    item.drawing_states = [
                        DrawingState(
                            position=QPointF(float(d.get("x", 0.0)), float(d.get("y", 0.0))),
                            color=QColor(*d.get("color", [255, 0, 0])),
                            size=int(d.get("size", 5)),
                        )
                        for d in ldata.get("drawings", [])
                    ]
                    ann_raw = ldata.get("annotation")
                    if isinstance(ann_raw, dict):
                        item.annotations = [dict_to_annotation(ann_raw, file_path=item.file_path)]
                    else:
                        item.annotations = [
                            Annotation(
                                annotation_id=1,
                                label=str(ldata.get("label", "Undefined")),
                                color=QColor(*ldata.get("color", [255, 255, 255])),
                            )
                        ]
                    pnames = ldata.get("plugins") or []
                    for pname in pnames:
                        if pname in self.plugin_registry:
                            try:
                                item.plugins.append(self.plugin_registry[pname]())
                            except Exception:
                                pass
                    item._apply_edge_opacity()
                    cv.layers.append(item)

                for step_str, step_states in cdata.get("states", {}).items():
                    try:
                        step_int = int(step_str)
                    except ValueError:
                        continue
                    slist = []
                    for sdata in step_states:
                        try:
                            slid = int(sdata.get("layer_id", 0))
                        except (ValueError, TypeError):
                            slid = 0
                        st = LayerState(
                            layer_id=slid,
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
                        matched_lyr = cv.get_layer(st.layer_id, st.layer_name)
                        if matched_lyr is not None:
                            st.layer_id = matched_lyr.layer_id
                        slist.append(st)
                    cv.states[step_int] = slist

                if cv.states:
                    last_step = max(cv.states.keys())
                    for st in cv.states[last_step]:
                        matched_lyr = cv.get_layer(st.layer_id, st.layer_name)
                        if matched_lyr is not None:
                            matched_lyr.previous_state = st.copy()

                restored_canvases.append(cv)

            if restored_canvases:
                WebLayerItem._next_id = max(WebLayerItem._next_id, max_layer_id + 1)
                self.canvases = restored_canvases
                active_cid = payload.get("active_canvas_id")
                self.current_canvas = next(
                    (c for c in self.canvases if str(c.canvas_id) == str(active_cid)),
                    self.canvases[0],
                )
                return True
            return False

    def _cache_path_for_file(self, file_path: Path, base_dir: Path | None = None) -> Path:
        if base_dir is None:
            base_dir = self.layer_config.cache_dir
        normalized = str(Path(file_path))
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        safe_name = Path(file_path).name
        return base_dir / f"{safe_name}.{digest}.json"

    def _label_color(self, label_name: str) -> QColor:
        color = self.layer_config.get_label_color(label_name)
        return QColor(color.red(), color.green(), color.blue())

    def ensure_label_available(self, label_name: str, color: QColor | None = None) -> bool:
        if not label_name:
            return False
        existing_names = [lbl.name for lbl in self.layer_config.predefined_labels]
        if label_name in existing_names:
            return False
        self.layer_config.predefined_labels.append(
            Label(name=label_name, color=color or QColor(255, 255, 255))
        )
        self.layer_config.save_labels_to_cache()
        return True

    def get_default_label(self) -> Label:
        self.layer_config.ensure_undefined_label()
        return self.layer_config.default_label

    def normalize_annotation_colors(
        self, annotations: list[Annotation], add_missing_labels: bool = True
    ) -> bool:
        changed = False
        for ann in annotations:
            if not ann.label:
                ann.label = self.get_default_label().name
                changed = True
            if add_missing_labels:
                self.ensure_label_available(ann.label, ann.color)
            target = self._label_color(ann.label)
            if (ann.color.red(), ann.color.green(), ann.color.blue()) != (
                target.red(),
                target.green(),
                target.blue(),
            ):
                ann.color = target
                changed = True
        return changed

    def save_current_image_annotations(self, delete_if_empty: bool = True):
        if not self.image_entries or not (0 <= self.curr_image_idx < len(self.image_entries)):
            return
        entry = self.image_entries[self.curr_image_idx]
        file_path = entry.file_path
        if not file_path or file_path == Path("Runtime"):
            return
        cache_path = self._cache_path_for_file(file_path)
        for idx, ann in enumerate(self.current_annotations):
            ann.annotation_id = idx
            ann.file_path = Path(file_path)

        # Save copy with selected=False to disk cache just like desktop LayerifyTab
        disk_copies = []
        for idx, ann in enumerate(self.current_annotations):
            c = ann.copy()
            c.annotation_id = idx
            c.selected = False
            c.file_path = Path(file_path)
            disk_copies.append(c)

        if disk_copies:
            Annotation.save_as_json(disk_copies, str(cache_path))
        elif delete_if_empty and cache_path.exists():
            try:
                cache_path.unlink()
            except OSError:
                pass

    def load_image_annotations(self, file_path: Path) -> list[Annotation]:
        if not file_path or file_path == Path("Runtime"):
            return []
        cache_path = self._cache_path_for_file(file_path)
        if cache_path.exists():
            annotations = Annotation.load_from_json(str(cache_path))
            for ann in annotations:
                self.ensure_label_available(ann.label, ann.color)
            if self.normalize_annotation_colors(annotations):
                Annotation.save_as_json(annotations, str(cache_path))
            return annotations
        return []

    @staticmethod
    def serialize_annotation(ann: Annotation) -> dict[str, Any]:
        return _serialize_ann(ann)

    def deserialize_annotation(
        self, d: dict[str, Any], index: int, default_file_path: Path
    ) -> Annotation:
        return _deserialize_ann(
            d=d,
            index=index,
            default_file_path=default_file_path,
            fallback_label=self.current_label or self.get_default_label().name,
            get_label_color_fn=self._label_color,
            ensure_label_fn=self.ensure_label_available,
        )
