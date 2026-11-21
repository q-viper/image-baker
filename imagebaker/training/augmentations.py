"""Built-in configurable augmentation descriptors for the visual training pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BaseAugmentationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Enable or disable this augmentation.")
    probability: float = Field(default=0.5, ge=0.0, le=1.0, description="Application probability.")


class HorizontalFlipConfig(BaseAugmentationConfig):
    pass


class VerticalFlipConfig(BaseAugmentationConfig):
    probability: float = Field(default=0.2, ge=0.0, le=1.0)


class RandomRotateConfig(BaseAugmentationConfig):
    max_angle: float = Field(default=25.0, ge=0.0, le=180.0, description="Max rotation degrees.")


class ColorJitterConfig(BaseAugmentationConfig):
    brightness: float = Field(default=0.2, ge=0.0, le=1.0)
    contrast: float = Field(default=0.2, ge=0.0, le=1.0)
    saturation: float = Field(default=0.2, ge=0.0, le=1.0)
    hue: float = Field(default=0.05, ge=0.0, le=0.5)


class GaussianBlurConfig(BaseAugmentationConfig):
    probability: float = Field(default=0.25, ge=0.0, le=1.0)
    kernel_size: int = Field(default=5, ge=3, le=31)


class MosaicConfig(BaseAugmentationConfig):
    probability: float = Field(default=0.5, ge=0.0, le=1.0)


class RandomCropConfig(BaseAugmentationConfig):
    min_scale: float = Field(default=0.7, ge=0.1, le=1.0)


class BaseAugmentation:
    """Descriptor for an augmentation node in the training pipeline."""

    name: str = "Augmentation"
    description: str = ""
    config_class: type[BaseAugmentationConfig] = BaseAugmentationConfig

    def __init__(self, name: str | None = None, description: str | None = None):
        if name:
            self.name = name
        if description is not None:
            self.description = description

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "defaults": self.config_class().model_dump(),
            "schema": self.config_class.model_json_schema(),
        }


class HorizontalFlipAugmentation(BaseAugmentation):
    name = "HorizontalFlip"
    description = "Randomly flip images and annotations horizontally."
    config_class = HorizontalFlipConfig


class VerticalFlipAugmentation(BaseAugmentation):
    name = "VerticalFlip"
    description = "Randomly flip images and annotations vertically."
    config_class = VerticalFlipConfig


class RandomRotateAugmentation(BaseAugmentation):
    name = "RandomRotate"
    description = "Randomly rotate images and annotations up to max_angle."
    config_class = RandomRotateConfig


class ColorJitterAugmentation(BaseAugmentation):
    name = "ColorJitter"
    description = "Randomly jitter brightness, contrast, saturation, and hue."
    config_class = ColorJitterConfig


class GaussianBlurAugmentation(BaseAugmentation):
    name = "GaussianBlur"
    description = "Apply Gaussian blur to simulate motion/defocus."
    config_class = GaussianBlurConfig


class MosaicAugmentation(BaseAugmentation):
    name = "Mosaic"
    description = "Combine 4 training images into a mosaic tile (YOLO-style)."
    config_class = MosaicConfig


class RandomCropAugmentation(BaseAugmentation):
    name = "RandomCrop"
    description = "Randomly crop and resize training images."
    config_class = RandomCropConfig


BUILTIN_AUGMENTATIONS: dict[str, BaseAugmentation] = {
    aug.name: aug
    for aug in [
        HorizontalFlipAugmentation(),
        VerticalFlipAugmentation(),
        RandomRotateAugmentation(),
        ColorJitterAugmentation(),
        GaussianBlurAugmentation(),
        MosaicAugmentation(),
        RandomCropAugmentation(),
    ]
}
