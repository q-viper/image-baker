import pytest
from unittest.mock import MagicMock, patch
from imagebaker.window.main_window import MainWindow
from imagebaker.core.configs import LayerConfig, CanvasConfig
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    """Create a QApplication instance for testing."""
    app = QApplication([])
    yield app
    app.quit()


@pytest.fixture
def main_window():
    """Create a MainWindow instance for testing."""
    layer_config = LayerConfig()
    canvas_config = CanvasConfig()
    loaded_models = {"Model1": "DummyModel"}
    return MainWindow(
        layerify_config=layer_config,
        canvas_config=canvas_config,
        loaded_models=loaded_models,
    )


def test_main_window_initialization(main_window):
    """Test if MainWindow initializes correctly."""
    assert main_window.layerify_config is not None
    assert main_window.canvas_config is not None
    assert main_window.loaded_models is not None
    assert main_window.windowTitle() == "Image Baker"
    assert main_window.tab_widget.count() == 2  # Ensure both tabs are added


def test_main_window_handle_tab_change(main_window):
    """Test if handle_tab_change updates the UI components correctly."""
    with patch.object(
        main_window.layerify_tab, "toolbar_dock", create=True
    ) as mock_toolbar_dock:
        with patch.object(
            main_window.layerify_tab, "toolbar", create=True
        ) as mock_toolbar:
            with patch.object(
                main_window.layerify_tab, "annotation_list", create=True
            ) as mock_annotation_list:
                with patch.object(
                    main_window.layerify_tab, "image_list_panel", create=True
                ) as mock_image_list_panel:
                    with patch.object(
                        main_window.baker_tab, "layer_settings", create=True
                    ) as mock_layer_settings:
                        with patch.object(
                            main_window.baker_tab, "layer_list", create=True
                        ) as mock_layer_list:
                            with patch.object(
                                main_window.baker_tab, "toolbar", create=True
                            ) as mock_baker_toolbar:
                                with patch.object(
                                    main_window.baker_tab, "canvas_list", create=True
                                ) as mock_canvas_list:
                                    # Simulate switching to the "Layerify" tab
                                    main_window.handle_tab_change(0)
                                    mock_toolbar_dock.setVisible.assert_called_with(
                                        True
                                    )
                                    mock_toolbar.setVisible.assert_called_with(True)
                                    mock_annotation_list.setVisible.assert_called_with(
                                        True
                                    )
                                    mock_image_list_panel.setVisible.assert_called_with(
                                        True
                                    )

                                    # Simulate switching to the "Baker" tab
                                    main_window.handle_tab_change(1)
                                    mock_layer_settings.setVisible.assert_called_with(
                                        True
                                    )
                                    mock_layer_list.setVisible.assert_called_with(True)
                                    mock_baker_toolbar.setVisible.assert_called_with(
                                        True
                                    )
                                    mock_canvas_list.setVisible.assert_called_with(True)


def test_main_window_update_status(main_window):
    """Test if update_status updates the status bar correctly."""
    with patch.object(main_window.status_bar, "showMessage") as mock_show_message:
        main_window.update_status("Test message")
        mock_show_message.assert_called_once_with("Test message")


def test_main_window_clear_annotations(main_window):
    """Test if clear_annotations clears annotations correctly."""
    with patch.object(
        main_window.layerify_tab.layer, "annotations", create=True
    ) as mock_annotations:
        with patch.object(main_window.layerify_tab.layer, "update") as mock_update:
            with patch.object(
                main_window.baker_tab.layer_list, "clear_layers"
            ) as mock_clear_layers:
                with patch.object(
                    main_window.baker_tab.current_canvas, "clear_layers"
                ) as mock_clear_canvas:
                    with patch.object(
                        main_window.layerify_tab, "update_annotation_list"
                    ) as mock_update_annotation_list:
                        main_window.clear_annotations()
                        mock_annotations.clear.assert_called_once()
                        mock_update.assert_called_once()
                        mock_clear_layers.assert_called_once()
                        mock_clear_canvas.assert_called_once()
                        mock_update_annotation_list.assert_called_once()


def test_main_window_close_event(main_window):
    """Test if closeEvent cleans up tabs correctly."""
    with patch.object(main_window.layerify_tab, "deleteLater") as mock_layerify_delete:
        with patch.object(main_window.baker_tab, "deleteLater") as mock_baker_delete:
            main_window.closeEvent(MagicMock())
            mock_layerify_delete.assert_called_once()
            mock_baker_delete.assert_called_once()
