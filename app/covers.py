"""
Cover art pipeline — runs on a worker thread.

Given (artist, title, album), the worker:
  1. Searches MusicBrainz for a recording matching artist + title.
  2. Collects the releases attached to the top matches.
  3. Ranks them: album-title match > studio album > live > bootleg.
  4. Asks the Cover Art Archive which of those releases actually have
     front cover art uploaded.
  5. Downloads a 250px thumbnail to a local disk cache.

The worker NEVER touches Qt GUI objects. It emits the file PATH to the
downloaded image; the main thread turns that into a QPixmap in the
delegate.
"""
import os
import re
import threading
import urllib.request
import urllib.error

from PySide6.QtCore import QObject, Signal, QThread, QTimer, Qt

from app import musicbrainz as mb


CACHE_DIR = os.path.join(os.path.expanduser("~"), ".TagIt", "covers")
NO_COVER_MARKER = os.path.join(CACHE_DIR, "no-cover.txt")
TIMEOUT_SECONDS = 6
USER_AGENT = "TagIt/0.1 (https://github.com/tsiopoulostomas1-del/TagIt)"

# Cooldown between completed items, in ms.
# 100ms = ~10 items/sec max pacing, still well within MusicBrainz limits.
COOLDOWN_MS = 100
SEARCH_LIMIT = 8


# ---------------------------------------------------------------- helpers
_DISC_PATTERNS = [
    re.compile(r"\s*[\(\[]\s*disc\s*\d+\s*[\)\]]", re.IGNORECASE),
    re.compile(r"\s*[\(\[]\s*cd\s*\d+\s*[\)\]]", re.IGNORECASE),
    re.compile(r"\s*-\s*disc\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"\s*-\s*cd\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"\s+disc\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"\s+cd\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"\s+d\d+\s*$", re.IGNORECASE),
]


def _strip_disc_suffix(text: str) -> str:
    if not text:
        return ""
    t = text
    for pat in _DISC_PATTERNS:
        t = pat.sub("", t)
    return t.strip(" -_")


