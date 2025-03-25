from imagebaker.base.configs import BaseLayerConfig
from imagebaker.base.modifier import BaseModifier
from imagebaker.base.painter import BasePainter

from PIL import Image
from pathlib import Path
from typing import List, Union, Tuple
import numpy as np
import matplotlib.pyplot as plt


class BaseLayer:
    def __init__(self, config: BaseLayerConfig = BaseLayerConfig()) -> None:
        self.config = config
        self._parent: "BaseLayer" = None
        self._children: List["BaseLayer"] = []
        self.layer_id = 0
        self._executors: Union[List["BaseLayer"], List[BaseModifier]] = []
        self._layer = None
        self.is_baked = False
        self._modifiers: List[BaseModifier] = []

    @property
    def gen_name(self) -> str:
        return f"{self.config.name}_{self.parent}_{self.layer_id}"

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def parent(self) -> "BaseLayer":
        return self._parent

    @parent.setter
    def parent(self, parent: "BaseLayer"):
        if self.config.allow_parent:
            self._parent = parent
        else:
            raise ValueError("This layer does not allow a parent")

    @property
    def children(self) -> List["BaseLayer"]:
        return self._children

    @property
    def executors(self) -> List[Union["BaseLayer", BaseModifier]]:
        return self._executors

    @property
    def modifiers(self) -> List[BaseModifier]:
        return self._modifiers

    @property
    def id(self) -> int:
        return self.layer_id

    @property
    def layer(self) -> Image.Image:
        return self._layer

    def __str__(self):
        return self.config.name

    def _init_layer(self) -> "BaseLayer":
        if isinstance(self.config.layer_background, Path):
            with Image.open(self.config.layer_background) as img:
                # Convert image to RGBA if it is not
                img = img.convert("RGBA")
                if self.config.resize_if_needed:
                    img = img.resize(self.config.layer_size)
                background = np.array(img)
                background[..., 3] = self.config.layer_alpha

        elif isinstance(self.config.layer_background, Tuple):
            background = np.zeros((*self.config.layer_size, 3), dtype=np.uint8)
            background[:] = self.config.layer_background
            background = np.dstack(
                (
                    background,
                    np.full(
                        self.config.layer_size, self.config.layer_alpha, dtype=np.uint8
                    ),
                )
            )
        self.background = background
        self._layer = Image.fromarray(self.background.copy())
        return self

    def bake_layer(self) -> "BaseLayer":
        self._init_layer()
        for executor in self.executors:

            if isinstance(executor, BaseLayer):
                executor.bake_layer()
                self._layer.alpha_composite(
                    executor.layer, executor.config.layer_position
                )
            elif isinstance(executor, BaseModifier):
                self._layer = executor.modify(self._layer)
            elif isinstance(executor, BasePainter):
                self._layer = executor.paint(self._layer)
            print(self.gen_name, executor.name)
            # self.show_layer(self._layer)
        self.is_baked = True
        return self

    def show_layer(self, layer: Image.Image = None):
        if layer is not None:
            plt.imshow(layer)
            plt.show()
            return
        if not self.is_baked:
            self.bake_layer()
        plt.imshow(self.layer)
        plt.show()

    def add_child(self, child: "BaseLayer") -> "BaseLayer":
        if self.config.allow_children:
            child.layer_id = len(self.children)
            self._children.append(child)
            child.parent = self
            self.executors.append(child)

        return self

    def remove_child(self, child: "BaseLayer") -> "BaseLayer":
        if child in self.children:
            self._children.remove(child)
            child.parent = None
        return self

    def add_modifier(self, modifier: List[BaseModifier]) -> "BaseLayer":
        self._modifiers.extend(modifier)
        self._executors.extend(modifier)
        return self

    def remove_modifier(self, modifier: List[BaseModifier]) -> "BaseLayer":
        if modifier in self.modifiers:
            self._modifiers.remove(modifier)
        return self
