"""
Pure logic for reading/writing audio tags. No UI code in here.
Uses mutagen so it works with mp3, flac, m4a, ogg, wav, aiff, dsf, wv, etc.
"""
import os

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TDRC, TCON
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.aiff import AIFF
from mutagen.dsf import DSF
from mutagen.wavpack import WavPack


# Extensions the app will load
SUPPORTED_EXTENSIONS = {
    # Lossy
    ".mp3", ".m4a", ".mp4", ".ogg", ".oga", ".opus", ".wma",
    # Lossless / studio
    ".flac", ".wav", ".aiff", ".aif", ".dsf", ".wv",
}

# Extensions that mutagen can READ but we cannot safely WRITE
READ_ONLY_EXTENSIONS = {".wma"}


# Canonical tag keys
FIELD_TITLE = "title"
FIELD_ARTIST = "artist"
FIELD_ALBUM_ARTIST = "album_artist"
FIELD_ALBUM = "album"
FIELD_TRACK = "track"
FIELD_DISC = "disc"
FIELD_YEAR = "year"
FIELD_GENRE = "genre"

ALL_FIELDS = [
    FIELD_TITLE, FIELD_ARTIST, FIELD_ALBUM_ARTIST, FIELD_ALBUM,
    FIELD_TRACK, FIELD_DISC, FIELD_YEAR, FIELD_GENRE,
]


def is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTENSIONS


