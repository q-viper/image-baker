from imagebaker.core.configs import LayerConfig, CanvasConfig
from imagebaker import logger
from imagebaker.tabs import LayerifyTab, BakerTab
from imagebaker import __version__


from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QTabWidget,
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        layerify_config: LayerConfig = LayerConfig(),
        canvas_config: CanvasConfig = CanvasConfig(),
        loaded_models: None | dict[str, str] = None,
    ):
        """
        Main window for Image Baker application.

        Args:
            layerify_config (LayerConfig): Configuration for Layerify tab.
            canvas_config (CanvasConfig): Configuration for Canvas tab.
            loaded_models (dict): Dictionary of loaded models.
        """
        super().__init__()
        self.layerify_config = layerify_config
        self.canvas_config = canvas_config
        self.loaded_models = loaded_models

        if self.loaded_models is None:
            self.loaded_models = {}

        # Use QTimer to defer UI initialization
        QTimer.singleShot(0, self.init_ui)

    def init_ui(self):
        """Initialize the main window and set up tabs."""
        try:
            self.setWindowTitle(f"Image Baker v{__version__}")
            self.setGeometry(100, 100, 1200, 800)

            self.status_bar = self.statusBar()
            self.status_bar.showMessage("Ready")

            # Create main tab widget
            self.tab_widget = QTabWidget()
            self.tab_widget.currentChanged.connect(self.handle_tab_change)
            self.setCentralWidget(self.tab_widget)

            # Initialize tabs
            self.layerify_tab = LayerifyTab(
                self, self.layerify_config, self.canvas_config, self.loaded_models
            )
            self.baker_tab = BakerTab(self, self.canvas_config)

            self.tab_widget.addTab(self.layerify_tab, "Layerify")
            self.tab_widget.addTab(self.baker_tab, "Baker")

            # Connect signals
            self.baker_tab.messageSignal.connect(self.update_status)
            self.layerify_tab.layerAdded.connect(self.baker_tab.add_layer)
            self.baker_tab.bakingResult.connect(self.layerify_tab.add_baked_result)
            self.layerify_tab.gotToTab.connect(self.goto_tab)
            # Use QTimer for safe signal connection
            QTimer.singleShot(0, self._connect_final_signals)

            # Handle initial tab state
            self.handle_tab_change(0)

        except Exception as e:
            logger.error(f"MainWindow initialization error: {e}")
            import traceback

            traceback.print_exc()
            QMessageBox.critical(self, "Initialization Error", str(e))

    def _connect_final_signals(self):
        """Connect signals that might require fully initialized objects"""
        try:
            self.layerify_tab.clearAnnotations.connect(
                lambda: QTimer.singleShot(0, self.clear_annotations),
                Qt.QueuedConnection,
            )
            self.layerify_tab.messageSignal.connect(self.update_status)
        except Exception as e:
            logger.error(f"Final signal connection error: {e}")

    def goto_tab(self, tab_index):
        """Switch to the specified tab index."""
        self.tab_widget.setCurrentIndex(tab_index)
        self.update_status("Switched to Layerify tab")

    def clear_annotations(self):
        """Clear all annotations and layers from both tabs."""
        try:
            logger.info("Clearing all annotations")
            # Clear annotations in Layerify tab
            self.layerify_tab.layer.annotations.clear()
            self.layerify_tab.layer.update()

            # Clear layers in Baker tab
            self.baker_tab.layer_list.clear_layers()
            self.baker_tab.current_canvas.clear_layers()

            # Update annotation list
            self.layerify_tab.update_annotation_list()

            # Update status
            self.update_status("All annotations cleared")
        except Exception as e:
            logger.error(f"Error handling clear: {str(e)}")
            self.status_bar.showMessage(f"Error handling clear: {str(e)}")

    def handle_tab_change(self, index):
        """Control annotation panel visibility based on tab"""
        current_tab = self.tab_widget.tabText(index)
        logger.info(f"Switched to {current_tab} tab.")

        if current_tab == "Layerify":
            self.layerify_tab.toolbar_dock.setVisible(True)
            self.layerify_tab.toolbar.setVisible(True)
            self.layerify_tab.annotation_list.setVisible(True)
            self.layerify_tab.image_list_panel.setVisible(True)

            self.baker_tab.layer_settings.setVisible(False)
            self.baker_tab.layer_list.setVisible(True)
            self.baker_tab.toolbar.setVisible(False)
            self.baker_tab.canvas_list.setVisible(False)

        else:
            self.layerify_tab.annotation_list.setVisible(False)
            self.layerify_tab.toolbar.setVisible(False)
            self.layerify_tab.toolbar_dock.setVisible(False)
            self.layerify_tab.image_list_panel.setVisible(False)

            self.baker_tab.layer_list.setVisible(True)
            self.baker_tab.layer_settings.setVisible(True)
            self.baker_tab.toolbar.setVisible(True)
            self.baker_tab.toolbar_dock.setVisible(True)
            self.baker_tab.canvas_list.setVisible(True)
            self.baker_tab.canvas_list.update_canvas_list()
            # self.baker_tab.

    def update_status(self, msg):
        """Update status bar that's visible in all tabs"""
        # if current tab is layerify
        if self.tab_widget.currentIndex() == 0:
            status_text = f"{msg} | Label: {self.layerify_tab.current_label}"
            status_text += (
                f"| Model: {self.layerify_tab.current_model.name} "
                if self.layerify_tab.current_model
                else ""
            )
            status_text += (
                f"| Annotations: {len(self.layerify_tab.layer.annotations)}"
                if self.layerify_tab.layer
                else ""
            )
            status_text += (
                f"| Layers: {len(self.baker_tab.current_canvas.layers)}"
                if self.baker_tab.current_canvas
                else ""
            )
            status_text += f"| Image: {self.layerify_tab.curr_image_idx + 1}"
            status_text += f"/{len(self.layerify_tab.image_entries)}"
        elif self.tab_widget.currentIndex() == 1:
            status_text = (
                f"{msg} | Num Layers: {len(self.baker_tab.current_canvas.layers)}"
                if self.baker_tab.current_canvas
                else ""
            )
        self.status_bar.showMessage(status_text)

    def closeEvent(self, event):
        logger.info("Closing the application.")
        if self.layerify_config.cleanup_on_exit:
            import shutil

            if self.layerify_config.bake_dir.exists():
                shutil.rmtree(self.layerify_config.bake_dir)
                logger.info(f"Deleted bake directory: {self.layerify_config.bake_dir}")
            if self.layerify_config.cache_dir.exists():
                shutil.rmtree(self.layerify_config.cache_dir)
                logger.info(
                    f"Deleted cache directory: {self.layerify_config.cache_dir}"
                )

    def keyPressEvent(self, event):
        # if pressed escape key, close the application
        if event.key() == Qt.Key_Escape:
            logger.info("Escape key pressed, closing the application.")
            self.close()

        # if ctrl+h, show help dialog
        elif event.key() == Qt.Key_H and event.modifiers() == Qt.ControlModifier:
            logger.info("Ctrl+H pressed, showing help dialog.")
            current_tab = self.tab_widget.currentIndex()
            if current_tab == 0:
                info = (
                    "<b>Layerify Tab Shortcuts:</b><br>"
                    "<ul>"
                    "<li><b>Ctrl + C</b>: Copy selected annotation.</li>"
                    "<li><b>Ctrl + V</b>: Paste copied annotation in its parent image if it is currently open.</li>"
                    "<li><b>Delete</b>: Delete selected annotation.</li>"
                    "<li><b>Left Click</b>: Select an annotation on mouse position.</li>"
                    "<li><b>Left Click + Drag</b>: Drag a selected annotation.</li>"
                    "<li><b>Double Left Click</b>: When using polygon annotation, completes the polygon.</li>"
                    "<li><b>Right Click</b>: Unselect an annotation. While annotating the polygon, undo the last point.</li>"
                    "<li><b>Ctrl + Mouse Wheel</b>: Zoom In/Out on the mouse position, i.e., resize the viewport.</li>"
                    "<li><b>Ctrl + Drag</b>: If done on the background, the viewport is panned.</li>"
                    "<li><b>Q</b>: Point mode on annotation.</li>"
                    "<li><b>W</b>: Polygon mode on annotation.</li>"
                    "<li><b>E</b>: Rectangle mode on annotation.</li>"
                    "<li><b>H</b>: Hides/un-hides selected annotation.</li>"
                    "<li><b>L</b>: Creates layer from an annotation. If any annotation selected, creates only its, else creates layers from all visible annotations.</li>"
                    "<li><b>C</b>: If any annotation is selected, a input box for Caption is created.</li>"
                    "<li><b>Numerics</b>: Selecting number 1, 2, till 9 selects label. If not available, asks for a new label.</li>"
                    "<li><b>Escape</b>: Closes the application.</li>"
                    "</ul>"
                )
            elif current_tab == 1:
                info = (
                    "<b>Baker Tab Shortcuts:</b><br>"
                    "<ul>"
                    "<li><b>Ctrl + C</b>: Copy selected layer.</li>"
                    "<li><b>Ctrl + V</b>: Paste copied layer in its parent if it is currently open.</li>"
                    "<li><b>Delete</b>: Delete selected layer.</li>"
                    "<li><b>Left Click</b>: Select a layer on mouse position.</li>"
                    "<li><b>Left Click + Drag</b>: Drag a selected layer.</li>"
                    "<li><b>Ctrl + S</b>: Save State on Baker Tab.</li>"
                    "<li><b>Ctrl + D</b>: Draw Mode on Baker Tab. Drawing can happen on a selected or main layer.</li>"
                    "<li><b>Ctrl + E</b>: Erase Mode on Baker Tab.</li>"
                    "<li><b>Wheel</b>: Change the size of the drawing pointer.</li>"
                    "<li><b>W</b>: Moves selected layer one step up in layer list in baker.</li>"
                    "<li><b>S</b>: Moves selected layer one step down in layer list in baker.</li>"
                    "<li><b>H</b>: Hides/un-hides selected layer.</li>"
                    "<li><b>C</b>: Edit Caption for selected layer.</li>"
                    "<li><b>Escape</b>: Closes the application.</li>"
                    "</ul>"
                )
            else:
                info = "No shortcuts available for this tab."

            QMessageBox.information(
                self,
                "Help",
                info,
            )

        # pass event to other widgets
        return super().keyPressEvent(event)
