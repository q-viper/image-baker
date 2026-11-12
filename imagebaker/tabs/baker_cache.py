import json
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPixmap

from imagebaker import logger
from imagebaker.core.defs import Annotation, DrawingState, LayerState
from imagebaker.layers.canvas_layer import CanvasLayer
from imagebaker.utils.annotation_formats import (
    dict_to_annotation,
    normalize_annotation_dict,
)


class BakerCacheMixin:
    """Persistent disk cache save/restore helpers for BakerTab canvases and timeline states."""

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
