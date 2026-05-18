from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget


class HelpTab(QWidget):
    """Help tab with shortcuts and practical usage tips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Image Baker Help")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        help_text = QTextBrowser(self)
        help_text.setReadOnly(True)
        help_text.setOpenExternalLinks(False)
        help_text.setHtml(
            """
            <h3>General</h3>
            <ul>
              <li><b>Ctrl + H</b>: Open this Help tab.</li>
              <li><b>Esc</b>: Close the application.</li>
            </ul>

            <h3>Layerify Shortcuts</h3>
            <ul>
              <li><b>Q / W / E</b>: Point / Polygon / Rectangle mode.</li>
              <li><b>Ctrl + C / Ctrl + V</b>: Copy and paste selected annotation.</li>
              <li><b>Delete</b>: Delete selected annotation.</li>
              <li><b>Left Click</b>: Select annotation under cursor.</li>
              <li><b>Left Drag</b>: Move selected annotation.</li>
              <li><b>Double Left Click</b>: Complete polygon drawing.</li>
              <li><b>Right Click</b>: Deselect annotation. In polygon mode, remove the last point.</li>
              <li><b>Ctrl + Mouse Wheel</b>: Zoom in and out around cursor.</li>
              <li><b>Ctrl + Drag</b> on background: Pan view.</li>
              <li><b>H</b>: Toggle visibility of selected annotation.</li>
              <li><b>C</b>: Edit caption for selected annotation.</li>
              <li><b>1..9</b>: Quick-select label slots.</li>
            </ul>

            <h3>Baker Shortcuts</h3>
            <ul>
              <li><b>Ctrl + Click</b>: Multi-select layers (canvas and layer list).</li>
              <li><b>Ctrl + G</b>: Group 2 selected layers, or ungroup 1 selected grouped layer.</li>
              <li><b>Plugin Options</b>: Multi-select plugins auto-discovered from project root.</li>
              <li>Checked plugin options are used for currently selected layer(s). If none are checked, plugins are not used.</li>
              <li><b>Clear Plugins</b>: Remove plugins from selected layer(s).</li>
              <li><b>Ctrl + C / Ctrl + V</b>: Copy and paste selected layer.</li>
              <li><b>Ctrl + Z / Ctrl + Y</b>: Undo and redo on Baker edits.</li>
              <li><b>Delete</b>: Delete selected layer.</li>
              <li><b>Ctrl + S</b>: Save current state.</li>
              <li><b>Ctrl + D / Ctrl + E</b>: Toggle draw / erase mode.</li>
              <li><b>Mouse Wheel</b> in draw/erase: Change brush size.</li>
              <li><b>W / S</b>: Move selected layer up / down in stack order.</li>
              <li><b>H</b>: Toggle visibility of selected layer.</li>
              <li><b>C</b>: Edit selected layer caption.</li>
            </ul>

            <h3>Workflow Hints</h3>
            <ul>
              <li>Use Layerify for detailed annotation and Baker for composition and export.</li>
              <li>Use grouping to move related layers together, then ungroup for fine edits.</li>
              <li>Use grid mode when aligning objects, especially after zooming in.</li>
              <li>Toggle theme if contrast is low in your current lighting.</li>
            </ul>
            """
        )
        layout.addWidget(help_text)
