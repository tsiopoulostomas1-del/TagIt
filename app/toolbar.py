"""
Top toolbar — logo, app title, Covers checkbox, action buttons.

Emits Qt signals instead of taking a reference to MainWindow, so the
main window just connects to them.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QCheckBox
)


class Toolbar(QFrame):
    # Signals
    add_files_clicked = Signal()
    add_folder_clicked = Signal()
    remove_clicked = Signal()
    clear_clicked = Signal()
    health_clicked = Signal()
    covers_toggled = Signal(bool)

    def __init__(self, logo_pixmap: QPixmap = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Toolbar")
        self.setFixedHeight(68)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(14)

        if logo_pixmap is not None and not logo_pixmap.isNull():
            logo = QLabel()
            logo.setObjectName("ToolbarLogo")
            logo.setFixedSize(40, 40)
            logo.setScaledContents(True)
            logo.setPixmap(logo_pixmap.scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            layout.addWidget(logo)

        title = QLabel("TagIt")
        title.setObjectName("AppTitle")

        self.covers_check = QCheckBox("Covers")
        self.covers_check.setObjectName("AutoTrack")
        self.covers_check.setChecked(True)
        self.covers_check.setToolTip(
            "Fetch album cover thumbnails from the Cover Art Archive.\n"
            "Downloads happen in the background, one at a time, and are cached."
        )

        self.btn_health = QPushButton("Library health")
        self.btn_health.setMinimumHeight(36)
        self.btn_health.setToolTip("Show tag completeness and format stats (Ctrl+H)")

        self.btn_add = QPushButton("Add Files")
        self.btn_add.setObjectName("PrimaryButton")
        self.btn_add.setMinimumHeight(36)
        self.btn_add.setToolTip("Open audio files (Ctrl+O)")

        self.btn_add_folder = QPushButton("Add Folder")
        self.btn_add_folder.setMinimumHeight(36)
        self.btn_add_folder.setToolTip("Scan a folder and all its subfolders for audio files")

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setMinimumHeight(36)
        self.btn_remove.setToolTip("Remove selected files from the list (Delete)")

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setMinimumHeight(36)
        self.btn_clear.setToolTip("Clear the entire list")

        layout.addWidget(title)
        layout.addWidget(self.covers_check)
        layout.addStretch(1)
        layout.addWidget(self.btn_health)
        layout.addWidget(self.btn_remove)
        layout.addWidget(self.btn_clear)
        layout.addWidget(self.btn_add_folder)
        layout.addWidget(self.btn_add)

        # Wire internal buttons to our own signals
        self.btn_add.clicked.connect(self.add_files_clicked.emit)
        self.btn_add_folder.clicked.connect(self.add_folder_clicked.emit)
        self.btn_remove.clicked.connect(self.remove_clicked.emit)
        self.btn_clear.clicked.connect(self.clear_clicked.emit)
        self.btn_health.clicked.connect(self.health_clicked.emit)
        self.covers_check.toggled.connect(self.covers_toggled.emit)

    def is_covers_enabled(self) -> bool:
        return self.covers_check.isChecked()