"""
Model Loading API

Provides utilities for loading and managing models.
"""

import runpy
from pathlib import Path
from typing import Dict, Optional

from imagebaker import logger
from imagebaker.models.base_model import BaseModel


def load_model(model_path: str, model_name: Optional[str] = None) -> BaseModel:
    """
    Load a model from a Python file.
    
    Args:
        model_path: Path to the Python file containing the model
        model_name: Optional name of the model variable to load (defaults to first model found)
        
    Returns:
        BaseModel instance
        
    Example:
        >>> model = load_model("examples/segmentation.py")
        >>> predictions = model.predict(image)
    """
    model_path = Path(model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    
    try:
        # Execute the file
        loaded_globals = runpy.run_path(str(model_path))
        
        if model_name:
            if model_name not in loaded_globals:
                raise ValueError(f"Model '{model_name}' not found in {model_path}")
            model = loaded_globals[model_name]
        else:
            # Find first BaseModel instance
            model = None
            for value in loaded_globals.values():
                if isinstance(value, BaseModel):
                    model = value
                    break
            
            if model is None:
                raise ValueError(f"No BaseModel instance found in {model_path}")
        
        logger.info(f"Loaded model from {model_path}")
        return model
        
    except Exception as e:
        logger.error(f"Failed to load model from {model_path}: {e}")
        raise


def load_models(models_file: str) -> Dict[str, BaseModel]:
    """
    Load multiple models from a file containing LOADED_MODELS dictionary.
    
    Args:
        models_file: Path to Python file with LOADED_MODELS dict
        
    Returns:
        Dictionary mapping model names to model instances
        
    Example:
        >>> models = load_models("examples/loaded_models.py")
        >>> detector = models["RTDetrV2"]
        >>> segmenter = models["SegmentationModel"]
    """
    models_file = Path(models_file)
    if not models_file.exists():
        raise FileNotFoundError(f"Models file not found: {models_file}")
    
    try:
        loaded_globals = runpy.run_path(str(models_file))
        
        if "LOADED_MODELS" not in loaded_globals:
            raise ValueError(f"No LOADED_MODELS dictionary found in {models_file}")
        
        models = loaded_globals["LOADED_MODELS"]
        logger.info(f"Loaded {len(models)} models from {models_file}")
        return models
        
    except Exception as e:
        logger.error(f"Failed to load models from {models_file}: {e}")
        raise