def _normalize(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _similar(a: str, b: str) -> bool:
    na = _normalize(_strip_disc_suffix(a))
    nb = _normalize(_strip_disc_suffix(b))
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _get_release_list(recording: dict):
    """
    MusicBrainz returns releases under 'release-list' when we don't pass
    includes=. Support both keys just in case.
    """
    if not isinstance(recording, dict):
        return []
    return recording.get("release-list") or recording.get("releases") or []


# ---------------------------------------------------------------- disk cache
def _ensure_cache_dir():
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except Exception:
        pass


def _cache_path(release_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{release_id}.jpg")


def cached_cover_path(release_id: str):
    if not release_id:
        return None
    p = _cache_path(release_id)
    if os.path.isfile(p) and os.path.getsize(p) > 0:
        return p
    return None


# ------------------------------------------------------- no-cover marker file
_no_cover_set = None
_no_cover_lock = threading.Lock()


def _load_no_cover_set():
    global _no_cover_set
    if _no_cover_set is not None:
        return _no_cover_set
    s = set()
    try:
        if os.path.isfile(NO_COVER_MARKER):
            with open(NO_COVER_MARKER, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        s.add(line)
    except Exception:
        pass
    _no_cover_set = s
    return s


def _mark_no_cover(release_id: str):
    if not release_id:
        return
    with _no_cover_lock:
        s = _load_no_cover_set()
        if release_id in s:
            return
        s.add(release_id)
        try:
            _ensure_cache_dir()
            with open(NO_COVER_MARKER, "a", encoding="utf-8") as f:
                f.write(release_id + "\n")
        except Exception:
            pass


def _is_known_no_cover(release_id: str) -> bool:
    if not release_id:
        return True
    return release_id in _load_no_cover_set()


# ------------------------------------------------------------------- checks
def release_has_cover(release_id: str) -> bool:
    """
    Ask Cover Art Archive whether this release has a front image.
    Uses the on-disk 'no cover' marker file to skip repeats.
    """
    if not release_id:
        return False
    if cached_cover_path(release_id):
        return True
    if _is_known_no_cover(release_id):
        return False

    url = f"https://coverartarchive.org/release/{release_id}/front-250"
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                _mark_no_cover(release_id)
            return ok
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            # redirect to the actual image — still a yes
            return True
        _mark_no_cover(release_id)
        return False
    except Exception:
        # network hiccup; don't mark as no-cover, we'll retry later
        return False


def download_cover(release_id: str):
    if not release_id:
        return None
    existing = cached_cover_path(release_id)
    if existing:
        return existing

    _ensure_cache_dir()
    url = f"https://coverartarchive.org/release/{release_id}/front-250"
    dest = _cache_path(release_id)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = resp.read()
    except urllib.error.HTTPError:
        _mark_no_cover(release_id)
        return None
    except Exception:
        return None
    if not data:
        return None
    try:
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
    except Exception:
        return None
    return dest


# -------------------------------------------------------------------- worker
class _CoverWorker(QObject):
    finished = Signal(str, str, str)
    _kick = Signal()

    def __init__(self):
        super().__init__()
        self._queue = []
        self._queued_paths = set()
        self._lock = threading.Lock()
        self._running = True
        self._kick.connect(self._process_next, Qt.QueuedConnection)

    def request(self, path: str, artist: str, title: str, album: str = ""):
        if not path:
            return
        with self._lock:
            if path in self._queued_paths:
                return
            self._queued_paths.add(path)
            self._queue.append((path, artist or "", title or "", album or ""))
        self._kick.emit()

    def clear_queue(self):
        with self._lock:
            self._queue.clear()
            self._queued_paths.clear()

    def stop(self):
        self._running = False

    def _process_next(self):
        if not self._running:
            return
        with self._lock:
            if not self._queue:
                return
            path, artist, title, album = self._queue.pop(0)
            self._queued_paths.discard(path)

        try:
            release_id = self._lookup_release_id(artist, title, album)
            image_path = ""
            if release_id:
                local = (cached_cover_path(release_id)
                         or download_cover(release_id))
                if local:
                    image_path = local
            self.finished.emit(path, image_path, release_id or "")
        except Exception:
            self.finished.emit(path, "", "")

        QTimer.singleShot(COOLDOWN_MS, self._kick.emit)

    # ---------------------------------------------------------- main logic
    def _lookup_release_id(self, artist, title, album=""):
        if not (artist or title):
            return ""

        results = self._search_strict(artist, title, limit=SEARCH_LIMIT)
        if not results:
            results = self._search_loose(artist, title, limit=SEARCH_LIMIT)
        if not results and album and artist:
            results = self._search_album(artist, album, limit=SEARCH_LIMIT)
        if not results:
            return ""

        candidates = []
        seen_ids = set()
        for match in results:
            for rel in _get_release_list(match):
                rid = rel.get("id")
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)

                rg = rel.get("release-group") or {}
                rg_type = (rg.get("type") or "").lower()
                secondary = [s.lower() for s in
                             (rg.get("secondary-type-list") or [])]
                is_live = ("live" in secondary) or (rg_type == "live")
                is_boot = ("bootleg" in secondary) or ("bootleg" in rg_type)
                rel_title = rel.get("title") or ""

                if album and _similar(album, rel_title):
                    priority = 0
                elif is_boot:
                    priority = 3
                elif is_live:
                    priority = 2
                elif rg_type in ("album", "ep"):
                    priority = 1
                else:
                    priority = 2

                candidates.append({
                    "id": rid,
                    "title": rel_title,
                    "priority": priority,
                })

        if not candidates:
            return ""

        candidates.sort(key=lambda c: c["priority"])

        # Fast path: if the top candidate is priority 0 (album-title match)
        # try to download it directly. If it fails, fall through to the loop.
        top = candidates[0]
        if top["priority"] == 0 and not _is_known_no_cover(top["id"]):
            local = download_cover(top["id"])
            if local:
                return top["id"]

        # Otherwise: walk down the list and HEAD-check each one
        for c in candidates:
            if release_has_cover(c["id"]):
                return c["id"]

        return ""

    # ---------------------------------------------------------- searches
    def _search_strict(self, artist, title, limit=6):
        parts = []
        if artist:
            safe = str(artist).replace('"', " ").strip()
            if safe:
                parts.append(f'artist:"{safe}"')
        if title:
            safe = str(title).replace('"', " ").strip()
            if safe:
                parts.append(f'recording:"{safe}"')
        query = " AND ".join(parts)
        if not query:
            return []
        try:
            return mb.search_recordings_raw(query, limit=limit)
        except Exception:
            return []

    def _search_loose(self, artist, title, limit=6):
        bits = []
        if title:
            bits.append(str(title).strip())
        if artist:
            bits.append(str(artist).strip())
        query = " ".join(b for b in bits if b).strip()
        if not query:
            return []
        try:
            return mb.search_recordings_raw(query, limit=limit)
        except Exception:
            return []

    def _search_album(self, artist, album, limit=6):
        clean_album = _strip_disc_suffix(album)
        if not clean_album:
            return []
        query = f'artist:"{artist}" AND release:"{clean_album}"'
        try:
            return mb.search_recordings_raw(query, limit=limit)
        except Exception:
            return []


# --------------------------------------------------------------- manager
class CoverManager(QObject):
    cover_ready = Signal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = QThread()
        self._worker = _CoverWorker()
        self._worker.moveToThread(self._thread)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def request_for_path(self, path: str, artist: str, title: str, album: str = ""):
        self._worker.request(path, artist, title, album)

    def clear_queue(self):
        try:
            self._worker.clear_queue()
        except Exception:
            pass

    def _on_finished(self, path, image_path, release_id):
        self.cover_ready.emit(path, image_path, release_id)

    def shutdown(self):
        try:
            self._worker.stop()
            self._thread.quit()
            self._thread.wait(1500)
        except Exception:
            pass