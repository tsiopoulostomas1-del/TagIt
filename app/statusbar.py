"""
Status bar — the thin bar at the bottom of the main window.

Shows a status message on the left (e.g. "Saved: file.mp3") and a
file-count on the right (e.g. "19 files · 1 selected").
"""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel


class StatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 4, 18, 4)
        layout.setSpacing(10)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("StatusText")

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("StatsLabel")

        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.stats_label)

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_stats(self, text: str):
        self.stats_label.setText(text)