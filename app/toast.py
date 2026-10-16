"""
Lightweight toast notification that slides in from the bottom-left
of the parent window and fades out after a moment. VS Code style.
"""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect


class Toast(QLabel):
    def __init__(self, parent, text: str, kind: str = "info", duration_ms: int = 2200):
        super().__init__(text, parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind)  # used by QSS via [kind="success"]

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setContentsMargins(14, 10, 14, 10)

        self.adjustSize()
        self.setFixedHeight(max(36, self.sizeHint().height()))

        # Opacity effect for fade
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        # Position: bottom-left of parent, with margin
        self._margin = 18
        self._reposition()
        self.show()
        self.raise_()

        # Fade in
        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        # Fade out
        self._fade_out = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_out.setDuration(260)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self.deleteLater)

        self._fade_in.start()
        QTimer.singleShot(duration_ms, self._fade_out.start)

    def _reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        x = self._margin
        y = parent.height() - self.height() - self._margin
        self.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()