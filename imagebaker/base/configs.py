from pydantic import BaseModel
from typing import Tuple, Union
from pathlib import Path


class BaseLayerConfig(BaseModel):
    name: str = "BaseLayer"
    layer_size: Tuple[int, int] = (1000, 1000)
    layer_background: Union[Path, Tuple[int, int, int]] = Path("../assets/me.jpg")
    # applied on layer when it is created
    layer_alpha: int = 255
    layer_visible: bool = True
    layer_locked: bool = False
    allow_children: bool = True
    allow_parent: bool = True
    resize_if_needed: bool = True
    layer_position: Tuple[int, int] = (0, 0)

    class Config:
        arbitrary_types_allowed = True
