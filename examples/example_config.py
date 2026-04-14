from imagebaker.core.configs import CanvasConfig, LayerConfig


class CustomLayerConfig(LayerConfig):
    project_name: str = "Custom Project"


class CustomCanvasConfig(CanvasConfig):
    project_name: str = "Custom Project"
