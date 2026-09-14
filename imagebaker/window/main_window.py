from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from imagebaker import __version__, logger
from imagebaker.core.configs import CanvasConfig, LayerConfig
from imagebaker.tabs import BakerTab, HelpTab, LayerifyTab


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
        self.theme_mode = "light"

        if self.loaded_models is None:
            self.loaded_models = {}

        # Use QTimer to defer UI initialization
        QTimer.singleShot(0, self.init_ui)

    def init_ui(self):
        """Initialize the main window and set up tabs."""
        try:
            self.setWindowTitle(f"Image Baker v{__version__}")

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
            self.help_tab = HelpTab(self)

            self.tab_widget.addTab(self.layerify_tab, "Layerify")
            self.tab_widget.addTab(self.baker_tab, "Baker")
            self.tab_widget.addTab(self.help_tab, "Help")

            # Connect signals
            self.baker_tab.messageSignal.connect(self.update_status)
            self.baker_tab.requestTabSwitch.connect(self.goto_tab)
            self.layerify_tab.layerAdded.connect(self.baker_tab.add_layer)
            self.baker_tab.bakingResult.connect(self.layerify_tab.add_baked_result)
            self.layerify_tab.gotToTab.connect(self.goto_tab)
            # Use QTimer for safe signal connection
            QTimer.singleShot(0, self._connect_final_signals)

            # Handle initial tab state
            self.handle_tab_change(0)
            self.apply_theme(self.theme_mode)
            QTimer.singleShot(0, self._fit_to_screen)

        except Exception as e:
            logger.error(f"MainWindow initialization error: {e}")
            import traceback

            traceback.print_exc()
            QMessageBox.critical(self, "Initialization Error", str(e))

    def _fit_to_screen(self):
        """Size the initial window in logical pixels, leaving room for decorations."""
        screen = self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.resize(
            min(1200, int(available.width() * 0.9)),
            min(800, int(available.height() * 0.9)),
        )
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

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

    def apply_theme(self, mode: str):
        """Apply light or dark theme to the full window."""
        if mode == "dark":
            stylesheet = """
                QMainWindow {
                    background-color: #121925;
                    color: #e8eef7;
                }
                QWidget {
                    background-color: #121925;
                    color: #e8eef7;
                    selection-background-color: #2d73dd;
                    selection-color: #f6f9ff;
                }
                QToolTip {
                    background-color: #1f2a3b;
                    color: #f6f9ff;
                    border: 1px solid #3e526f;
                    padding: 4px 6px;
                }
                QTabWidget::pane {
                    border: 1px solid #2b3a4f;
                    background: #162235;
                    top: -1px;
                }
                QTabBar::tab {
                    background: #1a2a40;
                    color: #ced9e7;
                    border: 1px solid #2b3a4f;
                    border-bottom: none;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    padding: 7px 14px;
                    margin-right: 3px;
                }
                QTabBar::tab:hover:!selected {
                    background: #22344e;
                }
                QTabBar::tab:selected {
                    background: #263a57;
                    color: #ffffff;
                    border-color: #4f6788;
                }
                QDockWidget {
                    border: 1px solid #2b3a4f;
                }
                QDockWidget::title {
                    background: #1b2a3e;
                    color: #dbe6f5;
                    border-bottom: 1px solid #2b3a4f;
                    text-align: left;
                    padding: 6px 8px;
                }
                QPushButton, QToolButton {
                    background-color: #233650;
                    color: #e8eef7;
                    border: 1px solid #385272;
                    border-radius: 6px;
                    padding: 5px 10px;
                }
                QPushButton:hover, QToolButton:hover {
                    background-color: #2b4160;
                    border-color: #54739a;
                }
                QPushButton:pressed, QToolButton:pressed {
                    background-color: #1c2b41;
                }
                QPushButton:checked, QToolButton:checked {
                    background-color: #2d73dd;
                    border-color: #5f9bfa;
                    color: #ffffff;
                }
                QLineEdit, QTextEdit, QPlainTextEdit,
                QListWidget, QComboBox, QSpinBox, QDoubleSpinBox {
                    background-color: #182438;
                    color: #e8eef7;
                    border: 1px solid #314761;
                    border-radius: 6px;
                    padding: 4px 6px;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
                QListWidget:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                    border: 1px solid #5f9bfa;
                    background-color: #1d2d46;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 18px;
                }
                QScrollBar:vertical {
                    background: #162235;
                    width: 11px;
                    margin: 1px;
                }
                QScrollBar::handle:vertical {
                    background: #3a4f6c;
                    min-height: 22px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #4d678b;
                }
                QScrollBar:horizontal {
                    background: #162235;
                    height: 11px;
                    margin: 1px;
                }
                QScrollBar::handle:horizontal {
                    background: #3a4f6c;
                    min-width: 22px;
                    border-radius: 5px;
                }
                QStatusBar {
                    background-color: #162235;
                    color: #dbe6f5;
                    border-top: 1px solid #2b3a4f;
                }
                QMenu {
                    background-color: #1a2a40;
                    color: #e8eef7;
                    border: 1px solid #385272;
                }
                QMenu::item:selected {
                    background-color: #2d73dd;
                    color: #ffffff;
                }
            """
        else:
            stylesheet = """
                QMainWindow {
                    background-color: #f3f6fa;
                    color: #1e2733;
                }
                QWidget {
                    background-color: #f3f6fa;
                    color: #1e2733;
                    selection-background-color: #8cb6ff;
                    selection-color: #0f1f36;
                }
                QToolTip {
                    background-color: #ffffff;
                    color: #1e2733;
                    border: 1px solid #b8c7dd;
                    padding: 4px 6px;
                }
                QTabWidget::pane {
                    border: 1px solid #b9c8dc;
                    background: #eaf0f8;
                    top: -1px;
                }
                QTabBar::tab {
                    background: #dde7f4;
                    color: #30435d;
                    border: 1px solid #b9c8dc;
                    border-bottom: none;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    padding: 7px 14px;
                    margin-right: 3px;
                }
                QTabBar::tab:hover:!selected {
                    background: #d1def0;
                }
                QTabBar::tab:selected {
                    background: #f8fbff;
                    color: #162a44;
                    border-color: #9bb2d2;
                }
                QDockWidget {
                    border: 1px solid #b9c8dc;
                }
                QDockWidget::title {
                    background: #dfe8f5;
                    color: #22344d;
                    border-bottom: 1px solid #b9c8dc;
                    text-align: left;
                    padding: 6px 8px;
                }
                QPushButton, QToolButton {
                    background-color: #e5edf8;
                    color: #1f3148;
                    border: 1px solid #9fb4d1;
                    border-radius: 6px;
                    padding: 5px 10px;
                }
                QPushButton:hover, QToolButton:hover {
                    background-color: #d8e5f5;
                    border-color: #7f9fc8;
                }
                QPushButton:pressed, QToolButton:pressed {
                    background-color: #c7d8ee;
                }
                QPushButton:checked, QToolButton:checked {
                    background-color: #3f83f8;
                    border-color: #2f6ed8;
                    color: #ffffff;
                }
                QLineEdit, QTextEdit, QPlainTextEdit,
                QListWidget, QComboBox, QSpinBox, QDoubleSpinBox {
                    background-color: #ffffff;
                    color: #1f3148;
                    border: 1px solid #adc0da;
                    border-radius: 6px;
                    padding: 4px 6px;
                }
                QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
                QListWidget:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                    border: 1px solid #508de8;
                    background-color: #f6f9ff;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 18px;
                }
                QScrollBar:vertical {
                    background: #e8eef7;
                    width: 11px;
                    margin: 1px;
                }
                QScrollBar::handle:vertical {
                    background: #b2c2d8;
                    min-height: 22px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #8fa5c3;
                }
                QScrollBar:horizontal {
                    background: #e8eef7;
                    height: 11px;
                    margin: 1px;
                }
                QScrollBar::handle:horizontal {
                    background: #b2c2d8;
                    min-width: 22px;
                    border-radius: 5px;
                }
                QStatusBar {
                    background-color: #e4ebf6;
                    color: #22344d;
                    border-top: 1px solid #b9c8dc;
                }
                QMenu {
                    background-color: #ffffff;
                    color: #22344d;
                    border: 1px solid #b8c7dd;
                }
                QMenu::item:selected {
                    background-color: #d9e8ff;
                    color: #15253a;
                }
            """
        self.setStyleSheet(stylesheet)
        self.theme_mode = mode
        self.update_status(f"Theme set to {mode}")

    def toggle_theme(self):
        """Toggle between dark and light theme."""
        self.apply_theme("dark" if self.theme_mode == "light" else "light")

    def goto_tab(self, tab_index):
        """Switch to the specified tab index."""
        self.tab_widget.setCurrentIndex(tab_index)
        tab_name = self.tab_widget.tabText(tab_index)
        self.update_status(f"Switched to {tab_name} tab")

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
            # Detach Baker docks so their splitter widths cannot affect Layerify.
            self.removeDockWidget(self.baker_tab.layer_list)
            self.removeDockWidget(self.baker_tab.layer_settings)
            self.removeDockWidget(self.baker_tab.toolbar_dock)
            self.removeDockWidget(self.baker_tab.canvas_list)

            # Re-attach Layerify docks in expected areas.
            self.addDockWidget(Qt.LeftDockWidgetArea, self.layerify_tab.image_list_panel)
            self.addDockWidget(Qt.RightDockWidgetArea, self.layerify_tab.annotation_list)
            self.addDockWidget(Qt.BottomDockWidgetArea, self.layerify_tab.toolbar_dock)
            # Keep layers list accessible on Layerify tab.
            self.addDockWidget(Qt.RightDockWidgetArea, self.baker_tab.layer_list)

            self.layerify_tab.toolbar_dock.setVisible(True)
            self.layerify_tab.toolbar.setVisible(True)
            self.layerify_tab.annotation_list.setVisible(True)
            self.layerify_tab.image_list_panel.setVisible(True)
            self.layerify_tab.toolbar_dock.raise_()
            self.layerify_tab.annotation_list.raise_()
            self.layerify_tab.image_list_panel.raise_()

            self.baker_tab.layer_settings.setVisible(False)
            self.baker_tab.layer_list.setVisible(True)
            self.baker_tab.toolbar.setVisible(False)
            self.baker_tab.toolbar_dock.setVisible(False)
            self.baker_tab.canvas_list.setVisible(False)
            QTimer.singleShot(0, self._refresh_layerify_layout)

        elif current_tab == "Baker":
            # Detach Layerify docks so their splitter widths cannot affect Baker.
            self.removeDockWidget(self.layerify_tab.annotation_list)
            self.removeDockWidget(self.layerify_tab.image_list_panel)
            self.removeDockWidget(self.layerify_tab.toolbar_dock)

            # Re-attach Baker docks in expected areas.
            self.addDockWidget(Qt.LeftDockWidgetArea, self.baker_tab.canvas_list)
            self.addDockWidget(Qt.RightDockWidgetArea, self.baker_tab.layer_list)
            self.addDockWidget(Qt.RightDockWidgetArea, self.baker_tab.layer_settings)
            self.addDockWidget(Qt.BottomDockWidgetArea, self.baker_tab.toolbar_dock)

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
            self.baker_tab.reload_plugins()

        else:
            # Help page: detach all side docks for a clean reading layout.
            self.removeDockWidget(self.layerify_tab.annotation_list)
            self.removeDockWidget(self.layerify_tab.image_list_panel)
            self.removeDockWidget(self.layerify_tab.toolbar_dock)
            self.removeDockWidget(self.baker_tab.canvas_list)
            self.removeDockWidget(self.baker_tab.layer_list)
            self.removeDockWidget(self.baker_tab.layer_settings)
            self.removeDockWidget(self.baker_tab.toolbar_dock)

            self.layerify_tab.annotation_list.setVisible(False)
            self.layerify_tab.toolbar.setVisible(False)
            self.layerify_tab.toolbar_dock.setVisible(False)
            self.layerify_tab.image_list_panel.setVisible(False)

            self.baker_tab.layer_list.setVisible(False)
            self.baker_tab.layer_settings.setVisible(False)
            self.baker_tab.toolbar.setVisible(False)
            self.baker_tab.toolbar_dock.setVisible(False)
            self.baker_tab.canvas_list.setVisible(False)

    def _refresh_layerify_layout(self):
        """Force a repaint/layout pass for Layerify docks after tab switch."""
        self.layerify_tab.image_list_panel.update()
        self.layerify_tab.annotation_list.update()
        self.layerify_tab.toolbar_dock.update()
        self.layerify_tab.updateGeometry()
        self.layerify_tab.update()

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
        else:
            status_text = msg
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
        else:
            # save the annotations to disk
            for layer in self.layerify_tab.annotable_layers:
                self.layerify_tab.save_layer_annotations(layer, delete_if_empty=False)
            self.layerify_tab.cleanup_stale_annotation_cache()

            for canvas in self.baker_tab.canvases:
                self.baker_tab.save_canvas_to_cache(canvas)

    def keyPressEvent(self, event):
        # if pressed escape key, close the application
        if event.key() == Qt.Key_Escape:
            logger.info("Escape key pressed, closing the application.")
            self.close()

        # if ctrl+h, open help tab
        elif event.key() == Qt.Key_H and event.modifiers() == Qt.ControlModifier:
            logger.info("Ctrl+H pressed, opening help tab.")
            self.goto_tab(2)
            return

        # pass event to other widgets
        return super().keyPressEvent(event)
