"""
Data model for the sidebar file list.

Backed by a plain Python list of dicts. The view (QListView) asks
this model for data by row index; the delegate paints it. No widgets,
no lifetime issues, no crashes.

The model exposes helper methods (set_cover, refresh_tags, add_files,
remove_paths, sort_by, reset_all) that mutate the underlying list and
emit the correct Qt signals so the view repaints automatically.
"""
from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex

from app import tagger


# Custom roles used by the delegate to know what to paint
ROLE_PATH = Qt.UserRole + 1
ROLE_TAGS = Qt.UserRole + 2
ROLE_RELEASE = Qt.UserRole + 3
ROLE_COVER_PATH = Qt.UserRole + 4
ROLE_COVER_TRIED = Qt.UserRole + 5


class SidebarModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []   # list of dicts

    # ------------------------------------------------------------- Qt API
    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        i = index.row()
        if i < 0 or i >= len(self._rows):
            return None
        row = self._rows[i]

        if role == Qt.DisplayRole:
            return row.get("path", "")
        if role == ROLE_PATH:
            return row.get("path", "")
        if role == ROLE_TAGS:
            return row.get("tags") or {}
        if role == ROLE_RELEASE:
            return row.get("release", "")
        if role == ROLE_COVER_PATH:
            return row.get("cover_path", "")
        if role == ROLE_COVER_TRIED:
            return row.get("cover_tried", False)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    # --------------------------------------------------------- public API
    def rows(self):
        return list(self._rows)

    def path_at(self, index: QModelIndex):
        if not index.isValid():
            return ""
        i = index.row()
        if 0 <= i < len(self._rows):
            return self._rows[i].get("path", "")
        return ""

    def index_of_path(self, path):
        for i, r in enumerate(self._rows):
            if r.get("path") == path:
                return i
        return -1

    def has_path(self, path):
        return self.index_of_path(path) >= 0

    def all_paths(self):
        return {r.get("path") for r in self._rows if r.get("path")}

    def all_items_as_dicts(self):
        return [dict(r) for r in self._rows]

    def add_file(self, path, tags):
        if self.has_path(path):
            return False
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append({
            "path": path,
            "tags": tags or {},
            "release": "",
            "cover_path": "",
            "cover_tried": False,
        })
        self.endInsertRows()
        return True

    def add_files_bulk(self, entries):
        """
        entries: list of (path, tags). Skips duplicates.
        Emits one reset at the end — much faster than per-row inserts.
        """
        existing = self.all_paths()
        added = 0
        self.beginResetModel()
        for path, tags in entries:
            if not path or path in existing:
                continue
            self._rows.append({
                "path": path,
                "tags": tags or {},
                "release": "",
                "cover_path": "",
                "cover_tried": False,
            })
            existing.add(path)
            added += 1
        self.endResetModel()
        return added

    def remove_indexes(self, indexes):
        rows_to_remove = sorted({ix.row() for ix in indexes if ix.isValid()},
                                reverse=True)
        if not rows_to_remove:
            return 0
        self.beginResetModel()
        for r in rows_to_remove:
            if 0 <= r < len(self._rows):
                del self._rows[r]
        self.endResetModel()
        return len(rows_to_remove)

    def clear(self):
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def refresh_tags(self, path, tags):
        i = self.index_of_path(path)
        if i < 0:
            return
        self._rows[i]["tags"] = tags or {}
        ix = self.index(i, 0)
        self.dataChanged.emit(ix, ix, [ROLE_TAGS])

    def set_release(self, path, release_id):
        i = self.index_of_path(path)
        if i < 0:
            return
        self._rows[i]["release"] = release_id or ""
        ix = self.index(i, 0)
        self.dataChanged.emit(ix, ix, [ROLE_RELEASE])

    def set_cover(self, path, image_path):
        i = self.index_of_path(path)
        if i < 0:
            return
        if image_path:
            self._rows[i]["cover_path"] = image_path
        ix = self.index(i, 0)
        self.dataChanged.emit(ix, ix, [ROLE_COVER_PATH])

    def mark_cover_tried(self, path, tried=True):
        i = self.index_of_path(path)
        if i < 0:
            return
        self._rows[i]["cover_tried"] = bool(tried)
        ix = self.index(i, 0)
        self.dataChanged.emit(ix, ix, [ROLE_COVER_TRIED])

    def clear_covers(self):
        for r in self._rows:
            r["cover_path"] = ""
        if self._rows:
            top = self.index(0, 0)
            bottom = self.index(len(self._rows) - 1, 0)
            self.dataChanged.emit(top, bottom, [ROLE_COVER_PATH])

    def sort_rows(self, key, ascending=True):
        def sort_value(r):
            tags = r.get("tags") or {}
            if key == "name":
                import os
                return os.path.basename(r.get("path") or "").lower()
            if key == "artist":
                return (_s(tags.get(tagger.FIELD_ARTIST)) or
                        _s(tags.get(tagger.FIELD_ALBUM_ARTIST))).lower()
            if key == "album":
                return _s(tags.get(tagger.FIELD_ALBUM)).lower()
            if key == "track":
                raw = _s(tags.get(tagger.FIELD_TRACK)) or "0"
                try:
                    return int(str(raw).split("/")[0].strip() or 0)
                except Exception:
                    return 0
            if key == "date":
                import os
                try:
                    return os.path.getmtime(r.get("path") or "")
                except Exception:
                    return 0
            return ""

        self.beginResetModel()
        self._rows.sort(key=sort_value, reverse=not ascending)
        self.endResetModel()


def _s(v):
    if v is None:
        return ""
    return str(v).strip()