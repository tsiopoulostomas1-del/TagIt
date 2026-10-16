import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from app.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("TagIt")
    app.setFont(QFont("Segoe UI Variable Text", 10))

    here = os.path.dirname(os.path.abspath(__file__))
    qss_path = os.path.join(here, "app", "style.qss")
    with open(qss_path, "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()