"""
Sidebar panel — search box, sort button, filter banner, and the file list.

Owns its own QListView, model reference, and delegate reference. The
main window asks this panel for things like "selected paths" or "tell
the panel to re-sort", and the panel emits signals when the user does
something (search typed, sort changed, item double-clicked).
"""
import os

from PySide6.QtCore import Qt, Signal, QItemSelectionModel
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListView
)


class SidebarPanel(QFrame):
    # Signals emitted upward to MainWindow
    search_changed = Signal(str)
    sort_menu_requested = Signal()
    clear_filter_requested = Signal()
    selection_changed = Signal()
    item_double_clicked = Signal(object)  # QModelIndex

    def __init__(self, model, delegate, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(400)

        self.model = model
        self.delegate = delegate

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ----- Header row: "YOUR FILES" + Sort button -----
        header_row = QHBoxLayout()
        header = QLabel("YOUR FILES")
        header.setObjectName("SectionHeader")

        self.btn_sort = QPushButton("Sort: Name ↑")
        self.btn_sort.setObjectName("SortButton")
        self.btn_sort.setMinimumHeight(28)
        self.btn_sort.setCursor(Qt.PointingHandCursor)
        self.btn_sort.setToolTip("Sort the file list")
        self.btn_sort.clicked.connect(self.sort_menu_requested.emit)

        header_row.addWidget(header)
        header_row.addStretch(1)
        header_row.addWidget(self.btn_sort)

        # ----- Health filter banner -----
        self.filter_banner = QFrame()
        self.filter_banner.setObjectName("BatchBanner")
        fb = QHBoxLayout(self.filter_banner)
        fb.setContentsMargins(12, 8, 12, 8)
        fb.setSpacing(8)
        self.filter_label = QLabel("")
        self.filter_label.setObjectName("BatchText")
        self.btn_clear_filter = QPushButton("Clear")
        self.btn_clear_filter.setObjectName("GhostButton")
        self.btn_clear_filter.setMinimumHeight(26)
        self.btn_clear_filter.clicked.connect(self.clear_filter_requested.emit)
        fb.addWidget(self.filter_label)
        fb.addStretch(1)
        fb.addWidget(self.btn_clear_filter)
        self.filter_banner.hide()

        # ----- Search box -----
        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchBox")
        self.search_input.setPlaceholderText("Search name, artist, album, title…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(36)
        self.search_input.setToolTip("Filter the list as you type (Ctrl+F)")
        self.search_input.textChanged.connect(self.search_changed.emit)

        # ----- File list -----
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(self.delegate)
        self.view.setSelectionMode(QListView.ExtendedSelection)
        self.view.setUniformItemSizes(True)
        self.view.setSpacing(0)
        self.view.setEditTriggers(QListView.NoEditTriggers)
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.doubleClicked.connect(self.item_double_clicked.emit)
        self.view.selectionModel().selectionChanged.connect(
            lambda *_: self.selection_changed.emit()
        )

        # ----- Hint at the bottom -----
        hint = QLabel(
            "Drag & drop files here\n"
            "or click Add Files above\n\n"
            "Double-click a file to open its folder"
        )
        hint.setObjectName("Hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)

        layout.addLayout(header_row)
        layout.addWidget(self.filter_banner)
        layout.addWidget(self.search_input)
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(hint)

    # ---------------- public helpers ----------------
    def update_sort_label(self, key: str, ascending: bool):
        labels = {"name": "Name", "artist": "Artist", "album": "Album",
                  "track": "Track #", "date": "Date added"}
        arrow = "↑" if ascending else "↓"
        self.btn_sort.setText(f"Sort: {labels.get(key, 'Name')} {arrow}")

    def get_search_text(self) -> str:
        return self.search_input.text()

    def clear_search(self):
        self.search_input.clear()

    def focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def selected_indexes(self):
        return [ix for ix in self.view.selectionModel().selectedIndexes()
                if ix.isValid()]

    def selected_paths(self):
        from app.sidebar_model import ROLE_PATH
        return [ix.data(ROLE_PATH) for ix in self.selected_indexes()]

    def clear_selection(self):
        self.view.clearSelection()

    def select_all_visible(self):
        sel = self.view.selectionModel()
        sel.clearSelection()
        for i in range(self.model.rowCount()):
            if self.view.isRowHidden(i):
                continue
            ix = self.model.index(i, 0)
            sel.select(ix, QItemSelectionModel.Select)

    def set_row_hidden(self, row: int, hidden: bool):
        self.view.setRowHidden(row, hidden)

    def is_row_hidden(self, row: int) -> bool:
        return self.view.isRowHidden(row)

    def repaint(self):
        self.view.viewport().update()

    def set_filter_banner(self, text: str):
        if text:
            self.filter_label.setText(text)
            self.filter_banner.show()
        else:
            self.filter_banner.hide()