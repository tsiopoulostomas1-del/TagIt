"""
Filename renaming dialog.

User enters a pattern like `{artist} - {title}`, sees a live preview
of every rename, and clicks "Rename" to actually do it. Conflicts and
empty results are skipped safely.
"""
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QCheckBox, QFrame,
    QMessageBox
)

from app import tagger


# Windows-illegal characters (also avoided on other platforms for portability)
ILLEGAL = r'<>:"/\\|?*'


def _sanitize(s: str) -> str:
    """Strip Windows-illegal chars and trailing dots/spaces."""
    if s is None:
        return ""
    s = str(s)
    s = re.sub(f"[{re.escape(ILLEGAL)}]", "", s)
    s = s.strip().rstrip(".")
    return s


def _zero_pad(val: str, width: int) -> str:
    """Turn '5' into '05' etc. Passes through non-numeric strings as-is."""
    try:
        n = int(str(val).split("/")[0].strip())
        return f"{n:0{width}d}"
    except Exception:
        return str(val or "")


def _render(pattern: str, tags: dict, fallback_ext: str) -> str:
    """
    Render the pattern with tags. Supports tokens like:
        {artist}  {album_artist}  {album}  {title}
        {track}  {disc}  {year}  {genre}  {ext}
        {track:02}  ->  zero-padded to 2 digits
    """
    def s(v):
        if v is None:
            return ""
        return str(v).strip()

    values = {
        "artist":       s(tags.get(tagger.FIELD_ARTIST)),
        "album_artist": s(tags.get(tagger.FIELD_ALBUM_ARTIST)),
        "album":        s(tags.get(tagger.FIELD_ALBUM)),
        "title":        s(tags.get(tagger.FIELD_TITLE)),
        "track":        s(tags.get(tagger.FIELD_TRACK)),
        "disc":         s(tags.get(tagger.FIELD_DISC)),
        "year":         s(tags.get(tagger.FIELD_YEAR)),
        "genre":        s(tags.get(tagger.FIELD_GENRE)),
        "ext":          fallback_ext.lstrip("."),
    }

    def replace(match):
        token = match.group(1)  # inside braces
        if ":" in token:
            name, _, width_s = token.partition(":")
            try:
                width = int(width_s)
            except ValueError:
                width = 0
            val = values.get(name, "")
            if name in ("track", "disc") and width > 0 and val:
                return _sanitize(_zero_pad(val, width))
            return _sanitize(val)
        val = values.get(token, "")
        return _sanitize(val)

    rendered = re.sub(r"\{([^{}]+)\}", replace, pattern)

    # Collapse leftover double spaces / dashes, trim
    rendered = re.sub(r"\s+", " ", rendered)
    rendered = rendered.strip(" -_.")

    return rendered


