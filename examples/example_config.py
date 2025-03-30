from imagebaker.core.configs import LayerConfig, CanvasConfig


class CustomLayerConfig(LayerConfig):
    project_name: str = "Custom Project"


class CustomCanvasConfig(CanvasConfig):
    project_name: str = "Custom Project"
