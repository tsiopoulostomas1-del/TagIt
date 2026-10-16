"""
Painter for each sidebar row.

Draws: soft cover thumbnail (with rounded corners) on the left,
filename on top, "Artist · Album" underneath. Background is
painted by the view via the QSS selection/hover state, so this
delegate mostly draws text and image.

A tiny in-memory QPixmap cache keeps repeated paints fast.
"""
import os
from collections import OrderedDict

from PySide6.QtCore import Qt, QRect, QSize, QModelIndex
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

from app import tagger
from app.sidebar_model import (
    ROLE_PATH, ROLE_TAGS, ROLE_COVER_PATH
)


COVER_SIZE = 40
ROW_HEIGHT = 60
LEFT_PAD = 10
RIGHT_PAD = 10
COVER_TEXT_GAP = 12

_MEM_LIMIT = 300


def _s(v):
    if v is None:
        return ""
    return str(v).strip()


class SidebarDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix_cache = OrderedDict()

    # ------------------------------------------------------- size hint
    def sizeHint(self, option, index: QModelIndex):
        return QSize(200, ROW_HEIGHT)

    # ------------------------------------------------------- paint
    def paint(self, painter: QPainter, option, index: QModelIndex):
        # 1. Let the style draw the background (hover/selected state from QSS)
        style = option.widget.style() if option.widget else None
        if style is not None:
            opt = option
            style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter,
                                option.widget)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        rect = option.rect
        cover_rect = QRect(
            rect.left() + LEFT_PAD,
            rect.top() + (rect.height() - COVER_SIZE) // 2,
            COVER_SIZE,
            COVER_SIZE,
        )

        # 2. Cover thumbnail (or empty rounded slot)
        cover_path = index.data(ROLE_COVER_PATH) or ""
        pix = self._get_pixmap(cover_path)
        if pix is not None and not pix.isNull():
            scaled = pix.scaled(
                COVER_SIZE, COVER_SIZE,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            # Crop to square center
            cx = (scaled.width() - COVER_SIZE) // 2
            cy = (scaled.height() - COVER_SIZE) // 2
            cropped = scaled.copy(cx, cy, COVER_SIZE, COVER_SIZE)
            painter.save()
            path_clip = _rounded_path(cover_rect, 6)
            painter.setClipPath(path_clip)
            painter.drawPixmap(cover_rect.topLeft(), cropped)
            painter.restore()
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#17171f"))
            painter.drawRoundedRect(cover_rect, 6, 6)

        # 3. Text area
        text_left = cover_rect.right() + COVER_TEXT_GAP
        text_right = rect.right() - RIGHT_PAD
        text_width = max(10, text_right - text_left)
        name_rect = QRect(text_left, rect.top() + 10, text_width, 18)
        sub_rect = QRect(text_left, rect.top() + 30, text_width, 16)

        selected = bool(option.state & QStyle.State_Selected)

        # Name
        fname = QFont()
        fname.setPointSizeF(9.5)
        fname.setWeight(QFont.Medium)
        painter.setFont(fname)
        painter.setPen(QColor("#ffffff" if selected else "#e0e2e8"))
        name = os.path.basename(index.data(ROLE_PATH) or "")
        painter.drawText(
            name_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            _elide(painter, name, text_width),
        )

        # Sub-line
        tags = index.data(ROLE_TAGS) or {}
        artist = _s(tags.get(tagger.FIELD_ARTIST))
        album = _s(tags.get(tagger.FIELD_ALBUM))
        bits = []
        if artist:
            bits.append(artist)
        if album:
            bits.append(album)
        sub = " · ".join(bits)
        if sub:
            fsub = QFont()
            fsub.setPointSizeF(8.0)
            painter.setFont(fsub)
            painter.setPen(QColor("#a8b8d0" if selected else "#7a8090"))
            painter.drawText(
                sub_rect,
                Qt.AlignLeft | Qt.AlignVCenter,
                _elide(painter, sub, text_width),
            )

        painter.restore()

    # ------------------------------------------------------- helpers
    def _get_pixmap(self, path):
        if not path:
            return None
        if path in self._pix_cache:
            self._pix_cache.move_to_end(path)
            return self._pix_cache[path]
        pix = QPixmap(path)
        if pix.isNull():
            self._pix_cache[path] = None
            return None
        self._pix_cache[path] = pix
        if len(self._pix_cache) > _MEM_LIMIT:
            self._pix_cache.popitem(last=False)
        return pix


# ---------------- small utilities ----------------

def _elide(painter, text, width):
    fm = painter.fontMetrics()
    return fm.elidedText(text, Qt.ElideMiddle, width)


def _rounded_path(rect, radius):
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(),
                        radius, radius)
    return path