class RenameDialog(QDialog):
    def __init__(self, parent, files):
        """
        files: list of (path, tags_dict). Renaming only affects these.
        """
        super().__init__(parent)
        self.setWindowTitle("Rename files")
        self.resize(880, 620)
        self.setModal(True)

        self._files = files
        self._plan = []  # list of (src, dst, ok, reason)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(14)

        heading = QLabel("Rename files")
        heading.setObjectName("EditorHeading")
        outer.addWidget(heading)

        subtitle = QLabel(
            "Type a pattern using tokens like {artist}, {title}, {track:02}. "
            "Extension is preserved."
        )
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        # Pattern row
        pat_row = QHBoxLayout()
        pat_label = QLabel("Pattern:")
        pat_label.setObjectName("FieldLabel")
        pat_label.setFixedWidth(70)
        self.pattern_input = QLineEdit("{artist} - {title}")
        self.pattern_input.setObjectName("PatternInput")
        self.pattern_input.setMinimumHeight(38)
        self.pattern_input.textChanged.connect(self._recompute_preview)
        pat_row.addWidget(pat_label)
        pat_row.addWidget(self.pattern_input, stretch=1)
        outer.addLayout(pat_row)

        # Move-into-folders row
        fold_row = QHBoxLayout()
        self.move_check = QCheckBox("Also move into subfolders")
        self.move_check.setObjectName("AutoTrack")
        self.move_check.stateChanged.connect(self._on_move_toggled)
        self.folder_input = QLineEdit("{album_artist}/{album}")
        self.folder_input.setObjectName("PatternInput")
        self.folder_input.setMinimumHeight(34)
        self.folder_input.setEnabled(False)
        self.folder_input.textChanged.connect(self._recompute_preview)
        fold_row.addWidget(self.move_check)
        fold_row.addWidget(self.folder_input, stretch=1)
        outer.addLayout(fold_row)

        # Tokens hint
        tokens = QLabel(
            "Tokens:  {artist}  {album_artist}  {album}  {title}  "
            "{track}  {track:02}  {disc}  {disc:02}  {year}  {genre}  {ext}"
        )
        tokens.setObjectName("TokenHint")
        tokens.setWordWrap(True)
        outer.addWidget(tokens)

        # Preview list
        self.preview = QListWidget()
        self.preview.setObjectName("PreviewList")
        self.preview.setSelectionMode(QListWidget.NoSelection)
        outer.addWidget(self.preview, stretch=1)

        # Counts
        counts_row = QHBoxLayout()
        self.ok_label = QLabel("")
        self.ok_label.setObjectName("OkCount")
        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("ConflictCount")
        counts_row.addWidget(self.ok_label)
        counts_row.addStretch(1)
        counts_row.addWidget(self.conflict_label)
        outer.addLayout(counts_row)

        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setMinimumWidth(120)
        btn_cancel.clicked.connect(self.reject)
        self.btn_rename = QPushButton("Rename")
        self.btn_rename.setObjectName("PrimaryButton")
        self.btn_rename.setMinimumWidth(140)
        self.btn_rename.clicked.connect(self._do_rename)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(self.btn_rename)
        outer.addLayout(buttons)

        self._recompute_preview()

    # ------------------------------------------------------------ internals
    def _on_move_toggled(self):
        self.folder_input.setEnabled(self.move_check.isChecked())
        self._recompute_preview()

    def _recompute_preview(self):
        self.preview.clear()
        self._plan = []

        pattern = self.pattern_input.text() or "{title}"
        move = self.move_check.isChecked()
        folder_pattern = self.folder_input.text() or ""

        # Track target paths to detect duplicates
        seen_targets = {}

        ok = 0
        conflicts = 0

        for src, tags in self._files:
            ext = os.path.splitext(src)[1]  # includes the dot, e.g. ".mp3"
            stem = _render(pattern, tags, ext)
            if not stem:
                stem = "Unknown"

            new_name = stem + ext

            if move and folder_pattern:
                folder = _render(folder_pattern, tags, ext)
                folder_parts = [p for p in folder.split("/") if p.strip()]
                folder_parts = [p for p in folder_parts if p not in (".", "..")]
                base_dir = os.path.dirname(src)
                target_dir = os.path.join(base_dir, *folder_parts)
            else:
                target_dir = os.path.dirname(src)

            dst = os.path.join(target_dir, new_name)

            ok_flag = True
            reason = ""
            if os.path.normcase(src) == os.path.normcase(dst):
                ok_flag = False
                reason = "unchanged"
            else:
                key = os.path.normcase(dst)
                if key in seen_targets:
                    ok_flag = False
                    reason = "duplicate target"
                elif os.path.exists(dst):
                    ok_flag = False
                    reason = "target exists"
                else:
                    seen_targets[key] = src

            self._plan.append((src, dst, ok_flag, reason))

            # Preview line
            old_name = os.path.basename(src)
            if move and folder_pattern:
                rel = _render(folder_pattern, tags, ext)
                new_display = f"{rel}/{new_name}" if rel else new_name
            else:
                new_display = new_name

            if ok_flag:
                line = f"  {old_name}\n  → {new_display}"
                ok += 1
            else:
                line = f"  {old_name}\n  → {new_display}   [{reason}]"
                conflicts += 1

            item = QListWidgetItem(line)
            if not ok_flag:
                item.setForeground(Qt.red)
            self.preview.addItem(item)

        self.ok_label.setText(f"{ok} will be renamed")
        self.conflict_label.setText(
            f"{conflicts} skipped" if conflicts else ""
        )

        self.btn_rename.setEnabled(ok > 0)

    def _do_rename(self):
        renamed = 0
        errors = []
        for src, dst, ok, reason in self._plan:
            if not ok:
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(src, dst)
                renamed += 1
            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {e}")

        if errors:
            QMessageBox.warning(
                self, "Some renames failed",
                f"Renamed {renamed} file(s).\n\nErrors:\n" +
                "\n".join(errors[:10])
            )
        self._renamed_count = renamed
        self.accept()

    def renamed_count(self):
        return getattr(self, "_renamed_count", 0)