from imagebaker.window.app import main
from imagebaker.core.configs import LayerConfig, CanvasConfig
from loaded_models import LOADED_MODELS

if __name__ == "__main__":
    main(
        layer_config=LayerConfig(),
        canvas_config=CanvasConfig(),
        LOADED_MODELS=LOADED_MODELS,
    )
