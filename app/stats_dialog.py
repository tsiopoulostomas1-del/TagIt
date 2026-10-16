"""
Library health dialog — counts tags and lets the user filter the file
list to files missing a specific field or duplicates.
"""
import os
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget
)

from app import tagger


def _s(v):
    """Safely coerce any tag value to a stripped string."""
    if v is None:
        return ""
    return str(v).strip()


class _StatRow(QFrame):
    def __init__(self, label, count, total, on_show=None, tone="warn"):
        super().__init__()
        self.setObjectName("StatRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        name = QLabel(label)
        name.setObjectName("StatRowLabel")

        value = QLabel(f"{count}")
        value.setObjectName("StatRowValue")
        if count == 0:
            value.setProperty("tone", "good")
        else:
            value.setProperty("tone", tone)

        pct = QLabel(f"({int(round(100 * count / total))}%)" if total else "(0%)")
        pct.setObjectName("StatRowPct")

        layout.addWidget(name)
        layout.addStretch(1)
        layout.addWidget(value)
        layout.addWidget(pct)

        if on_show is not None and count > 0:
            btn = QPushButton("Show")
            btn.setObjectName("GhostButton")
            btn.setMinimumHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False: on_show())
            layout.addWidget(btn)
        else:
            spacer = QLabel("")
            spacer.setFixedWidth(60)
            layout.addWidget(spacer)


class StatsDialog(QDialog):
    """
    After exec() returns Accepted, use `.chosen_filter` to read the
    filter key the user wants to apply (or None).
    """
    def __init__(self, parent, file_paths):
        super().__init__(parent)
        self.setWindowTitle("Library health")
        self.resize(560, 620)
        self.setModal(True)

        self.chosen_filter = None
        self._paths = [p for p in file_paths if p]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(14)

        heading = QLabel("Library health")
        heading.setObjectName("EditorHeading")
        outer.addWidget(heading)

        if not self._paths:
            empty = QLabel("No files loaded.")
            empty.setObjectName("Hint")
            outer.addWidget(empty)
            outer.addStretch(1)
            close_row = QHBoxLayout()
            close_row.addStretch(1)
            btn = QPushButton("Close")
            btn.setObjectName("PrimaryButton")
            btn.setMinimumWidth(120)
            btn.clicked.connect(self.reject)
            close_row.addWidget(btn)
            outer.addLayout(close_row)
            return

        counts = self._count()

        subtitle = QLabel(f"Based on {counts['total']} loaded file(s).")
        subtitle.setObjectName("Hint")
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("QWidget { background: transparent; }")
        sl = QVBoxLayout(inner)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)

        total = counts["total"]

        def row(label, key, value):
            sl.addWidget(_StatRow(
                label, value, total,
                on_show=(lambda k=key: self._choose(k))
            ))

        row("Missing Album Artist", "album_artist", counts["missing_album_artist"])
        row("Missing Artist", "artist", counts["missing_artist"])
        row("Missing Album", "album", counts["missing_album"])
        row("Missing Title", "title", counts["missing_title"])
        row("Missing Track #", "track", counts["missing_track"])
        row("Missing Year", "year", counts["missing_year"])
        row("Missing Genre", "genre", counts["missing_genre"])
        row("Duplicate (artist + title)", "duplicates", counts["duplicates"])

        sl.addSpacing(8)
        sep_label = QLabel("Format breakdown")
        sep_label.setObjectName("SectionHeader")
        sl.addWidget(sep_label)

        if counts["formats"]:
            for ext, n in sorted(counts["formats"].items(), key=lambda kv: -kv[1]):
                label = f"{ext.lstrip('.').upper()} files" if ext else "(no extension)"
                sl.addWidget(_StatRow(label, n, total, on_show=None))
        else:
            no_fmt = QLabel("—")
            no_fmt.setObjectName("Hint")
            sl.addWidget(no_fmt)

        scroll.setWidget(inner)
        outer.addWidget(scroll, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_clear = QPushButton("Clear filter")
        btn_clear.setMinimumWidth(120)
        btn_clear.clicked.connect(lambda: self._choose(None))
        btn_close = QPushButton("Close")
        btn_close.setObjectName("PrimaryButton")
        btn_close.setMinimumWidth(120)
        btn_close.clicked.connect(self.reject)
        buttons.addWidget(btn_clear)
        buttons.addWidget(btn_close)
        outer.addLayout(buttons)

    # ------------------------------------------------------------ internals
    def _choose(self, key):
        self.chosen_filter = key
        self.accept()

    def _count(self):
        c = {
            "total": len(self._paths),
            "missing_album_artist": 0,
            "missing_artist": 0,
            "missing_album": 0,
            "missing_title": 0,
            "missing_track": 0,
            "missing_year": 0,
            "missing_genre": 0,
            "duplicates": 0,
            "formats": Counter(),
        }
        seen = Counter()

        for p in self._paths:
            try:
                tags = tagger.read_tags(p) or {}
            except Exception:
                tags = {}

            if not _s(tags.get(tagger.FIELD_ALBUM_ARTIST, "")):
                c["missing_album_artist"] += 1
            if not _s(tags.get(tagger.FIELD_ARTIST, "")):
                c["missing_artist"] += 1
            if not _s(tags.get(tagger.FIELD_ALBUM, "")):
                c["missing_album"] += 1
            if not _s(tags.get(tagger.FIELD_TITLE, "")):
                c["missing_title"] += 1
            if not _s(tags.get(tagger.FIELD_TRACK, "")):
                c["missing_track"] += 1
            if not _s(tags.get(tagger.FIELD_YEAR, "")):
                c["missing_year"] += 1
            if not _s(tags.get(tagger.FIELD_GENRE, "")):
                c["missing_genre"] += 1

            key = (
                _s(tags.get(tagger.FIELD_ARTIST, "")).lower(),
                _s(tags.get(tagger.FIELD_TITLE, "")).lower(),
            )
            if key[0] and key[1]:
                seen[key] += 1

            try:
                ext = os.path.splitext(p)[1].lower()
            except Exception:
                ext = ""
            c["formats"][ext] += 1

        c["duplicates"] = sum(1 for v in seen.values() if v > 1)
        return c