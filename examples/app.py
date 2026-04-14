from imagebaker.core.configs import CanvasConfig, LayerConfig
from imagebaker.window.app import main

# from loaded_models import LOADED_MODELS

if __name__ == "__main__":
    main(
        layer_config=LayerConfig(),
        canvas_config=CanvasConfig(),
        # LOADED_MODELS=LOADED_MODELS,
        LOADED_MODELS={None: None},
    )
