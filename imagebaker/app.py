from PySide6.QtWidgets import QApplication
from imagebaker.window.main_window import MainWindow
from imagebaker.core.configs import LayerConfig, CanvasConfig
from imagebaker.loaded_models import LOADED_MODELS


app = QApplication([])
window = MainWindow(
    layerify_config=LayerConfig(),
    canvas_config=CanvasConfig(),
    loaded_models=LOADED_MODELS,
)
window.show()
app.exec()
