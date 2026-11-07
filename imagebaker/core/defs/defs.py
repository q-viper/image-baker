from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

import numpy as np
from pydantic import BaseModel
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPolygonF


class MouseMode(Enum):
    IDLE = 0
    POINT = 1
    POLYGON = 2
    RECTANGLE = 3
    PAN = 4
    ZOOM_IN = 5
    ZOOM_OUT = 6
    RESIZE = 7
    RESIZE_HEIGHT = 8
    RESIZE_WIDTH = 9
    GRAB = 11
    DRAW = 12  # Brush annotation mode
    ERASE = 13


class ModelType(str, Enum):
    DETECTION = "detection"
    SEGMENTATION = "segmentation"
    CLASSIFICATION = "classification"
    PROMPT = "prompt"


class AnnotationFormat(str, Enum):
    """Supported annotation file/export formats."""

    DEFAULT = "default"
    COCO = "coco"
    YOLO = "yolo"

    @classmethod
    def from_value(cls, val: object) -> "AnnotationFormat":
        """Convert a string or enum instance to AnnotationFormat safely."""
        if isinstance(val, cls):
            return val
        if not val:
            return cls.DEFAULT
        v = str(val).strip().lower()
        for item in cls:
            if item.value == v or item.name.lower() == v:
                return item
        valid_opts = [f.value for f in cls]
        raise ValueError(
            f"Unsupported annotation format '{val}'. Choose from {valid_opts}."
        )


@dataclass
class DrawingState:
    position: QPointF = field(default_factory=lambda: QPointF(0, 0))
    color: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    size: int = 5


class PredictionResult(BaseModel):
    class_name: str = None
    class_id: int = None
    score: float = None
    rectangle: list[int] | None = None
    mask: np.ndarray | None = None
    keypoints: list[list[int, int]] | None = None
    polygon: np.ndarray | None = None
    prompt: str | None = None
    annotated_image: np.ndarray | None = None
    annotation_time: str | None = None

    class Config:
        arbitrary_types_allowed = True


@dataclass
class LayerState:
    layer_id: str = ""
    state_step: int = 0
    layer_name: str = "Layer"
    opacity: float = 255.00
    position: QPointF = field(default_factory=lambda: QPointF(0, 0))
    rotation: float = 0.00
    scale: float = 1.00
    scale_x: float = 1.00
    scale_y: float = 1.00
    transform_origin: QPointF = field(default_factory=lambda: QPointF(0.0, 0.0))
    order: int = 0
    visible: bool = True
    allow_annotation_export: bool = True
    playing: bool = False
    selected: bool = False
    is_annotable: bool = True
    status: str = "Ready"
    drawing_states: list[DrawingState] = field(default_factory=list)
    edge_opacity: int = 100
    edge_width: int = 1
    caption: str = ""

    def copy(self):
        return LayerState(
            layer_id=self.layer_id,
            layer_name=self.layer_name,
            opacity=self.opacity,
            position=QPointF(self.position.x(), self.position.y()),
            rotation=self.rotation,
            scale=self.scale,
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            transform_origin=QPointF(
                self.transform_origin.x(), self.transform_origin.y()
            ),
            order=self.order,
            visible=self.visible,
            allow_annotation_export=self.allow_annotation_export,
            playing=self.playing,
            selected=self.selected,
            is_annotable=self.is_annotable,
            status=self.status,
            drawing_states=[
                DrawingState(
                    QPointF(d.position.x(), d.position.y()),
                    QColor(d.color.red(), d.color.green(), d.color.blue()),
                    d.size,
                )
                for d in self.drawing_states
            ],
            edge_opacity=self.edge_opacity,
            edge_width=self.edge_width,
            caption=self.caption,
        )


@dataclass
class Label:
    name: str = "Undefined"
    color: QColor = field(default_factory=lambda: QColor(255, 255, 255))


