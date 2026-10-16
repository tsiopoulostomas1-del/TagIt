"""
In-memory undo history.

Every tag write (single Save or batch Apply) pushes an entry here.
Ctrl+Z pops the last entry and writes the "before" tags back to disk.
History is lost when the app closes — that's intentional for now.
"""
from collections import deque

from PySide6.QtCore import QObject, Signal


MAX_HISTORY = 30


class UndoEntry:
    """
    One reversible action.

    files: list of dicts, each:
        {path, before_tags, after_tags}
    label: human-readable description ("Save on foo.mp3", "Batch apply")
    """
    def __init__(self, label, files):
        self.label = label
        self.files = files


class UndoStack(QObject):
    """
    Simple LIFO stack with a max size.
    Emits `changed` whenever the stack is modified so the UI can
    enable/disable the Undo button if desired.
    """
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = deque(maxlen=MAX_HISTORY)

    def push(self, label, files):
        """
        files: list of dicts with keys path, before_tags, after_tags
        """
        # Only keep entries that actually changed something
        useful = []
        for f in files:
            if not f.get("path"):
                continue
            before = f.get("before_tags") or {}
            after = f.get("after_tags") or {}
            if before == after:
                continue
            useful.append({
                "path": f["path"],
                "before_tags": dict(before),
                "after_tags": dict(after),
            })
        if not useful:
            return
        self._stack.append(UndoEntry(label, useful))
        self.changed.emit()

    def pop(self):
        if not self._stack:
            return None
        entry = self._stack.pop()
        self.changed.emit()
        return entry

    def peek(self):
        if not self._stack:
            return None
        return self._stack[-1]

    def can_undo(self) -> bool:
        return len(self._stack) > 0

    def clear(self):
        self._stack.clear()
        self.changed.emit()