def is_read_only(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in READ_ONLY_EXTENSIONS


# --------------------------------------------------------------------- READ
def read_tags(path: str) -> dict:
    """Return a dict of canonical keys. Missing tags are empty strings."""
    result = {k: "" for k in ALL_FIELDS}

    try:
        audio = MutagenFile(path)
    except Exception:
        return result

    if audio is None or audio.tags is None:
        return result

    tags = audio.tags

    # --- ID3-based (mp3, wav, aiff, dsf) ---
    if isinstance(tags, ID3):
        def get_id3(frame_id):
            frame = tags.get(frame_id)
            if not frame:
                return ""
            try:
                return str(frame.text[0]) if hasattr(frame, "text") else str(frame)
            except Exception:
                return ""
        result[FIELD_TITLE] = get_id3("TIT2")
        result[FIELD_ARTIST] = get_id3("TPE1")
        result[FIELD_ALBUM_ARTIST] = get_id3("TPE2")
        result[FIELD_ALBUM] = get_id3("TALB")
        result[FIELD_TRACK] = get_id3("TRCK")
        result[FIELD_DISC] = get_id3("TPOS")
        result[FIELD_YEAR] = get_id3("TDRC")
        result[FIELD_GENRE] = get_id3("TCON")
        return result

    # --- Vorbis-comment based (flac, ogg, opus, wv) ---
    if isinstance(audio, (FLAC, OggVorbis, WavPack)) or \
       audio.__class__.__name__ in ("OggOpus", "OggFLAC"):
        def get_vorbis(key):
            v = tags.get(key)
            if not v:
                return ""
            return str(v[0])
        result[FIELD_TITLE] = get_vorbis("title")
        result[FIELD_ARTIST] = get_vorbis("artist")
        result[FIELD_ALBUM_ARTIST] = get_vorbis("albumartist")
        result[FIELD_ALBUM] = get_vorbis("album")
        result[FIELD_TRACK] = get_vorbis("tracknumber")
        result[FIELD_DISC] = get_vorbis("discnumber")
        result[FIELD_YEAR] = get_vorbis("date")
        result[FIELD_GENRE] = get_vorbis("genre")
        return result

    # --- MP4 / M4A ---
    if isinstance(audio, MP4):
        def get_mp4(key):
            v = tags.get(key)
            if not v:
                return ""
            val = v[0]
            if isinstance(val, (list, tuple)):
                val = val[0] if val else ""
            return str(val)
        result[FIELD_TITLE] = get_mp4("\xa9nam")
        result[FIELD_ARTIST] = get_mp4("\xa9ART")
        result[FIELD_ALBUM_ARTIST] = get_mp4("aART")
        result[FIELD_ALBUM] = get_mp4("\xa9alb")
        tr = tags.get("trkn")
        if tr:
            result[FIELD_TRACK] = str(tr[0][0]) if tr[0] else ""
        dk = tags.get("disk")
        if dk:
            result[FIELD_DISC] = str(dk[0][0]) if dk[0] else ""
        result[FIELD_YEAR] = get_mp4("\xa9day")
        result[FIELD_GENRE] = get_mp4("\xa9gen")
        return result

    return result


# -------------------------------------------------------------------- WRITE
def write_tags(path: str, fields: dict) -> None:
    """
    Write tags from `fields` into the file. Empty strings remove the tag.
    Raises ValueError for unsupported or read-only formats.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in READ_ONLY_EXTENSIONS:
        raise ValueError(
            f"{ext} files are read-only — this format cannot be safely written "
            f"by the app. Convert to FLAC/MP3 to edit tags."
        )

    if not is_supported(path):
        raise ValueError(f"Unsupported format: {ext}")

    audio = MutagenFile(path, easy=False)
    if audio is None:
        raise ValueError(f"Could not open file: {path}")

    # --- ID3-based writers (mp3, wav, aiff, dsf) ---
    if ext in (".mp3", ".wav", ".aiff", ".aif", ".dsf"):
        try:
            audio.add_tags()
        except Exception:
            pass
        tags = audio.tags

        def set_or_del(frame_id, frame_class, value):
            if value:
                tags.setall(frame_id, [frame_class(encoding=3, text=[value])])
            else:
                tags.delall(frame_id)

        set_or_del("TIT2", TIT2, fields.get(FIELD_TITLE, ""))
        set_or_del("TPE1", TPE1, fields.get(FIELD_ARTIST, ""))
        set_or_del("TPE2", TPE2, fields.get(FIELD_ALBUM_ARTIST, ""))
        set_or_del("TALB", TALB, fields.get(FIELD_ALBUM, ""))
        set_or_del("TRCK", TRCK, fields.get(FIELD_TRACK, ""))
        set_or_del("TPOS", TPOS, fields.get(FIELD_DISC, ""))
        set_or_del("TDRC", TDRC, fields.get(FIELD_YEAR, ""))
        set_or_del("TCON", TCON, fields.get(FIELD_GENRE, ""))
        audio.save()
        return

    # --- Vorbis-comment writers (flac, ogg, opus, wv) ---
    if ext in (".flac", ".ogg", ".oga", ".opus", ".wv"):
        mapping = {
            "title": fields.get(FIELD_TITLE, ""),
            "artist": fields.get(FIELD_ARTIST, ""),
            "albumartist": fields.get(FIELD_ALBUM_ARTIST, ""),
            "album": fields.get(FIELD_ALBUM, ""),
            "tracknumber": fields.get(FIELD_TRACK, ""),
            "discnumber": fields.get(FIELD_DISC, ""),
            "date": fields.get(FIELD_YEAR, ""),
            "genre": fields.get(FIELD_GENRE, ""),
        }
        for key, value in mapping.items():
            if value:
                audio.tags[key] = [value]
            else:
                if key in audio.tags:
                    del audio.tags[key]
        audio.save()
        return

    # --- MP4 / M4A ---
    if ext in (".m4a", ".mp4"):
        def set_or_del(key, value):
            if value:
                audio.tags[key] = [value]
            else:
                if key in audio.tags:
                    del audio.tags[key]

        set_or_del("\xa9nam", fields.get(FIELD_TITLE, ""))
        set_or_del("\xa9ART", fields.get(FIELD_ARTIST, ""))
        set_or_del("aART", fields.get(FIELD_ALBUM_ARTIST, ""))
        set_or_del("\xa9alb", fields.get(FIELD_ALBUM, ""))
        set_or_del("\xa9day", fields.get(FIELD_YEAR, ""))
        set_or_del("\xa9gen", fields.get(FIELD_GENRE, ""))

        track = fields.get(FIELD_TRACK, "")
        if track:
            try:
                audio.tags["trkn"] = [(int(str(track).split("/")[0]), 0)]
            except ValueError:
                pass
        elif "trkn" in audio.tags:
            del audio.tags["trkn"]

        disc = fields.get(FIELD_DISC, "")
        if disc:
            try:
                audio.tags["disk"] = [(int(str(disc).split("/")[0]), 0)]
            except ValueError:
                pass
        elif "disk" in audio.tags:
            del audio.tags["disk"]

        audio.save()
        return

    raise ValueError(f"Unsupported format: {ext}")


# ------------------------------------------------------- FILENAME AUTO-PARSE
import re

# Each pattern returns a dict with keys it can extract.
# Order matters: most specific first.
_FILENAME_PATTERNS = [
    # 01 - Artist - Title
    (re.compile(r"^(?P<track>\d{1,3})\s*[-._]\s*(?P<artist>.+?)\s*[-–—]\s*(?P<title>.+)$"), True),
    # 01. Artist - Title
    (re.compile(r"^(?P<track>\d{1,3})\.\s+(?P<artist>.+?)\s*[-–—]\s*(?P<title>.+)$"), True),
    # Artist - 01 - Title
    (re.compile(r"^(?P<artist>.+?)\s*[-–—]\s*(?P<track>\d{1,3})\s*[-._]\s*(?P<title>.+)$"), True),
    # Artist - Title
    (re.compile(r"^(?P<artist>.+?)\s*[-–—]\s*(?P<title>.+)$"), True),
    # 01 - Title   (no artist)
    (re.compile(r"^(?P<track>\d{1,3})\s*[-._]\s*(?P<title>.+)$"), False),
    # 01 Title
    (re.compile(r"^(?P<track>\d{1,3})\s+(?P<title>.+)$"), False),
]


def parse_filename(path: str) -> dict:
    """
    Try to extract tags from a filename. Returns a dict with only
    the fields we're confident about (may be empty).
    """
    base = os.path.splitext(os.path.basename(path))[0].strip()
    if not base:
        return {}

    for pattern, expect_artist in _FILENAME_PATTERNS:
        m = pattern.match(base)
        if not m:
            continue

        result = {}
        groups = m.groupdict()

        if "track" in groups and groups["track"]:
            try:
                result[FIELD_TRACK] = str(int(groups["track"]))
            except ValueError:
                pass

        if "artist" in groups and groups["artist"]:
            result[FIELD_ARTIST] = groups["artist"].strip()

        if "title" in groups and groups["title"]:
            title = groups["title"].strip()
            # Strip trailing " [something]" or " (something)" that's likely junk
            # but keep parens that look like part of the title
            result[FIELD_TITLE] = title

        # Require at least artist or title to consider it a match,
        # and if pattern declares expect_artist=True, require artist
        if expect_artist and FIELD_ARTIST not in result:
            continue
        if FIELD_TITLE not in result and FIELD_ARTIST not in result:
            continue

        return result

    return {}