@dataclass
class Annotation:
    annotation_id: int
    label: str
    color: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    points: list[QPointF] = field(default_factory=list)
    # [x, y, width, height]
    rectangle: QRectF = None
    polygon: QPolygonF = None
    mask: np.ndarray = None  # For brush/mask-based annotations
    is_complete: bool = False
    selected: bool = False
    score: float = None
    annotator: str = "User"
    annotation_time: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    visible: bool = True
    file_path: Path = field(default_factory=lambda: Path("Runtime"))
    is_model_generated: bool = False
    model_name: str = None
    caption: str = ""
    label_id: int = 0
    iscrowd: bool = False
    layer_id: str = ""

    def copy(self):
        import numpy as np

        ann = Annotation(
            annotation_id=self.annotation_id,
            label=self.label,
            color=QColor(self.color.red(), self.color.green(), self.color.blue()),
            points=[QPointF(p) for p in self.points],
            rectangle=QRectF(self.rectangle) if self.rectangle else None,
            polygon=QPolygonF(self.polygon) if self.polygon else None,
            mask=np.array(self.mask, copy=True) if self.mask is not None else None,
            is_complete=self.is_complete,
            selected=self.selected,
            score=self.score,
            annotator=self.annotator,
            annotation_time=self.annotation_time,
            visible=self.visible,
            file_path=Path(self.file_path),
            is_model_generated=self.is_model_generated,
            model_name=self.model_name,
            caption=self.caption,
        )
        ann.is_selected = False
        return ann

    @property
    def name(self):
        return f"{self.annotation_id} {self.label}"

    @staticmethod
    def save_as_json(annotations: list["Annotation"], path: str):
        import json

        import numpy as np

        from imagebaker.utils.annotation_formats import mask_to_rle

        annotations_dict = []
        for annotation in annotations:
            rectangle = None
            if annotation.rectangle:
                rectangle = [
                    annotation.rectangle.x(),
                    annotation.rectangle.y(),
                    annotation.rectangle.width(),
                    annotation.rectangle.height(),
                ]
            polygon = None
            if annotation.polygon:
                polygon = [[p.x(), p.y()] for p in annotation.polygon]
            points = None
            if annotation.points:
                points = [[p.x(), p.y()] for p in annotation.points]
            rle = None
            mask_size = None
            if annotation.mask is not None and np.any(annotation.mask):
                mask_arr = np.asarray(annotation.mask)
                if mask_arr.ndim == 3:
                    mask_arr = (
                        mask_arr[:, :, -1]
                        if mask_arr.shape[2] == 4
                        else mask_arr[:, :, 0]
                    )
                rle = mask_to_rle(mask_arr)
                mask_size = [int(mask_arr.shape[0]), int(mask_arr.shape[1])]
            is_brush = bool(rle and not polygon and not rectangle)
            data = {
                "annotation_id": annotation.annotation_id,
                "label": annotation.label,
                "color": annotation.color.getRgb(),
                "type": "brushlabels"
                if is_brush
                else (
                    "polygon"
                    if polygon
                    else ("rectangle" if rectangle else "point")
                ),
                "format": "rle" if rle else None,
                "brushlabels": [annotation.label] if rle else None,
                "rle": rle,
                "mask_size": mask_size,
                "points": points,
                "rectangle": rectangle,
                "polygon": polygon,
                "mask": None,
                "is_complete": annotation.is_complete,
                "selected": annotation.selected,
                "score": annotation.score,
                "annotator": annotation.annotator,
                "annotation_time": annotation.annotation_time,
                "visible": annotation.visible,
                "file_path": str(annotation.file_path),
                "is_model_generated": annotation.is_model_generated,
                "model_name": annotation.model_name,
                "caption": annotation.caption,
            }
            annotations_dict.append(data)

        with open(path, "w") as f:
            json.dump(annotations_dict, f, indent=4)

    @staticmethod
    def load_from_json(path: str):
        import json

        import numpy as np

        from imagebaker.utils.annotation_formats import (
            load_annotations_from_path,
            rle_to_mask,
        )

        # if path does not exist, return empty list
        if not Path(path).exists():
            return []

        with open(path) as f:
            data = json.load(f)

        if isinstance(data, dict) and (
            "categories" in data or "images" in data or "annotations" in data
        ):
            return load_annotations_from_path(path, fmt="auto")

        annotations = []
        for d in data:
            val_dict = d.get("value") if isinstance(d.get("value"), dict) else {}
            brushlabels = d.get("brushlabels") or val_dict.get("brushlabels") or []
            lbl = (
                d.get("label")
                or (
                    brushlabels[0]
                    if isinstance(brushlabels, list) and brushlabels
                    else "Undefined"
                )
            )
            col = d.get("color") or [255, 255, 255]
            annotation = Annotation(
                annotation_id=d.get("annotation_id", len(annotations)),
                label=lbl,
                color=QColor(*col[:3]),
                is_complete=d.get("is_complete", True),
                selected=d.get("selected", False),
                score=d.get("score", None),
                annotator=d.get("annotator", "User"),
                annotation_time=d.get(
                    "annotation_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
                visible=d.get("visible", True),
                file_path=Path(d.get("file_path", "Runtime")),
                is_model_generated=d.get("is_model_generated", False),
                model_name=d.get("model_name", None),
                caption=d.get("caption", ""),
            )

            # Handle points/keypoints safely
            points_data = d.get("points") or d.get("keypoints")
            if points_data:
                annotation.points = [QPointF(*p) for p in points_data]

            # Handle rectangle safely (supports both [x,y,w,h] and [x1,y1,x2,y2]).
            rect_data = d.get("rectangle")
            if rect_data:
                if len(rect_data) == 4:
                    x1, y1, x2_or_w, y2_or_h = rect_data
                    if x2_or_w >= x1 and y2_or_h >= y1 and (
                        d.get("rectangle_format") == "xyxy" or "bbox" in d
                    ):
                        annotation.rectangle = QRectF(
                            x1, y1, x2_or_w - x1, y2_or_h - y1
                        )
                    else:
                        annotation.rectangle = QRectF(x1, y1, x2_or_w, y2_or_h)

            # Handle polygon safely (supports one polygon or list-of-polygons).
            polygon_data = d.get("polygon")
            if polygon_data:
                if (
                    len(polygon_data) > 0
                    and isinstance(polygon_data[0], list)
                    and len(polygon_data[0]) > 0
                    and isinstance(polygon_data[0][0], (list, tuple))
                ):
                    polygon_data = polygon_data[0]
                annotation.polygon = QPolygonF([QPointF(*p) for p in polygon_data])

            # Handle RLE or legacy 2D mask safely
            rle_data = d.get("rle") or val_dict.get("rle")
            mask_size = (
                d.get("mask_size")
                or d.get("size")
                or val_dict.get("mask_size")
                or (
                    [int(d["original_height"]), int(d["original_width"])]
                    if "original_height" in d and "original_width" in d
                    else None
                )
            )
            if rle_data is not None and mask_size and len(mask_size) == 2:
                annotation.mask = rle_to_mask(
                    rle_data, int(mask_size[0]), int(mask_size[1])
                )
            else:
                mask_data = d.get("mask")
                if mask_data is not None:
                    annotation.mask = np.array(mask_data, dtype=np.uint8)

            annotations.append(annotation)

        return annotations


@dataclass
class BakingResult:
    filename: Path
    step: int = 0
    image: QImage = field(default=None)
    masks: list[np.ndarray] = field(default_factory=list)
    mask_names: list[str] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
