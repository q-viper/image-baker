"""Dataset configuration dataclasses and cached asset containers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from imagebaker.core.defs.defs import AnnotationFormat


@dataclass
class DatasetBakeConfig:
    """
    Configuration for dataset generation from ImageBaker cache.
    All properties are reproducible when `seed` is provided.
    """

    seed: int | None = 42

    # Output formatting and splits
    export_format: AnnotationFormat | str = AnnotationFormat.DEFAULT
    split_ratios: dict[str, float] = field(
        default_factory=lambda: {"train": 0.7, "val": 0.2, "test": 0.1}
    )
    prevent_background_leakage: bool = True

    # Background sizing & cropping
    background_size: tuple[int, int] = (640, 640)  # (width, height)
    preserve_aspect_ratio: bool = True
    crop_large_background: bool = True
    crop_mode: Literal["random", "center"] = "random"
    pad_color: tuple[int, int, int] = (114, 114, 114)

    # Foreground layers selection
    layers_per_image: tuple[int, int] = (1, 4)
    background_labels: list[str] = field(
        default_factory=lambda: ["background", "bg", "backdrop"]
    )

    # Layer dimensions constraints
    layer_min_size: tuple[int, int] | int | None = 20
    layer_max_size: tuple[int, int] | int | None = 480

    # Annotation labeling controls (e.g. noise baked into composite without labels)
    labeled_labels: list[str] | None = None
    unlabeled_labels: list[str] = field(
        default_factory=lambda: ["noise", "distractor", "background", "bg"]
    )

    # State variable ranges
    scale_range: tuple[float, float] = (0.6, 1.4)
    scale_x_range: tuple[float, float] | None = None
    scale_y_range: tuple[float, float] | None = None
    rotation_range: tuple[float, float] = (0.0, 360.0)
    opacity_range: tuple[float, float] = (200.0, 255.0)
    edge_opacity_range: tuple[int, int] = (255, 255)
    edge_width_range: tuple[int, int] = (1, 1)

    position_mode: Literal["random", "center"] = "random"
    allow_partial_overflow: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetBakeConfig:
        clean = dict(data)
        for key in (
            "background_size",
            "layers_per_image",
            "scale_range",
            "rotation_range",
            "opacity_range",
        ):
            if key in clean and isinstance(clean[key], list):
                clean[key] = tuple(clean[key])
        return cls(**clean)

    def to_json(self, path: str | Path | None = None) -> str:
        s = json.dumps(self.to_dict(), indent=2)
        if path:
            Path(path).write_text(s, encoding="utf-8")
        return s

    @classmethod
    def from_json(cls, path_or_json: str | Path) -> DatasetBakeConfig:
        p = Path(path_or_json)
        if p.exists() and p.is_file():
            content = p.read_text(encoding="utf-8")
        else:
            content = str(path_or_json)
        return cls.from_dict(json.loads(content))


@dataclass
class CachedLayerAsset:
    """A layer asset loaded from cache."""

    name: str
    label: str
    image: np.ndarray  # RGBA uint8
    polygon: list[list[float]] | None = None
    rectangle: list[float] | None = None  # [x, y, w, h]
    mask: np.ndarray | None = None
    is_background: bool = False
    source_file: str = ""
