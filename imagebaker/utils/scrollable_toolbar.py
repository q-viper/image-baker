from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy


class ScrollableToolbar(QScrollArea):
    """Keep a tool row accessible without imposing its width on the window."""

    def __init__(self, toolbar):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setWidget(toolbar)

    def sizeHint(self):
        return QSize(
            0,
            self.widget().minimumSizeHint().height()
            + self.horizontalScrollBar().sizeHint().height(),
        )

    def minimumSizeHint(self):
        return self.sizeHint()
