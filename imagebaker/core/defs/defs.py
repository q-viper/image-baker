from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPolygonF
from PySide6.QtGui import QImage

from enum import Enum
from dataclasses import dataclass, field
import numpy as np
from datetime import datetime
from pydantic import BaseModel
from pathlib import Path


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
    DRAW = 12
    ERASE = 13


class ModelType(str, Enum):
    DETECTION = "detection"
    SEGMENTATION = "segmentation"
    CLASSIFICATION = "classification"
    PROMPT = "prompt"


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
        )


@dataclass
class Label:
    name: str = "Unlabeled"
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

    def copy(self):
        ann = Annotation(
            annotation_id=self.annotation_id,
            label=self.label,
            color=QColor(self.color.red(), self.color.green(), self.color.blue()),
            points=[QPointF(p) for p in self.points],
            rectangle=QRectF(self.rectangle) if self.rectangle else None,
            polygon=QPolygonF(self.polygon) if self.polygon else None,
            is_complete=self.is_complete,
            selected=self.selected,
            score=self.score,
            annotator=self.annotator,
            annotation_time=self.annotation_time,
            visible=self.visible,
            file_path=self.file_path,
            is_model_generated=self.is_model_generated,
            model_name=self.model_name,
        )
        ann.is_selected = False
        return ann

    @property
    def name(self):
        return f"{self.annotation_id} {self.label}"

    @staticmethod
    def save_as_json(annotations: list["Annotation"], path: str):
        import json

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
            data = {
                "annotation_id": annotation.annotation_id,
                "label": annotation.label,
                "color": annotation.color.getRgb(),
                "points": points,
                "rectangle": rectangle,
                "polygon": polygon,
                "is_complete": annotation.is_complete,
                "selected": annotation.selected,
                "score": annotation.score,
                "annotator": annotation.annotator,
                "annotation_time": annotation.annotation_time,
                "visible": annotation.visible,
                "file_path": str(annotation.file_path),
                "is_model_generated": annotation.is_model_generated,
                "model_name": annotation.model_name,
            }
            annotations_dict.append(data)

        with open(path, "w") as f:
            json.dump(annotations_dict, f, indent=4)

    @staticmethod
    def load_from_json(path: str):
        import json

        with open(path, "r") as f:
            data = json.load(f)

        annotations = []
        for d in data:
            annotation = Annotation(
                annotation_id=d["annotation_id"],
                label=d["label"],
                color=QColor(*d["color"]),
                is_complete=d.get("is_complete", False),
                selected=d.get("selected", False),
                score=d.get("score", None),
                annotator=d.get("annotator", None),
                annotation_time=d.get(
                    "annotation_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
                visible=d.get("visible", True),
                file_path=Path(d.get("file_path", "Runtime")),
                is_model_generated=d.get("is_model_generated", False),
                model_name=d.get("model_name", None),
            )

            # Handle points safely
            points_data = d.get("points")
            if points_data:
                annotation.points = [QPointF(*p) for p in points_data]

            # Handle rectangle safely
            rect_data = d.get("rectangle")
            if rect_data:
                annotation.rectangle = QRectF(*rect_data)

            # Handle polygon safely
            polygon_data = d.get("polygon")
            if polygon_data:
                annotation.polygon = QPolygonF([QPointF(*p) for p in polygon_data])

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
