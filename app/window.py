import os
import time
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer, QModelIndex, QItemSelectionModel
from PySide6.QtGui import QIcon, QPixmap, QKeySequence, QShortcut, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListView, QLineEdit, QFormLayout,
    QFrame, QSizePolicy, QFileDialog, QMessageBox, QCheckBox, QMenu
)

from app.undo import UndoStack
from app import tagger
from app import musicbrainz as mb
from app.toast import Toast
from app.player import PlaybackBar
from app.matcher_dialog import MatcherDialog
from app.stats_dialog import StatsDialog
from app.rename_dialog import RenameDialog
from app.covers import CoverManager
from app.sidebar_model import (
    SidebarModel, ROLE_PATH, ROLE_TAGS, ROLE_RELEASE, ROLE_COVER_TRIED
)
from app.sidebar_delegate import SidebarDelegate
from app.statusbar import StatusBar
from app.toolbar import Toolbar
from app.sidebar_panel import SidebarPanel


def _s(v):
    if v is None:
        return ""
    return str(v).strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TagIt")
        self.resize(1180, 780)
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)

        self._logo_pixmap = self._load_logo()
        self.current_file = None
        self._suppress_editor_events = False
        self._sort_key = "name"
        self._sort_ascending = True
        self._health_filter = None

        # Sidebar model + delegate
        self.model = SidebarModel(self)
        self.delegate = SidebarDelegate(self)

        # Undo history (in-memory, session-only)
        self.undo_stack = UndoStack(self)

        # Covers
        self.covers = CoverManager(self)
        self.covers.cover_ready.connect(self._on_cover_ready)

        self._cover_timer = QTimer(self)
        self._cover_timer.setSingleShot(True)
        self._cover_timer.setInterval(500)
        self._cover_timer.timeout.connect(self._fetch_cover_for_current_now)

        self._fetch_covers_enabled = True
        self._loading_bulk = False

        # Debounced selection handler
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(40)
        self._selection_timer.timeout.connect(self._apply_selection_change)

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_statusbar())

        self._connect_signals()
        self._install_shortcuts()
        self._update_editor_enabled(False)
        self._update_batch_banner()
        self._refresh_stats()

    def closeEvent(self, event):
        try:
            self.covers.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- logo ----------------
    def _load_logo(self):
        base = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(base)
        for name in ("logo.png", "logo.jpg", "logo.jpeg"):
            p = os.path.join(root, name)
            if os.path.isfile(p):
                pix = QPixmap(p)
                if not pix.isNull():
                    self.setWindowIcon(QIcon(pix))
                    return pix
        return None

    # ---------------- toolbar ----------------
    def _build_toolbar(self):
        self.toolbar = Toolbar(logo_pixmap=self._logo_pixmap)
        return self.toolbar

    # ---------------- body ----------------
    def _build_body(self):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar(), stretch=0)
        layout.addWidget(self._build_editor(), stretch=1)
        return container

    def _build_sidebar(self):
        self.sidebar_panel = SidebarPanel(self.model, self.delegate)
        self.sidebar_panel.search_changed.connect(self._apply_filter)
        self.sidebar_panel.sort_menu_requested.connect(self._show_sort_menu)
        self.sidebar_panel.clear_filter_requested.connect(self._clear_health_filter)
        self.sidebar_panel.selection_changed.connect(self.on_selection_changed)
        self.sidebar_panel.item_double_clicked.connect(self.on_view_double_clicked)
        return self.sidebar_panel

    def _build_editor(self):
        panel = QFrame()
        panel.setObjectName("Editor")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(32, 24, 32, 20)
        outer.setSpacing(16)

        self.batch_banner = QFrame()
        self.batch_banner.setObjectName("BatchBanner")
        bl = QHBoxLayout(self.batch_banner)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(8)
        self.batch_label = QLabel("")
        self.batch_label.setObjectName("BatchText")
        bl.addWidget(self.batch_label)
        bl.addStretch(1)
        self.batch_banner.hide()

        heading_row = QHBoxLayout()
        heading = QLabel("Metadata")
        heading.setObjectName("EditorHeading")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)

        self.btn_rename = QPushButton("Rename files")
        self.btn_rename.setObjectName("GhostButton")
        self.btn_rename.setMinimumHeight(34)
        self.btn_rename.setCursor(Qt.PointingHandCursor)
        self.btn_rename.setToolTip("Rename files on disk using a pattern (Ctrl+R)")
        self.btn_rename.clicked.connect(self.on_rename_files)
        self.btn_rename.hide()
        heading_row.addWidget(self.btn_rename)

        self.btn_mb = QPushButton("Look up online")
        self.btn_mb.setObjectName("GhostButton")
        self.btn_mb.setMinimumHeight(34)
        self.btn_mb.setCursor(Qt.PointingHandCursor)
        self.btn_mb.setToolTip("Search MusicBrainz for this artist/title (Ctrl+M)")
        self.btn_mb.clicked.connect(self.on_lookup_online)
        self.btn_mb.hide()
        heading_row.addWidget(self.btn_mb)

        self.btn_autofill = QPushButton("Auto-fill from filename")
        self.btn_autofill.setObjectName("GhostButton")
        self.btn_autofill.setMinimumHeight(34)
        self.btn_autofill.setCursor(Qt.PointingHandCursor)
        self.btn_autofill.setToolTip("Guess tags from the file name (Ctrl+T)")
        self.btn_autofill.clicked.connect(self.on_autofill_from_filename)
        self.btn_autofill.hide()
        heading_row.addWidget(self.btn_autofill)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)
        form.setContentsMargins(0, 0, 0, 0)

        self.field_title = QLineEdit()
        self.field_artist = QLineEdit()
        self.field_album_artist = QLineEdit()
        self.field_album = QLineEdit()
        self.field_track = QLineEdit()
        self.field_disc = QLineEdit()
        self.field_year = QLineEdit()
        self.field_genre = QLineEdit()

        for f in (self.field_title, self.field_artist, self.field_album_artist,
                  self.field_album, self.field_track, self.field_disc,
                  self.field_year, self.field_genre):
            f.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            f.setMinimumHeight(38)
            f.setMaximumWidth(780)
            f.setClearButtonEnabled(True)

        form.addRow(self._label("Title"), self.field_title)
        form.addRow(self._label("Artist"), self.field_artist)
        form.addRow(self._label("Album Artist"), self.field_album_artist)
        form.addRow(self._label("Album"), self.field_album)
        form.addRow(self._label("Track #"), self.field_track)
        form.addRow(self._label("Disc #"), self.field_disc)
        form.addRow(self._label("Year"), self.field_year)
        form.addRow(self._label("Genre"), self.field_genre)

        self.auto_track_check = QCheckBox("Auto-number tracks across selection (1, 2, 3, ...)")
        self.auto_track_check.setObjectName("AutoTrack")
        self.auto_track_check.hide()

        self.player = PlaybackBar()
        self.player.hide()

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_apply = QPushButton("Apply to Selection")
        self.btn_apply.setObjectName("PrimaryButton")
        self.btn_apply.setMinimumWidth(190)
        self.btn_apply.setMinimumHeight(40)
        self.btn_apply.setToolTip("Apply the filled-in fields to every selected file (Ctrl+S)")
        self.btn_apply.hide()
        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.setMinimumWidth(140)
        self.btn_save.setMinimumHeight(40)
        self.btn_save.setToolTip("Save the tags to this file (Ctrl+S)")
        actions.addWidget(self.btn_apply)
        actions.addWidget(self.btn_save)

        outer.addWidget(self.batch_banner)
        outer.addLayout(heading_row)
        outer.addWidget(form_widget)
        outer.addWidget(self.auto_track_check)
        outer.addStretch(1)
        outer.addWidget(self.player)
        outer.addLayout(actions)
        return panel

    def _label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        lbl.setFixedWidth(110)
        return lbl

    def _build_statusbar(self):
        self.statusbar = StatusBar()
        return self.statusbar

    # ---------------- signals ----------------
    def _connect_signals(self):
        # Toolbar
        self.toolbar.add_files_clicked.connect(self.on_add_files)
        self.toolbar.add_folder_clicked.connect(self.on_add_folder)
        self.toolbar.remove_clicked.connect(self.on_remove_selected)
        self.toolbar.clear_clicked.connect(self.on_clear)
        self.toolbar.health_clicked.connect(self.on_show_health)
        self.toolbar.covers_toggled.connect(self._on_covers_toggled)

        # Editor buttons
        self.btn_save.clicked.connect(self.on_save)
        self.btn_apply.clicked.connect(self.on_apply_to_selection)

        # Editor fields
        for f in (self.field_title, self.field_artist, self.field_album_artist,
                  self.field_album, self.field_track, self.field_disc,
                  self.field_year, self.field_genre):
            f.textEdited.connect(self.on_field_edited)

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+O"), self, self.on_add_files)
        QShortcut(QKeySequence("Ctrl+S"), self, self.on_save_or_apply)
        QShortcut(QKeySequence("Ctrl+A"), self, self.on_select_all)
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+Z"), self, self._undo_placeholder)
        QShortcut(QKeySequence("Ctrl+T"), self, self.on_autofill_from_filename)
        QShortcut(QKeySequence("Ctrl+M"), self, self.on_lookup_online)
        QShortcut(QKeySequence("Ctrl+H"), self, self.on_show_health)
        QShortcut(QKeySequence("Ctrl+R"), self, self.on_rename_files)
        QShortcut(QKeySequence("Delete"), self, self._on_delete_key)
        QShortcut(QKeySequence("Esc"), self, self._on_escape)

        self._space_sc = QShortcut(QKeySequence("Space"), self)
        self._space_sc.setContext(Qt.WindowShortcut)
        self._space_sc.activated.connect(self._on_space)

    def _on_space(self):
        if isinstance(self.focusWidget(), QLineEdit):
            return
        if self.player.isVisible():
            self.player.toggle_play()

    def _on_delete_key(self):
        if isinstance(self.focusWidget(), QLineEdit):
            return
        self.on_remove_selected()

    def _focus_search(self):
        self.sidebar_panel.focus_search()

    def _on_escape(self):
        if self.sidebar_panel.get_search_text():
            self.sidebar_panel.clear_search()
        elif self._health_filter is not None:
            self._clear_health_filter()
        else:
            self.sidebar_panel.clear_selection()

    def _undo_placeholder(self):
        self.on_undo()

    def on_undo(self):
        entry = self.undo_stack.pop()
        if entry is None:
            self._toast("Nothing to undo", kind="info")
            return

        paths_in_undo = {f["path"] for f in entry.files}
        player_was_loading = (
            self.player.isVisible() and self.current_file in paths_in_undo
        )
        if player_was_loading:
            self.player.release()

        restored = 0
        missing = 0
        errors = []

        for f in entry.files:
            path = f["path"]
            if not os.path.exists(path):
                missing += 1
                continue
            try:
                tagger.write_tags(path, f["before_tags"])
                self.model.refresh_tags(path, f["before_tags"])
                restored += 1
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        if player_was_loading and os.path.exists(self.current_file or ""):
            self.player.load(self.current_file)

        if self.current_file and self.current_file in paths_in_undo \
                and os.path.exists(self.current_file):
            tags = tagger.read_tags(self.current_file)
            self._suppress_editor_events = True
            self.field_title.setText(_s(tags.get(tagger.FIELD_TITLE)))
            self.field_artist.setText(_s(tags.get(tagger.FIELD_ARTIST)))
            self.field_album_artist.setText(_s(tags.get(tagger.FIELD_ALBUM_ARTIST)))
            self.field_album.setText(_s(tags.get(tagger.FIELD_ALBUM)))
            self.field_track.setText(_s(tags.get(tagger.FIELD_TRACK)))
            self.field_disc.setText(_s(tags.get(tagger.FIELD_DISC)))
            self.field_year.setText(_s(tags.get(tagger.FIELD_YEAR)))
            self.field_genre.setText(_s(tags.get(tagger.FIELD_GENRE)))
            self._suppress_editor_events = False

        self.sidebar_panel.repaint()

        if self._health_filter is not None:
            self._apply_filter(self.sidebar_panel.get_search_text())

        parts = [f"Undid: {entry.label}"]
        if restored:
            parts.append(f"{restored} file{'s' if restored != 1 else ''} restored")
        if missing:
            parts.append(f"{missing} missing")
        if errors:
            parts.append(f"{len(errors)} failed")

        message = " · ".join(parts)
        self._set_status(message)
        self._toast(message, kind="success" if not errors else "error")

    # ---------------- covers ----------------
    def _on_covers_toggled(self, checked):
        self._fetch_covers_enabled = bool(checked)
        if not checked:
            self.covers.clear_queue()
            self.model.clear_covers()
            self.sidebar_panel.repaint()
            self._toast("Cover fetching off", kind="info")
        else:
            self._toast("Cover fetching on", kind="info")
            self._cover_timer.start()

    def _fetch_cover_for_current_now(self):
        if self._loading_bulk:
            return
        if not self._fetch_covers_enabled or not self.current_file:
            return
        i = self.model.index_of_path(self.current_file)
        if i < 0:
            return
        ix = self.model.index(i, 0)
        if ix.data(ROLE_COVER_TRIED):
            return
        tags = ix.data(ROLE_TAGS) or {}
        artist = _s(tags.get(tagger.FIELD_ARTIST))
        title = _s(tags.get(tagger.FIELD_TITLE))
        album = _s(tags.get(tagger.FIELD_ALBUM))
        if not (artist or title):
            parsed = tagger.parse_filename(self.current_file)
            artist = artist or parsed.get(tagger.FIELD_ARTIST, "")
            title = title or parsed.get(tagger.FIELD_TITLE, "")
        if not (artist or title):
            self.model.mark_cover_tried(self.current_file, True)
            return
        self.model.mark_cover_tried(self.current_file, True)
        self.covers.request_for_path(self.current_file, artist, title, album)

    def _on_cover_ready(self, path, image_path, release_id):
        if not image_path:
            return
        if release_id:
            self.model.set_release(path, release_id)
        self.model.set_cover(path, image_path)
        self.sidebar_panel.repaint()

    def _start_background_cover_fetch(self):
        if not self._fetch_covers_enabled:
            return
        count = 0
        for row in self.model.rows():
            path = row.get("path") or ""
            if not path or row.get("cover_tried"):
                continue
            tags = row.get("tags") or {}
            artist = _s(tags.get(tagger.FIELD_ARTIST))
            title = _s(tags.get(tagger.FIELD_TITLE))
            album = _s(tags.get(tagger.FIELD_ALBUM))
            if not (artist or title):
                parsed = tagger.parse_filename(path)
                artist = artist or parsed.get(tagger.FIELD_ARTIST, "")
                title = title or parsed.get(tagger.FIELD_TITLE, "")
            if not (artist or title):
                self.model.mark_cover_tried(path, True)
                continue
            self.model.mark_cover_tried(path, True)
            self.covers.request_for_path(path, artist, title, album)
            count += 1
        if count:
            self._toast(
                f"Fetching {count} cover{'s' if count != 1 else ''}…",
                kind="info"
            )

    # ---------------- state ----------------
    def _all_fields(self):
        return (self.field_title, self.field_artist, self.field_album_artist,
                self.field_album, self.field_track, self.field_disc,
                self.field_year, self.field_genre)

    def _update_editor_enabled(self, enabled):
        for f in self._all_fields():
            f.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)

    def _clear_editor(self):
        self._suppress_editor_events = True
        for f in self._all_fields():
            f.clear()
        self.auto_track_check.setChecked(False)
        self._suppress_editor_events = False

    def _set_status(self, text):
        self.statusbar.set_status(text)
        self._refresh_stats()

    def _refresh_stats(self):
        total = self.model.rowCount()
        selected = len(self.sidebar_panel.selected_indexes())
        parts = [f"{total} file{'s' if total != 1 else ''}"]
        if selected:
            parts.append(f"{selected} selected")
        self.statusbar.set_stats(" · ".join(parts))

    def _selected_indexes(self):
        return self.sidebar_panel.selected_indexes()

    def _selected_paths(self):
        return self.sidebar_panel.selected_paths()

    def _update_batch_banner(self):
        n = len(self._selected_indexes())
        if n > 1:
            self.batch_label.setText(
                f"Batch edit · {n} files selected · only fields you fill in will be written")
            self.batch_banner.show()
        else:
            self.batch_banner.hide()

    def _toast(self, text, kind="info"):
        Toast(self, text, kind=kind)

    # ---------------- health filter ----------------
    def on_show_health(self):
        paths = [r.get("path") for r in self.model.rows() if r.get("path")]
        dlg = StatsDialog(self, paths)
        if dlg.exec() != StatsDialog.Accepted:
            return
        self._set_health_filter(dlg.chosen_filter)

    def _set_health_filter(self, key):
        self._health_filter = key
        if key is None:
            self.sidebar_panel.set_filter_banner("")
            self._apply_filter(self.sidebar_panel.get_search_text())
            return
        labels = {
            "album_artist": "Missing Album Artist",
            "artist": "Missing Artist",
            "album": "Missing Album",
            "title": "Missing Title",
            "track": "Missing Track #",
            "year": "Missing Year",
            "genre": "Missing Genre",
            "duplicates": "Duplicates (artist + title)",
        }
        self.sidebar_panel.set_filter_banner(f"Filter: {labels.get(key, key)}")
        self._apply_filter(self.sidebar_panel.get_search_text())

    def _clear_health_filter(self):
        self._set_health_filter(None)

    def _row_matches_health(self, row):
        if self._health_filter is None:
            return True
        tags = row.get("tags") or {}
        k = self._health_filter
        if k == "album_artist":
            return not _s(tags.get(tagger.FIELD_ALBUM_ARTIST, ""))
        if k == "artist":
            return not _s(tags.get(tagger.FIELD_ARTIST, ""))
        if k == "album":
            return not _s(tags.get(tagger.FIELD_ALBUM, ""))
        if k == "title":
            return not _s(tags.get(tagger.FIELD_TITLE, ""))
        if k == "track":
            return not _s(tags.get(tagger.FIELD_TRACK, ""))
        if k == "year":
            return not _s(tags.get(tagger.FIELD_YEAR, ""))
        if k == "genre":
            return not _s(tags.get(tagger.FIELD_GENRE, ""))
        if k == "duplicates":
            mine = (
                _s(tags.get(tagger.FIELD_ARTIST, "")).lower(),
                _s(tags.get(tagger.FIELD_TITLE, "")).lower(),
            )
            if not (mine[0] and mine[1]):
                return False
            count = 0
            for r in self.model.rows():
                ot = r.get("tags") or {}
                ok = (
                    _s(ot.get(tagger.FIELD_ARTIST, "")).lower(),
                    _s(ot.get(tagger.FIELD_TITLE, "")).lower(),
                )
                if ok == mine:
                    count += 1
            return count > 1
        return True

    # ---------------- sort ----------------
    def _show_sort_menu(self):
        menu = QMenu(self)
        for key, label in [("name", "Name"), ("artist", "Artist"),
                           ("album", "Album"), ("track", "Track #"),
                           ("date", "Date added")]:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self._sort_key == key)
            action.triggered.connect(lambda _=False, k=key: self._set_sort_key(k))
            menu.addAction(action)

        menu.addSeparator()
        direction = QAction("Ascending", self)
        direction.setCheckable(True)
        direction.setChecked(self._sort_ascending)
        direction.triggered.connect(self._toggle_direction)
        menu.addAction(direction)
        btn = self.sidebar_panel.btn_sort
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _set_sort_key(self, key):
        self._sort_key = key
        self._update_sort_button_label()
        self._resort()

    def _toggle_direction(self):
        self._sort_ascending = not self._sort_ascending
        self._update_sort_button_label()
        self._resort()

    def _update_sort_button_label(self):
        self.sidebar_panel.update_sort_label(self._sort_key, self._sort_ascending)

    def _resort(self):
        selected_paths = set(self.sidebar_panel.selected_paths())
        current = self.current_file

        self.model.sort_rows(self._sort_key, self._sort_ascending)
        self._apply_filter(self.sidebar_panel.get_search_text())

        if selected_paths:
            self.sidebar_panel.clear_selection()
            sel = self.sidebar_panel.view.selectionModel()
            for i, row in enumerate(self.model.rows()):
                if row.get("path") in selected_paths:
                    ix = self.model.index(i, 0)
                    sel.select(ix, QItemSelectionModel.Select)
        if current:
            self.current_file = current

    # ---------------- filter ----------------
    def _apply_filter(self, text):
        q = (text or "").strip().lower()
        for i, row in enumerate(self.model.rows()):
            visible = self._row_matches_health(row)
            if visible and q:
                tags = row.get("tags") or {}
                haystack = " ".join([
                    os.path.basename(row.get("path") or ""),
                    _s(tags.get(tagger.FIELD_TITLE)),
                    _s(tags.get(tagger.FIELD_ARTIST)),
                    _s(tags.get(tagger.FIELD_ALBUM_ARTIST)),
                    _s(tags.get(tagger.FIELD_ALBUM)),
                    _s(tags.get(tagger.FIELD_GENRE)),
                ]).lower()
                visible = q in haystack
            self.sidebar_panel.set_row_hidden(i, not visible)
        self._refresh_stats()

    # ---------------- add files / folder ----------------
    def on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add audio files", "",
            "Audio files (*.mp3 *.flac *.m4a *.mp4 *.ogg *.oga *.opus *.wav *.wma *.aiff *.aif *.dsf *.wv);;All files (*.*)")
        if files:
            self.add_files(files)

    def on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a folder to scan"
        )
        if not folder:
            return
        self._scan_folder(folder)

    def _scan_folder(self, folder):
        found = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                full = os.path.join(root, name)
                if tagger.is_supported(full):
                    found.append(full)
        if not found:
            self._set_status("No audio files found in that folder")
            self._toast("No audio files found", kind="error")
            return
        before = self.model.rowCount()
        self.add_files(found)
        added = self.model.rowCount() - before
        self._toast(
            f"Added {added} file{'s' if added != 1 else ''} from folder scan",
            kind="success"
        )

    def add_files(self, paths):
        existing = self.model.all_paths()
        entries = []
        skipped = 0
        for path in paths:
            path = os.path.abspath(path)
            if not tagger.is_supported(path):
                skipped += 1
                continue
            if path in existing:
                continue
            tags = tagger.read_tags(path)
            entries.append((path, tags))
            existing.add(path)

        self._loading_bulk = True
        added = self.model.add_files_bulk(entries)
        self._loading_bulk = False

        if added:
            self._resort()
            self._selection_timer.start()

        self._set_status(f"Added {added} file{'s' if added != 1 else ''}"
                         + (f" · skipped {skipped} unsupported" if skipped else ""))
        self._refresh_stats()
        if added:
            self._toast(f"Added {added} file{'s' if added != 1 else ''}", kind="success")
            QTimer.singleShot(800, self._start_background_cover_fetch)

    # ---------------- remove / clear ----------------
    def on_remove_selected(self):
        indexes = self._selected_indexes()
        if not indexes:
            self._set_status("Nothing selected to remove")
            return
        n = len(indexes)
        paths = {ix.data(ROLE_PATH) for ix in indexes}
        if self.current_file in paths:
            self.player.release()
            self.player.hide()

        self._loading_bulk = True
        self.model.remove_indexes(indexes)
        self._loading_bulk = False

        self.current_file = None
        self._clear_editor()
        self._update_editor_enabled(False)
        self._update_batch_banner()
        self._set_status(f"Removed {n} file{'s' if n != 1 else ''}")
        self._refresh_stats()
        self._toast(f"Removed {n} file{'s' if n != 1 else ''}", kind="info")

    def on_clear(self):
        n = self.model.rowCount()
        self.model.clear()
        self.covers.clear_queue()
        self.current_file = None
        self._health_filter = None
        self.sidebar_panel.set_filter_banner("")
        self.player.release()
        self.player.hide()
        self._clear_editor()
        self._update_editor_enabled(False)
        self._update_batch_banner()
        self._set_status("Cleared")
        self._refresh_stats()
        if n:
            self._toast("List cleared", kind="info")

    def on_select_all(self):
        self.sidebar_panel.select_all_visible()
        self._update_batch_banner()
        self._refresh_stats()

    # ---------------- selection ----------------
    def on_selection_changed(self, *_):
        if self._loading_bulk:
            return
        self._selection_timer.start()

    def _apply_selection_change(self):
        if self._loading_bulk:
            return
        indexes = self._selected_indexes()
        self._update_batch_banner()
        self._refresh_stats()

        if len(indexes) == 0:
            self.current_file = None
            self._clear_editor()
            self._update_editor_enabled(False)
            self.btn_apply.hide()
            self.auto_track_check.hide()
            self.btn_autofill.hide()
            self.btn_mb.hide()
            self.btn_rename.hide()
            self.player.release()
            self.player.hide()
            return

        if len(indexes) == 1:
            self.btn_apply.hide()
            self.auto_track_check.hide()
            self._update_editor_enabled(True)
            self.btn_autofill.show()
            self.btn_mb.show()
            self.btn_rename.show()

            ix = indexes[0]
            path = ix.data(ROLE_PATH)
            self.current_file = path
            tags = ix.data(ROLE_TAGS) or tagger.read_tags(path)
            self.model.refresh_tags(path, tags)

            self._suppress_editor_events = True
            self.field_title.setText(_s(tags.get(tagger.FIELD_TITLE)))
            self.field_artist.setText(_s(tags.get(tagger.FIELD_ARTIST)))
            self.field_album_artist.setText(_s(tags.get(tagger.FIELD_ALBUM_ARTIST)))
            self.field_album.setText(_s(tags.get(tagger.FIELD_ALBUM)))
            self.field_track.setText(_s(tags.get(tagger.FIELD_TRACK)))
            self.field_disc.setText(_s(tags.get(tagger.FIELD_DISC)))
            self.field_year.setText(_s(tags.get(tagger.FIELD_YEAR)))
            self.field_genre.setText(_s(tags.get(tagger.FIELD_GENRE)))
            self._suppress_editor_events = False

            self.player.load(path)
            self.player.show()
            self._set_status(f"Loaded: {os.path.basename(path)}")

            if not self._loading_bulk:
                self._cover_timer.start()
            return

        self.current_file = None
        self._update_editor_enabled(True)
        self.btn_apply.show()
        self.auto_track_check.show()
        self.btn_autofill.hide()
        self.btn_mb.hide()
        self.btn_rename.show()
        self.player.release()
        self.player.hide()

        self._suppress_editor_events = True
        for f in self._all_fields():
            f.clear()
        self._suppress_editor_events = False
        self._set_status(f"{len(indexes)} files selected — fill fields to batch edit")

    def on_view_double_clicked(self, index):
        if not index.isValid():
            return
        path = index.data(ROLE_PATH)
        if not path:
            return
        folder = os.path.dirname(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            self._toast(f"Could not open folder: {e}", kind="error")

    # ---------------- auto-fill ----------------
    def on_autofill_from_filename(self):
        if not self.current_file:
            self._set_status("Select a single file first")
            self._toast("Select a single file first", kind="error")
            return

        parsed = tagger.parse_filename(self.current_file)
        if not parsed:
            self._set_status("Could not detect tags from filename")
            self._toast("Couldn't detect a pattern in the filename", kind="error")
            return

        field_map = {
            tagger.FIELD_TITLE: self.field_title,
            tagger.FIELD_ARTIST: self.field_artist,
            tagger.FIELD_ALBUM_ARTIST: self.field_album_artist,
            tagger.FIELD_ALBUM: self.field_album,
            tagger.FIELD_TRACK: self.field_track,
            tagger.FIELD_DISC: self.field_disc,
            tagger.FIELD_YEAR: self.field_year,
            tagger.FIELD_GENRE: self.field_genre,
        }
        filled = []
        self._suppress_editor_events = True
        for key, value in parsed.items():
            widget = field_map.get(key)
            if widget is not None and not widget.text().strip():
                widget.setText(str(value))
                filled.append(key)
        self._suppress_editor_events = False

        if not filled:
            self._set_status("No empty fields to fill")
            self._toast("Fields already have values — nothing to fill", kind="info")
            return

        self._set_status(f"Auto-filled: {', '.join(filled)}")
        self._toast(f"Filled {len(filled)} field(s) — review and Save", kind="success")

    # ---------------- rename files ----------------
    def on_rename_files(self):
        indexes = self._selected_indexes()
        if not indexes:
            if self.model.rowCount() == 0:
                self._set_status("No files loaded")
                self._toast("Nothing to rename", kind="error")
                return
            reply = QMessageBox.question(
                self, "Rename all loaded files?",
                f"No files are selected. Rename all {self.model.rowCount()} loaded files?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            indexes = [self.model.index(i, 0) for i in range(self.model.rowCount())]

        files = []
        for ix in indexes:
            path = ix.data(ROLE_PATH)
            if not path:
                continue
            tags = ix.data(ROLE_TAGS) or tagger.read_tags(path)
            files.append((path, tags))

        if not files:
            return

        dlg = RenameDialog(self, files)
        if dlg.exec() != RenameDialog.Accepted:
            return

        renamed = dlg.renamed_count()
        if renamed == 0:
            self._set_status("Nothing renamed")
            return

        self._reload_after_rename(indexes)
        self._set_status(f"Renamed {renamed} file{'s' if renamed != 1 else ''}")
        self._toast(f"Renamed {renamed} file{'s' if renamed != 1 else ''}", kind="success")

    def _reload_after_rename(self, indexes):
        original_paths = [ix.data(ROLE_PATH) for ix in indexes if ix.data(ROLE_PATH)]

        gone = []
        for i, row in enumerate(self.model.rows()):
            p = row.get("path") or ""
            if p and not os.path.exists(p):
                gone.append(self.model.index(i, 0))
        if gone:
            self._loading_bulk = True
            self.model.remove_indexes(gone)
            self._loading_bulk = False

        to_add = []
        existing = self.model.all_paths()
        for p in original_paths:
            folder = os.path.dirname(p)
            if not os.path.isdir(folder):
                continue
            try:
                for name in os.listdir(folder):
                    full = os.path.join(folder, name)
                    if os.path.isfile(full) and tagger.is_supported(full):
                        if full not in existing:
                            to_add.append(full)
            except Exception:
                pass
        if to_add:
            self.add_files(to_add)

    # ---------------- MusicBrainz lookup ----------------
    def on_lookup_online(self):
        if not self.current_file:
            self._set_status("Select a single file first")
            self._toast("Select a single file first", kind="error")
            return

        artist = self.field_artist.text().strip()
        title = self.field_title.text().strip()

        if not artist or not title:
            guessed = tagger.parse_filename(self.current_file)
            artist = artist or guessed.get(tagger.FIELD_ARTIST, "")
            title = title or guessed.get(tagger.FIELD_TITLE, "")

        if not artist and not title:
            self._set_status("Need at least an artist or title to look up")
            self._toast("Fill Artist or Title first, or Auto-fill from filename", kind="error")
            return

        self._set_status(f"Searching MusicBrainz for “{artist} — {title}”…")
        self.btn_mb.setEnabled(False)
        try:
            results = mb.search_recordings(artist, title, limit=8)
        finally:
            self.btn_mb.setEnabled(True)

        if not results:
            self._set_status("No MusicBrainz matches found")
            self._toast("No matches found on MusicBrainz", kind="error")
            return

        dlg = MatcherDialog(self, artist, title, results)
        if dlg.exec() != MatcherDialog.Accepted:
            self._set_status("Lookup cancelled")
            return

        choice = dlg.get_choice()
        if not choice:
            return
        self._apply_mb_choice(choice)

    def _apply_mb_choice(self, choice):
        match = choice.get("match") or {}
        release = choice.get("release")

        release_details = None
        if release and release.get("id"):
            release_details = mb.get_release_details(
                release["id"],
                track_artist=(match.get("artist") or
                              self.field_artist.text().strip())
            )

        artist_name = match.get("artist") or ""
        title_name = match.get("title") or ""
        album_name = ""
        album_artist = ""
        year = ""
        track_no = ""
        disc_no = ""
        genre = ""

        if release_details:
            album_name = release_details.get("title") or ""
            album_artist = (release_details.get("album_artist")
                            or release_details.get("artist")
                            or artist_name)
            year = mb.year_from_date(release_details.get("date", ""))
            if release_details.get("genre"):
                genre = release_details["genre"]
            tracks = release_details.get("tracks") or []
            if tracks:
                found = None
                for t in tracks:
                    if (t.get("title") or "").lower() == (title_name or "").lower():
                        found = t
                        break
                if not found:
                    for t in tracks:
                        if (title_name or "").lower() in (t.get("title") or "").lower():
                            found = t
                            break
                if not found and len(tracks) >= 1:
                    found = tracks[0]
                if found:
                    track_no = str(found.get("position") or "")
                    disc_no = str(found.get("disc") or "1")
        elif release:
            album_name = release.get("title") or ""
            album_artist = release.get("artist_credit") or artist_name
            year = mb.year_from_date(release.get("date", ""))

        if release and release.get("id") and self.current_file:
            self.model.set_release(self.current_file, release["id"])
            if self._fetch_covers_enabled:
                self.covers.request_for_path(
                    self.current_file,
                    artist_name or self.field_artist.text().strip(),
                    title_name or self.field_title.text().strip(),
                    album_name or self.field_album.text().strip(),
                )

        field_map = {
            tagger.FIELD_TITLE: (self.field_title, title_name),
            tagger.FIELD_ARTIST: (self.field_artist, artist_name),
            tagger.FIELD_ALBUM_ARTIST: (self.field_album_artist,
                                        album_artist or artist_name or ""),
            tagger.FIELD_ALBUM: (self.field_album, album_name),
            tagger.FIELD_TRACK: (self.field_track, track_no),
            tagger.FIELD_DISC: (self.field_disc, disc_no),
            tagger.FIELD_YEAR: (self.field_year, year),
            tagger.FIELD_GENRE: (self.field_genre, genre),
        }

        filled = []
        self._suppress_editor_events = True
        for key, (widget, value) in field_map.items():
            if not value:
                continue
            if widget.text().strip():
                continue
            widget.setText(str(value))
            filled.append(key)
        self._suppress_editor_events = False

        if filled:
            self._set_status(f"MusicBrainz filled: {', '.join(filled)}")
            self._toast(f"Filled {len(filled)} field(s) — review and Save", kind="success")
        else:
            self._set_status("Nothing to fill — all fields already set")
            self._toast("All fields already have values", kind="info")

    # ---------------- edit ----------------
    def on_field_edited(self, _text):
        if self._suppress_editor_events:
            return
        self._set_status("Unsaved changes")

    def _collect_fields(self):
        return {
            tagger.FIELD_TITLE: self.field_title.text().strip(),
            tagger.FIELD_ARTIST: self.field_artist.text().strip(),
            tagger.FIELD_ALBUM_ARTIST: self.field_album_artist.text().strip(),
            tagger.FIELD_ALBUM: self.field_album.text().strip(),
            tagger.FIELD_TRACK: self.field_track.text().strip(),
            tagger.FIELD_DISC: self.field_disc.text().strip(),
            tagger.FIELD_YEAR: self.field_year.text().strip(),
            tagger.FIELD_GENRE: self.field_genre.text().strip(),
        }

    # ---------------- save ----------------
    def on_save_or_apply(self):
        if self.btn_apply.isVisible() and len(self._selected_indexes()) > 1:
            self.on_apply_to_selection()
        else:
            self.on_save()

    def _write_with_retry(self, path, fields, was_loaded_in_player):
        last_err = None
        for _ in range(4):
            try:
                tagger.write_tags(path, fields)
                return True, None
            except PermissionError as e:
                last_err = e
                if was_loaded_in_player:
                    self.player.release()
                time.sleep(0.2)
            except Exception as e:
                return False, e
        return False, last_err

    def on_save(self):
        if not self.current_file:
            self._set_status("No file selected")
            self._toast("No file selected", kind="error")
            return

        if tagger.is_read_only(self.current_file):
            ext = os.path.splitext(self.current_file)[1].lower()
            QMessageBox.warning(
                self, "Read-only format",
                f"{ext} files can't be safely written by this app.\n\n"
                f"Convert to FLAC or MP3 to edit tags.")
            self._set_status("Read-only format")
            self._toast("This format is read-only", kind="error")
            return

        fields = self._collect_fields()
        path = self.current_file

        before_tags = tagger.read_tags(path)

        was_loaded_in_player = self.player.isVisible()
        if was_loaded_in_player:
            self.player.release()

        ok, err = self._write_with_retry(path, fields, was_loaded_in_player)

        if not ok:
            if was_loaded_in_player:
                self.player.load(path)
            if isinstance(err, PermissionError):
                QMessageBox.warning(
                    self, "Save failed — file is locked",
                    "Windows wouldn't let us write to this file.\n\n"
                    "Most common causes:\n"
                    "  • The file is open in another app\n"
                    "  • The folder is OneDrive/Dropbox synced\n"
                    "  • Windows Defender is scanning the file\n"
                    "  • The file is marked read-only\n\n"
                    "Close other apps and try again.")
                self._set_status("Save failed — file locked")
                self._toast("File is locked", kind="error")
            else:
                QMessageBox.critical(self, "Save failed",
                                     f"Could not write tags:\n\n{err}")
                self._set_status("Save failed")
                self._toast("Save failed", kind="error")
            return

        if was_loaded_in_player:
            self.player.load(path)

        self.model.refresh_tags(path, dict(fields))
        self.sidebar_panel.repaint()

        # Record undo history
        self.undo_stack.push(
            f"Save on {os.path.basename(path)}",
            [{
                "path": path,
                "before_tags": before_tags,
                "after_tags": dict(fields),
            }],
        )

        self._set_status(f"Saved: {os.path.basename(path)}")
        self._toast("Saved successfully", kind="success")

        if self._health_filter is not None:
            self._apply_filter(self.sidebar_panel.get_search_text())

    # ---------------- batch apply ----------------
    def on_apply_to_selection(self):
        indexes = self._selected_indexes()
        if len(indexes) < 2:
            self._set_status("Select 2+ files for batch apply")
            return

        entered = self._collect_fields()
        fields_to_apply = {k: v for k, v in entered.items() if v != ""}
        auto_track = self.auto_track_check.isChecked()

        if not fields_to_apply and not auto_track:
            self._set_status("Nothing to apply — fill at least one field")
            self._toast("Nothing to apply", kind="error")
            return

        playing_path = None
        if self.player.isVisible() and self.current_file:
            playing_path = self.current_file
            self.player.release()

        errors = []
        written = 0
        skipped_readonly = 0

        sorted_indexes = sorted(indexes, key=lambda ix: ix.row())
        undo_batch = []

        for i, ix in enumerate(sorted_indexes):
            path = ix.data(ROLE_PATH)
            if not path:
                continue
            if tagger.is_read_only(path):
                skipped_readonly += 1
                continue

            merged = None
            wrote = False
            last_err = None
            existing_before = None
            for _ in range(4):
                try:
                    existing_before = tagger.read_tags(path)
                    merged = dict(existing_before)
                    merged.update(fields_to_apply)
                    if auto_track:
                        merged[tagger.FIELD_TRACK] = str(i + 1)
                    tagger.write_tags(path, merged)
                    wrote = True
                    break
                except PermissionError as e:
                    last_err = e
                    time.sleep(0.2)
                except Exception as e:
                    last_err = e
                    break

            if wrote:
                self.model.refresh_tags(path, merged)
                undo_batch.append({
                    "path": path,
                    "before_tags": existing_before or {},
                    "after_tags": dict(merged),
                })
                written += 1
            else:
                if isinstance(last_err, PermissionError):
                    errors.append(f"{os.path.basename(path)}: file is locked")
                else:
                    errors.append(f"{os.path.basename(path)}: {last_err}")

        if playing_path:
            self.player.load(playing_path)

        self.sidebar_panel.repaint()

        if undo_batch:
            self.undo_stack.push(
                f"Batch apply to {len(undo_batch)} file"
                f"{'s' if len(undo_batch) != 1 else ''}",
                undo_batch,
            )

        msg = f"Applied to {written} file{'s' if written != 1 else ''}"
        if skipped_readonly:
            msg += f" · skipped {skipped_readonly} read-only"
        if errors:
            QMessageBox.warning(
                self, "Batch apply — some failed",
                f"Applied to {written}/{len(indexes)} files.\n\nErrors:\n" +
                "\n".join(errors[:10]))
            self._set_status(msg + f" · {len(errors)} failed")
            self._toast(f"{written} applied, {len(errors)} failed", kind="error")
        else:
            self._set_status(msg)
            self._toast(msg, kind="success")

        if self._health_filter is not None:
            self._apply_filter(self.sidebar_panel.get_search_text())

    # ---------------- drag/drop ----------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if not p:
                continue
            if os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for name in files:
                        full = os.path.join(root, name)
                        if tagger.is_supported(full):
                            paths.append(full)
            else:
                paths.append(p)
        if paths:
            self.add_files(paths)
        event.acceptProposedAction()