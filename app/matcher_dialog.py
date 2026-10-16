"""
Dialog shown after a MusicBrainz search: pick a match, then pick a
release (album), then confirm.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QFrame
)

from app import musicbrainz as mb


class MatcherDialog(QDialog):
    def __init__(self, parent, artist: str, title: str, results):
        super().__init__(parent)
        self.setWindowTitle("MusicBrainz — pick a match")
        self.resize(760, 520)
        self.setModal(True)

        self._results = results
        self._chosen = None  # will hold the final dict

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        # Header
        heading = QLabel("Pick the correct match")
        heading.setObjectName("EditorHeading")
        outer.addWidget(heading)

        hint = QLabel(
            f"Searched for:  Artist = “{artist or '—'}”  ·  Title = “{title or '—'}”"
        )
        hint.setObjectName("StatusText")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # Results list
        self.list = QListWidget()
        self.list.setObjectName("ResultList")
        for r in results:
            item = QListWidgetItem(self._format_result(r))
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemSelectionChanged.connect(self._on_match_changed)
        self.list.itemDoubleClicked.connect(lambda _: self._on_accept())
        outer.addWidget(self.list, stretch=1)

        # Release row
        rel_frame = QFrame()
        rel_frame.setObjectName("BatchBanner")
        rl = QHBoxLayout(rel_frame)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(10)
        rel_label = QLabel("Release:")
        rel_label.setObjectName("FieldLabel")
        self.release_combo = QComboBox()
        self.release_combo.setMinimumWidth(460)
        rl.addWidget(rel_label)
        rl.addWidget(self.release_combo, stretch=1)
        outer.addWidget(rel_frame)

        # Info label
        self.info_label = QLabel("")
        self.info_label.setObjectName("Hint")
        self.info_label.setWordWrap(True)
        outer.addWidget(self.info_label)

        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_choose = QPushButton("Use this match")
        self.btn_choose.setObjectName("PrimaryButton")
        self.btn_choose.setMinimumWidth(160)
        self.btn_choose.clicked.connect(self._on_accept)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_choose)
        outer.addLayout(buttons)

        # Trigger first selection
        self._on_match_changed()

    # ---------------------------------------------------------------- helpers
    def _format_result(self, r):
        parts = [r.get("artist") or "?", "—", r.get("title") or "?"]
        rels = r.get("releases") or []
        if rels:
            album = rels[0].get("title") or ""
            year = mb.year_from_date(rels[0].get("date", ""))
            if album:
                parts.append(f"   ·   {album}")
            if year:
                parts.append(f" ({year})")
        return "".join(parts)

    def _on_match_changed(self):
        items = self.list.selectedItems()
        self.release_combo.clear()
        self.info_label.clear()
        if not items:
            self.btn_choose.setEnabled(False)
            return
        self.btn_choose.setEnabled(True)
        r = items[0].data(Qt.UserRole)
        rels = r.get("releases") or []
        if not rels:
            self.release_combo.addItem("(no releases found — album fields will stay empty)", None)
            return
        for rel in rels:
            year = mb.year_from_date(rel.get("date", ""))
            country = rel.get("country") or ""
            label = rel.get("title") or "(untitled release)"
            extras = []
            if year:
                extras.append(year)
            if country:
                extras.append(country)
            tracks = rel.get("track_count")
            if tracks:
                extras.append(f"{tracks} tracks")
            if extras:
                label += "  ·  " + " · ".join(str(e) for e in extras)
            self.release_combo.addItem(label, rel)

    def _on_accept(self):
        items = self.list.selectedItems()
        if not items:
            return
        match = items[0].data(Qt.UserRole)
        release = self.release_combo.currentData()
        self._chosen = {"match": match, "release": release}
        self.accept()

    def get_choice(self):
        """Call after exec() returns Accepted."""
        return self._chosen