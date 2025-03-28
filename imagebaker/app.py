from PySide6.QtWidgets import QApplication
from imagebaker.window.main_window import MainWindow
from imagebaker.core.configs import LayerConfig
from loaded_models import LOADED_MODELS


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow(layerify_config=LayerConfig(), loaded_models=LOADED_MODELS)
    window.show()
    app.exec()
