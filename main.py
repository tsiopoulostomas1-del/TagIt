import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from app.window import MainWindow


def _resource_path(relative: str) -> str:
    """
    Resolve a path both when running from source and when running from a
    PyInstaller bundle. PyInstaller extracts bundled data into sys._MEIPASS.
    """
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TagIt")
    app.setFont(QFont("Segoe UI Variable Text", 10))

    qss_path = _resource_path(os.path.join("app", "style.qss"))
    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    except Exception as e:
        # Don't crash if the stylesheet is missing — just run unstyled
        print(f"Could not load stylesheet: {e}", flush=True)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()