"""
MusicBrainz lookup.

Uses musicbrainzngs (no API key needed, but must identify itself with
a proper user-agent per their policy: https://musicbrainz.org/doc/XML_Web_Service/Rate_Limiting
"""
import musicbrainzngs


APP_NAME = "TagIt"
APP_VERSION = "0.1"
APP_CONTACT = "https://github.com/tsiopoulostomas1-del/TagIt"

# Album artist values that mean "this is a compilation" — replace with track artist
_VARIOUS_TOKENS = {
    "various artists",
    "various",
    "va",
    "v/a",
    "[unknown]",
    "unknown artist",
}

# Common genres — prefer the shortest / most general match from a list
# so "hip hop" beats "west coast hip hop" or "conscious hip hop".
_GENRE_RANK = [
    "pop", "rock", "hip hop", "rap", "r&b", "rnb", "soul",
    "jazz", "blues", "country", "folk", "electronic", "dance",
    "classical", "metal", "punk", "reggae", "latin", "funk",
    "disco", "house", "techno", "ambient", "indie", "alternative",
]


def _ensure_agent():
    musicbrainzngs.set_useragent(APP_NAME, APP_VERSION, APP_CONTACT)


def search_recordings(artist: str, title: str, limit: int = 8):
    _ensure_agent()
    if not (artist or title):
        return []

    strict = _query_strict(artist, title)
    results = _run_search(strict, limit)
    if not results:
        loose = _query_loose(artist, title)
        results = _run_search(loose, limit)
    return results


def _query_strict(artist, title):
    parts = []
    if artist:
        safe = str(artist).replace('"', " ").strip()
        if safe:
            parts.append(f'artist:"{safe}"')
    if title:
        safe = str(title).replace('"', " ").strip()
        if safe:
            parts.append(f'recording:"{safe}"')
    return " AND ".join(parts)


def _query_loose(artist, title):
    bits = []
    if title:
        bits.append(str(title).strip())
    if artist:
        bits.append(str(artist).strip())
    return " ".join(b for b in bits if b).strip()


def _run_search(query, limit):
    if not query:
        return []
    try:
        result = musicbrainzngs.search_recordings(query=query, limit=limit)
    except musicbrainzngs.WebServiceError:
        return []
    except Exception:
        return []

    recordings = result.get("recording-list", []) or []
    out = []
    for rec in recordings:
        artist_name = _artist_credit(rec)
        releases = []
        for rel in rec.get("release-list", []) or []:
            releases.append({
                "id": rel.get("id", ""),
                "title": rel.get("title", ""),
                "date": rel.get("date", ""),
                "country": rel.get("country", ""),
                "track_count": rel.get("medium-track-count", ""),
                "artist_credit": _release_artist(rel),
            })
        out.append({
            "id": rec.get("id", ""),
            "title": rec.get("title", ""),
            "artist": artist_name,
            "score": int(rec.get("ext:score", 0) or 0),
            "releases": releases,
        })
    return out


def get_release_details(release_id: str, track_artist: str = ""):
    """
    Fetch full release info. Includes genres from:
      - release group tags (usually best)
      - release tags
      - artist tags (fallback when album has none)

    Also picks a "best" album artist:
      - Use the release artist, UNLESS it's a Various Artists compilation,
        in which case fall back to `track_artist` (the track's own artist).
    """
    _ensure_agent()
    try:
        result = musicbrainzngs.get_release_by_id(
            release_id,
            includes=["artists", "recordings", "release-groups",
                      "artist-credits", "tags"],
        )
    except Exception:
        return None

    rel = result.get("release", {})
    if not rel:
        return None

    # ---------- Tracks ----------
    tracks = []
    media = rel.get("medium-list", []) or []
    for disc_idx, medium in enumerate(media, start=1):
        for t in medium.get("track-list", []) or []:
            rec = t.get("recording", {}) or {}
            tracks.append({
                "disc": disc_idx,
                "position": t.get("position", ""),
                "title": t.get("title") or rec.get("title", ""),
                "recording_id": rec.get("id", ""),
                "length": rec.get("length", ""),
            })

    # ---------- Genres ----------
    genre_lists = []

    rg = rel.get("release-group", {}) or {}
    genre_lists.append(_tags_of(rg))

    genre_lists.append(_tags_of(rel))

    artist_credit = rel.get("artist-credit", []) or []
    if artist_credit and isinstance(artist_credit[0], dict):
        artist_obj = artist_credit[0].get("artist") or {}
        genre_lists.append(_tags_of(artist_obj))

    genre = _pick_best_genre(genre_lists)

    # ---------- Album artist ----------
    release_artist = ""
    if artist_credit and isinstance(artist_credit[0], dict):
        release_artist = (artist_credit[0].get("name")
                          or (artist_credit[0].get("artist") or {}).get("name", ""))

    album_artist = release_artist
    if _is_various(release_artist) and track_artist:
        album_artist = track_artist

    return {
        "id": rel.get("id", ""),
        "title": rel.get("title", ""),
        "date": rel.get("date", ""),
        "artist": release_artist,
        "album_artist": album_artist,
        "is_compilation": _is_various(release_artist),
        "track_count": len(tracks),
        "tracks": tracks,
        "genres": genre_lists,
        "genre": genre,
    }


# ---------- helpers ----------

def _tags_of(obj):
    """Return a list of tag/genre name strings from a MusicBrainz dict."""
    if not isinstance(obj, dict):
        return []
    names = []
    for tag in obj.get("tag-list", []) or []:
        name = (tag.get("name") or "").strip().lower()
        if name:
            names.append(name)
    for g in obj.get("genre-list", []) or []:
        name = (g.get("name") or "").strip().lower()
        if name and name not in names:
            names.append(name)
    return names


def _is_various(name: str) -> bool:
    if not name:
        return False
    return name.strip().lower() in _VARIOUS_TOKENS


def _pick_best_genre(genre_lists):
    """
    Given a list of tag-lists (from release-group, release, artist),
    pick the single best genre. Prefers:
      1. Exact matches from _GENRE_RANK, earliest rank wins
      2. Otherwise, the shortest tag name (fewer adjectives)
    """
    flat = []
    for lst in genre_lists:
        for g in lst:
            if g and g not in flat:
                flat.append(g)

    if not flat:
        return ""

    # Prefer known general genres
    for preferred in _GENRE_RANK:
        for g in flat:
            if g == preferred:
                return g.title()

    # Fall back to shortest
    flat.sort(key=lambda s: (len(s), s))
    return flat[0].title()


def _artist_credit(rec):
    credits = rec.get("artist-credit", []) or []
    names = []
    for c in credits:
        if isinstance(c, dict):
            name = c.get("name")
            if name:
                names.append(name)
    return " & ".join(names) if names else ""


def _release_artist(rel):
    credits = rel.get("artist-credit", []) or []
    names = []
    for c in credits:
        if isinstance(c, dict):
            name = c.get("name")
            if name:
                names.append(name)
    return " & ".join(names) if names else ""


def year_from_date(date_str: str) -> str:
    if not date_str:
        return ""
    return date_str.split("-")[0]

def search_recordings_raw(query: str, limit: int = 5):
    """
    Run a raw Lucene query against MusicBrainz and return the raw
    'recording-list' entries. Used by the cover pipeline, which needs
    release IDs that our normal search_recordings strips out.
    """
    _ensure_agent()
    if not query:
        return []
    try:
        result = musicbrainzngs.search_recordings(query=query, limit=limit)
    except musicbrainzngs.WebServiceError:
        return []
    except Exception:
        return []
    return result.get("recording-list", []) or []