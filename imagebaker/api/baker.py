"""
ImageBaker Core API

Provides the main ImageBaker class for programmatic image composition and annotation.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QImage, QPainter, QPixmap, QTransform)

from imagebaker import logger
from imagebaker.core.configs import CanvasConfig
from imagebaker.core.defs import Annotation, BakingResult, LayerState
from imagebaker.utils.image import qpixmap_to_numpy


class ImageBaker:
    """
    Main ImageBaker class for compositing images with annotations.
    
    This class provides a programmatic interface to ImageBaker's core functionality
    without requiring the GUI.
    
    Example:
        >>> from imagebaker.api import ImageBaker
        >>> baker = ImageBaker()
        >>> baker.add_layer_from_file("path/to/image.png")
        >>> baker.set_layer_position(0, x=100, y=100)
        >>> baker.set_layer_opacity(0, 0.5)
        >>> result = baker.bake()
        >>> baker.save(result, "output.png")
    """
    
    def __init__(self, config: Optional[CanvasConfig] = None, output_dir: Optional[Path] = None):
        """
        Initialize ImageBaker.
        
        Args:
            config: Optional CanvasConfig for customizing behavior
            output_dir: Directory for saving outputs (defaults to ./assets/exports)
        """
        self.config = config or CanvasConfig()
        self.output_dir = Path(output_dir) if output_dir else self.config.export_folder
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.layers: List[Dict] = []
        self.states: Dict[int, List[LayerState]] = {}
        self.current_step = 0
        
        logger.info(f"ImageBaker initialized with output directory: {self.output_dir}")
    
    def add_layer_from_file(self, image_path: Union[str, Path], 
                           layer_name: Optional[str] = None,
                           visible: bool = True,
                           opacity: float = 1.0) -> int:
        """
        Add a layer from an image file.
        
        Args:
            image_path: Path to the image file
            layer_name: Optional name for the layer
            visible: Whether the layer is visible
            opacity: Layer opacity (0.0 to 1.0)
            
        Returns:
            Layer index (ID)
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            raise ValueError(f"Failed to load image: {image_path}")
        
        layer_id = len(self.layers)
        layer_name = layer_name or f"Layer_{layer_id}"
        
        layer = {
            "id": layer_id,
            "name": layer_name,
            "image": pixmap,
            "file_path": image_path,
            "visible": visible,
            "opacity": int(opacity * 255),
            "position": QPointF(0, 0),
            "rotation": 0.0,
            "scale_x": 1.0,
            "scale_y": 1.0,
            "annotations": []
        }
        
        self.layers.append(layer)
        logger.info(f"Added layer '{layer_name}' from {image_path}")
        return layer_id
    
    def add_layer_from_array(self, image: np.ndarray, 
                            layer_name: Optional[str] = None,
                            visible: bool = True,
                            opacity: float = 1.0) -> int:
        """
        Add a layer from a numpy array.
        
        Args:
            image: Image as numpy array (H, W, C)
            layer_name: Optional name for the layer
            visible: Whether the layer is visible
            opacity: Layer opacity (0.0 to 1.0)
            
        Returns:
            Layer index (ID)
        """
        if image.shape[2] == 4:
            format = QImage.Format_RGBA8888
        elif image.shape[2] == 3:
            format = QImage.Format_RGB888
        else:
            raise ValueError("Image must have 3 or 4 channels")
        
        height, width = image.shape[:2]
        bytes_per_line = image.strides[0]
        
        qimage = QImage(image.data, width, height, bytes_per_line, format)
        pixmap = QPixmap.fromImage(qimage.copy())
        
        layer_id = len(self.layers)
        layer_name = layer_name or f"Layer_{layer_id}"
        
        layer = {
            "id": layer_id,
            "name": layer_name,
            "image": pixmap,
            "file_path": Path("Runtime"),
            "visible": visible,
            "opacity": int(opacity * 255),
            "position": QPointF(0, 0),
            "rotation": 0.0,
            "scale_x": 1.0,
            "scale_y": 1.0,
            "annotations": []
        }
        
        self.layers.append(layer)
        logger.info(f"Added layer '{layer_name}' from numpy array")
        return layer_id
    
    def set_layer_position(self, layer_id: int, x: float, y: float):
        """Set the position of a layer."""
        if layer_id >= len(self.layers):
            raise IndexError(f"Layer {layer_id} does not exist")
        self.layers[layer_id]["position"] = QPointF(x, y)
        logger.debug(f"Set layer {layer_id} position to ({x}, {y})")
    
    def set_layer_rotation(self, layer_id: int, rotation: float):
        """Set the rotation of a layer in degrees."""
        if layer_id >= len(self.layers):
            raise IndexError(f"Layer {layer_id} does not exist")
        self.layers[layer_id]["rotation"] = rotation
        logger.debug(f"Set layer {layer_id} rotation to {rotation}°")
    
    def set_layer_scale(self, layer_id: int, scale_x: float, scale_y: Optional[float] = None):
        """Set the scale of a layer."""
        if layer_id >= len(self.layers):
            raise IndexError(f"Layer {layer_id} does not exist")
        if scale_y is None:
            scale_y = scale_x
        self.layers[layer_id]["scale_x"] = scale_x
        self.layers[layer_id]["scale_y"] = scale_y
        logger.debug(f"Set layer {layer_id} scale to ({scale_x}, {scale_y})")
    
    def set_layer_opacity(self, layer_id: int, opacity: float):
        """Set the opacity of a layer (0.0 to 1.0)."""
        if layer_id >= len(self.layers):
            raise IndexError(f"Layer {layer_id} does not exist")
        self.layers[layer_id]["opacity"] = int(max(0, min(255, opacity * 255)))
        logger.debug(f"Set layer {layer_id} opacity to {opacity}")
    
    def set_layer_visibility(self, layer_id: int, visible: bool):
        """Set the visibility of a layer."""
        if layer_id >= len(self.layers):
            raise IndexError(f"Layer {layer_id} does not exist")
        self.layers[layer_id]["visible"] = visible
        logger.debug(f"Set layer {layer_id} visibility to {visible}")
    
    def add_annotation(self, layer_id: int, annotation: Annotation):
        """Add an annotation to a layer."""
        if layer_id >= len(self.layers):
            raise IndexError(f"Layer {layer_id} does not exist")
        self.layers[layer_id]["annotations"].append(annotation)
        logger.debug(f"Added annotation to layer {layer_id}")
    
    def save_state(self, step: Optional[int] = None):
        """
        Save the current state of all layers.
        
        Args:
            step: Optional step number (defaults to auto-increment)
        """
        if step is None:
            step = self.current_step
            self.current_step += 1
        
        states = []
        for layer in self.layers:
            state = LayerState(
                layer_id=layer["id"],
                layer_name=layer["name"],
                opacity=layer["opacity"],
                position=layer["position"],
                rotation=layer["rotation"],
                scale_x=layer["scale_x"],
                scale_y=layer["scale_y"],
                visible=layer["visible"],
                order=layer["id"]
            )
            states.append(state)
        
        self.states[step] = states
        logger.info(f"Saved state at step {step} with {len(states)} layers")
    
    def bake(self, step: Optional[int] = None, 
             include_annotations: bool = True) -> BakingResult:
        """
        Bake (composite) the layers into a single image.
        
        Args:
            step: Optional step number to bake (defaults to current state)
            include_annotations: Whether to include annotations in output
            
        Returns:
            BakingResult with the composited image and annotations
        """
        # If no step specified, save current state and use it
        if step is None:
            if not self.states:
                self.save_state()
            step = max(self.states.keys())
        
        if step not in self.states:
            raise ValueError(f"Step {step} not found in saved states")
        
        states = self.states[step]
        
        # Calculate bounding box
        import sys
        top_left = QPointF(sys.maxsize, sys.maxsize)
        bottom_right = QPointF(-sys.maxsize, -sys.maxsize)
        
        for state in states:
            layer = self.layers[state.layer_id]
            if layer["visible"] and not layer["image"].isNull():
                transform = QTransform()
                transform.translate(state.position.x(), state.position.y())
                transform.rotate(state.rotation)
                transform.scale(state.scale_x, state.scale_y)
                
                original_rect = QRectF(QPointF(0, 0), layer["image"].size())
                transformed_rect = transform.mapRect(original_rect)
                
                top_left.setX(min(top_left.x(), transformed_rect.left()))
                top_left.setY(min(top_left.y(), transformed_rect.top()))
                bottom_right.setX(max(bottom_right.x(), transformed_rect.right()))
                bottom_right.setY(max(bottom_right.y(), transformed_rect.bottom()))
        
        # Create output image
        width = int(bottom_right.x() - top_left.x())
        height = int(bottom_right.y() - top_left.y())
        
        if width <= 0 or height <= 0:
            raise ValueError("Invalid bounding box for baking")
        
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        
        painter = QPainter(image)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        
        masks = []
        mask_names = []
        annotations = []
        
        # Paint layers
        for state in sorted(states, key=lambda s: s.order):
            layer = self.layers[state.layer_id]
            if not layer["visible"] or layer["image"].isNull():
                continue
            
            painter.save()
            
            # Apply transformations relative to bounding box
            painter.translate(
                state.position.x() - top_left.x(),
                state.position.y() - top_left.y()
            )
            painter.rotate(state.rotation)
            painter.scale(state.scale_x, state.scale_y)
            
            # Apply opacity
            painter.setOpacity(state.opacity / 255.0)
            painter.drawPixmap(0, 0, layer["image"])
            
            painter.restore()
            
            # Collect masks and annotations
            if include_annotations and layer["annotations"]:
                for ann in layer["annotations"]:
                    if ann.visible:
                        # Transform annotation coordinates
                        transform = QTransform()
                        transform.translate(
                            state.position.x() - top_left.x(),
                            state.position.y() - top_left.y()
                        )
                        transform.rotate(state.rotation)
                        transform.scale(state.scale_x, state.scale_y)
                        
                        transformed_ann = ann.copy()
                        if ann.polygon:
                            transformed_ann.polygon = transform.map(ann.polygon)
                        if ann.rectangle:
                            transformed_ann.rectangle = transform.mapRect(ann.rectangle)
                        if ann.points:
                            transformed_ann.points = [transform.map(p) for p in ann.points]
                        
                        annotations.append(transformed_ann)
        
        painter.end()
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = Path(self.config.filename_format.format(
            project_name=self.config.project_name,
            timestamp=timestamp
        ))
        
        result = BakingResult(
            filename=filename,
            step=step,
            image=image,
            masks=masks,
            mask_names=mask_names,
            annotations=annotations
        )
        
        logger.info(f"Baked image at step {step}: {width}x{height}")
        return result
    
    def save(self, result: BakingResult, output_path: Optional[Union[str, Path]] = None,
             save_annotations: bool = True) -> Path:
        """
        Save a baking result to disk.
        
        Args:
            result: BakingResult to save
            output_path: Optional output path (defaults to config export folder)
            save_annotations: Whether to save annotations as JSON
            
        Returns:
            Path to the saved image
        """
        if output_path is None:
            output_path = self.output_dir / f"{result.filename}.{self.config.export_format}"
        else:
            output_path = Path(output_path)
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save image
        result.image.save(str(output_path))
        logger.info(f"Saved baked image to {output_path}")
        
        # Save annotations
        if save_annotations and result.annotations:
            json_path = output_path.with_suffix(".json")
            Annotation.save_as_json(result.annotations, str(json_path))
            logger.info(f"Saved annotations to {json_path}")
        
        return output_path
    
    def bake_and_save(self, output_path: Optional[Union[str, Path]] = None,
                     step: Optional[int] = None) -> Path:
        """
        Convenience method to bake and save in one call.
        
        Args:
            output_path: Optional output path
            step: Optional step number to bake
            
        Returns:
            Path to the saved image
        """
        result = self.bake(step=step)
        return self.save(result, output_path)
    
    def to_numpy(self, result: BakingResult) -> np.ndarray:
        """
        Convert a baking result to a numpy array.
        
        Args:
            result: BakingResult to convert
            
        Returns:
            Numpy array with shape (H, W, C)
        """
        return qpixmap_to_numpy(QPixmap.fromImage(result.image))
    
    def get_layer_count(self) -> int:
        """Get the number of layers."""
        return len(self.layers)
    
    def get_layer_info(self, layer_id: int) -> Dict:
        """Get information about a layer."""
        if layer_id >= len(self.layers):
            raise IndexError(f"Layer {layer_id} does not exist")
        
        layer = self.layers[layer_id]
        return {
            "id": layer["id"],
            "name": layer["name"],
            "visible": layer["visible"],
            "opacity": layer["opacity"] / 255.0,
            "position": (layer["position"].x(), layer["position"].y()),
            "rotation": layer["rotation"],
            "scale": (layer["scale_x"], layer["scale_y"]),
            "file_path": str(layer["file_path"]),
            "annotation_count": len(layer["annotations"])
        }
