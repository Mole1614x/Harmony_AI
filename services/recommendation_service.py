"""
Harmony AI - Local Music Recommendation Engine

A small, deterministic, content-based recommender that runs entirely on the
local machine (no network access, no API keys, no random selection).

How a track is scored
---------------------
* Content similarity: artist, genre and album overlap with the track that
  is currently playing.
* Personalization: a taste profile is built from favorites (strong signal)
  and listening history (recency-weighted, repeated plays count more).
* Cold start: with no favorites/history the engine falls back to similarity
  with the current track, and finally to metadata completeness with
  artist diversity (it never pretends to know the user's taste).

Track format (matches ``LibraryDatabase.tracks`` rows and
``MainWindow.get_track_metadata``)::

    {"path": "/music/song.mp3", "title": "...", "artist": "...",
     "album_artist": "...", "album": "...", "genre": "...", "duration": 123.4}

Conventions
-----------
* ``listening_history`` must be ordered OLDEST -> NEWEST (the last item is
  the most recent play). ``LibraryDatabase.get_history`` returns NEWEST
  first, so use :func:`recommend_for_library`, which handles this.
* History rows from non-local sources (e.g. YouTube) are ignored.
* Multi-artist strings ("A, B", "A & B", "A feat. B") are split so that
  tracks sharing any performer are treated as related.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
import math
import os
import re
import sqlite3
import unicodedata


_ARTIST_SPLIT = re.compile(
    r"\s*(?:;|,|&|\bfeat\.?(?=\s)|\bft\.?(?=\s)|\bfeaturing\b)\s*",
    re.IGNORECASE,
)
_GENRE_SPLIT = re.compile(r"[;,/|]")


def _as_dict(item):
    """Return a plain dict for dict-like tracks (dict, Mapping, sqlite3.Row)."""
    if isinstance(item, dict):
        return item

    if isinstance(item, Mapping):
        return dict(item)

    if isinstance(item, sqlite3.Row):
        return dict(item)

    return None


class RecommendationService:
    """Rank local tracks using metadata and user preference signals."""

    FIELD_WEIGHTS = {
        "artist": 0.40,
        "genre": 0.35,
        "album": 0.25,
    }

    UNKNOWN_VALUES = {
        "",
        "unknown",
        "unknown artist",
        "unknown album",
        "unknown genre",
        "unknown title",
        "various artists",
        "various",
        "none",
        "null",
        "n/a",
        "na",
    }

    def __init__(self, artist_weight=0.40, genre_weight=0.35,
                 album_weight=0.25):
        weights = {
            "artist": max(0.0, float(artist_weight)),
            "genre": max(0.0, float(genre_weight)),
            "album": max(0.0, float(album_weight)),
        }

        total = sum(weights.values())

        if total <= 0:
            raise ValueError("At least one metadata weight must be positive.")

        self.weights = {
            key: value / total for key, value in weights.items()
        }

    # ---------------------------------------------------------
    # Normalization and metadata extraction
    # ---------------------------------------------------------

    @staticmethod
    def _normalize(value):
        """Normalize metadata for case-insensitive comparisons."""
        if value is None:
            return ""

        value = unicodedata.normalize("NFKC", str(value))
        value = value.casefold().strip()
        value = re.sub(r"\s+", " ", value)
        return value

    @classmethod
    def _is_known(cls, value):
        return cls._normalize(value) not in cls.UNKNOWN_VALUES

    @staticmethod
    def _path(track):
        """Return a stable identifier for a track (resolved local path)."""
        if isinstance(track, (str, Path)):
            value = str(track)
        else:
            data = _as_dict(track)
            value = ""

            if data is not None:
                # The row "id" of history records is deliberately NOT used:
                # it is a database counter, not a track identifier.
                value = (
                    data.get("path")
                    or data.get("file_path")
                    or data.get("uri")
                    or ""
                )

        value = str(value).strip()

        if not value:
            return ""

        if "://" not in value:
            try:
                return str(Path(value).expanduser().resolve())
            except (OSError, RuntimeError, ValueError):
                pass

        return value

    @classmethod
    def _title(cls, track):
        data = _as_dict(track)

        if data is None:
            return ""

        for key in ("title", "name"):
            value = data.get(key)

            if cls._is_known(value):
                return cls._normalize(value)

        return ""

    @classmethod
    def _split_values(cls, raw, splitter):
        if raw is None:
            return []

        if isinstance(raw, (list, tuple, set)):
            parts = []

            for value in raw:
                parts.extend(cls._split_values(value, splitter))

            return parts

        return [
            cls._normalize(part)
            for part in splitter.split(str(raw))
            if cls._is_known(part)
        ]

    @classmethod
    def _artists(cls, track):
        """Ordered, de-duplicated tuple of normalized artist names."""
        data = _as_dict(track)

        if data is None:
            return ()

        for keys in (("artist",), ("album_artist", "albumartist")):
            found = []

            for key in keys:
                found.extend(
                    cls._split_values(data.get(key), _ARTIST_SPLIT)
                )

            if found:
                return tuple(dict.fromkeys(found))

        return ()

    @classmethod
    def _artist(cls, track):
        """Primary artist (first listed), or an empty string."""
        artists = cls._artists(track)
        return artists[0] if artists else ""

    @classmethod
    def _genres(cls, track):
        """Normalized genre labels as a set."""
        data = _as_dict(track)

        if data is None:
            return set()

        raw = data.get("genre", data.get("genres", ""))
        return set(cls._split_values(raw, _GENRE_SPLIT))

    @classmethod
    def _album(cls, track):
        data = _as_dict(track)

        if data is None:
            return ""

        value = data.get("album")
        return cls._normalize(value) if cls._is_known(value) else ""

    @classmethod
    def _metadata_value(cls, track, field):
        """Backward-compatible accessor for a single normalized field."""
        if field == "title":
            return cls._title(track)

        if field in ("artist", "album_artist"):
            return cls._artist(track)

        if field == "album":
            return cls._album(track)

        if field == "genre":
            return ", ".join(sorted(cls._genres(track)))

        return ""

    @classmethod
    def _features(cls, track):
        return {
            "artists": set(cls._artists(track)),
            "genres": cls._genres(track),
            "album": cls._album(track),
        }

    @classmethod
    def _content_key(cls, track):
        """
        Identity of the *recording*, independent of its file path.

        Used to suppress the same song imported from two different paths.
        Returns None when there is not enough metadata to be confident.
        """
        title = cls._title(track)

        if not title:
            return None

        data = _as_dict(track) or {}

        try:
            duration = int(round(float(data.get("duration") or 0)))
        except (TypeError, ValueError):
            duration = 0

        return (
            title,
            tuple(sorted(cls._artists(track))),
            cls._album(track),
            duration,
        )

    # ---------------------------------------------------------
    # Similarity
    # ---------------------------------------------------------

    @staticmethod
    def _jaccard(first, second):
        if not first or not second:
            return 0.0

        union = first | second

        if not union:
            return 0.0

        return len(first & second) / len(union)

    @staticmethod
    def _overlap(first, second):
        """Overlap coefficient: 1.0 when one set contains the other."""
        if not first or not second:
            return 0.0

        return len(first & second) / min(len(first), len(second))

    @classmethod
    def _feature_similarity(cls, first, second, weights):
        weighted_score = 0.0
        available_weight = 0.0

        if first["artists"] and second["artists"]:
            available_weight += weights["artist"]
            weighted_score += weights["artist"] * cls._overlap(
                first["artists"], second["artists"]
            )

        if first["genres"] and second["genres"]:
            available_weight += weights["genre"]
            weighted_score += weights["genre"] * cls._jaccard(
                first["genres"], second["genres"]
            )

        if first["album"] and second["album"]:
            available_weight += weights["album"]

            if first["album"] == second["album"]:
                weighted_score += weights["album"]

        if available_weight <= 0:
            return 0.0

        return weighted_score / available_weight

    @classmethod
    def similarity(cls, first, second, weights=None):
        """
        Return metadata similarity between 0.0 and 1.0.

        Missing/unknown metadata never counts as a match, and the score is
        normalized over the fields that both tracks actually have.
        """
        if _as_dict(first) is None or _as_dict(second) is None:
            return 0.0

        return cls._feature_similarity(
            cls._features(first),
            cls._features(second),
            weights or cls.FIELD_WEIGHTS,
        )

    # ---------------------------------------------------------
    # User preference profile
    # ---------------------------------------------------------

    @staticmethod
    def _build_profile(weighted_features):
        profile = {
            "artists": defaultdict(float),
            "genres": defaultdict(float),
            "albums": defaultdict(float),
        }

        for features, weight in weighted_features:
            if weight <= 0:
                continue

            for artist in features["artists"]:
                profile["artists"][artist] += weight

            for genre in features["genres"]:
                profile["genres"][genre] += weight

            if features["album"]:
                profile["albums"][features["album"]] += weight

        return profile

    @staticmethod
    def _preference_score(features, profile):
        components = []
        weights = []

        if features["artists"] and profile["artists"]:
            maximum = max(profile["artists"].values()) or 1.0
            best = max(
                profile["artists"].get(artist, 0.0)
                for artist in features["artists"]
            )
            components.append(min(1.0, best / maximum))
            weights.append(0.45)

        if features["genres"] and profile["genres"]:
            maximum = max(profile["genres"].values()) or 1.0
            score = sum(
                min(1.0, profile["genres"].get(genre, 0.0) / maximum)
                for genre in features["genres"]
            ) / len(features["genres"])
            components.append(score)
            weights.append(0.40)

        if features["album"] and profile["albums"]:
            maximum = max(profile["albums"].values()) or 1.0
            components.append(
                min(1.0, profile["albums"].get(features["album"], 0.0)
                    / maximum)
            )
            weights.append(0.15)

        if not components:
            return 0.0

        return sum(
            score * weight for score, weight in zip(components, weights)
        ) / sum(weights)

    # ---------------------------------------------------------
    # Main recommendation API
    # ---------------------------------------------------------

    def recommend(
        self,
        tracks,
        current_track=None,
        favorites=None,
        listening_history=None,
        limit=10,
        exclude_paths=None,
        allow_favorites=True,
    ):
        """
        Return ranked recommendations.

        Parameters
        ----------
        tracks:
            Candidate library tracks (dicts / rows with a ``path``).
        current_track:
            Optional currently playing track (dict or path).
        favorites:
            Iterable of track dicts or paths.
        listening_history:
            Iterable of track dicts or paths, OLDEST -> NEWEST. Repeated
            entries increase a track's influence. Non-local rows ignored.
        limit:
            Maximum number of results.
        exclude_paths:
            Paths that must never be returned.
        allow_favorites:
            Favorites are ranked after all non-favorite candidates and only
            used to fill remaining slots. Set False to never return them.

        Returns
        -------
        list[dict] of ``{"track", "score" (0..1), "reason"}``; the order is
        deterministic for identical inputs.
        """
        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError):
            limit = 10

        if limit == 0 or not tracks:
            return []

        # ----- candidate library (valid + de-duplicated) -----
        by_path = {}

        for track in tracks:
            data = _as_dict(track)

            if data is None:
                continue

            path = self._path(data)

            if path and path not in by_path:
                by_path[path] = data

        if not by_path:
            return []

        candidates = []
        seen_content = set()

        for path in sorted(by_path):
            track = by_path[path]
            content_key = self._content_key(track)

            if content_key is not None:
                if content_key in seen_content:
                    continue

                seen_content.add(content_key)

            candidates.append((path, track, content_key))

        # ----- resolve user signals against the library -----
        def resolve(item):
            data = _as_dict(item)

            if data is not None:
                source = str(data.get("source") or "local").casefold()

                if source != "local":
                    return None, None

            path = self._path(item)

            if path in by_path:
                return path, by_path[path]

            if data is not None and (
                self._artists(data) or self._album(data)
                or self._genres(data)
            ):
                return path, data

            return path or None, None

        favorite_paths = set()
        favorite_keys = set()
        favorite_features = []

        for item in list(favorites or []):
            path, track = resolve(item)

            if path:
                favorite_paths.add(path)

            if track is not None:
                favorite_features.append(self._features(track))
                key = self._content_key(track)

                if key is not None:
                    favorite_keys.add(key)

        history_entries = []  # (path, features), oldest -> newest
        history_counts = Counter()

        for item in list(listening_history or []):
            path, track = resolve(item)

            if track is None:
                continue

            history_entries.append((path or "", self._features(track)))

            if path:
                history_counts[path] += 1

        weighted = [(features, 3.0) for features in favorite_features]

        for position, (_, features) in enumerate(reversed(history_entries)):
            weighted.append((features, max(0.5, 1.5 - position * 0.05)))

        profile = self._build_profile(weighted)
        has_profile = any(
            profile[key] for key in ("artists", "genres", "albums")
        )

        # ----- current track context -----
        current_path = self._path(current_track) if current_track else ""
        current_data = _as_dict(current_track)

        if current_data is None and current_path:
            current_data = by_path.get(current_path)
        elif current_data is not None and current_path in by_path:
            current_data = by_path[current_path]

        current_features = (
            self._features(current_data) if current_data else None
        )
        current_key = (
            self._content_key(current_data) if current_data else None
        )

        excluded = {
            self._path(item)
            for item in (exclude_paths or [])
            if self._path(item)
        }

        favorite_artists = set()

        for features in favorite_features:
            favorite_artists |= features["artists"]

        references = (
            list(reversed(history_entries[-30:]))
            + [("", features) for features in favorite_features]
        )

        # ----- score -----
        ranked = []

        for path, track, content_key in candidates:
            if path == current_path or path in excluded:
                continue

            if current_key is not None and content_key == current_key:
                continue

            is_favorite = (
                path in favorite_paths
                or (content_key is not None and content_key in favorite_keys)
            )

            if is_favorite and not allow_favorites:
                continue

            features = self._features(track)

            metadata_score = (
                self._feature_similarity(
                    features, current_features, self.weights
                )
                if current_features else 0.0
            )

            if has_profile:
                profile_score = self._preference_score(features, profile)

                # A track is never compared with itself, so a replayed
                # song is lifted only by the explicit play-count bonus.
                history_scores = [
                    self._feature_similarity(
                        features, ref_features, self.weights
                    )
                    for ref_path, ref_features in references
                    if not ref_path or ref_path != path
                ]
                # With nothing else to compare against (e.g. the only played
                # track) stay neutral instead of scoring zero.
                history_score = (
                    sum(history_scores) / len(history_scores)
                    if history_scores else profile_score
                )

                # The small completeness term only separates tracks that
                # have no preference signal, so well-tagged tracks rank
                # ahead of empty ones instead of falling back to A-Z order.
                score = (
                    0.48 * profile_score
                    + 0.25 * history_score
                    + 0.25 * metadata_score
                    + 0.02 * self._library_quality(track)
                )
            elif current_features:
                score = (
                    0.85 * metadata_score
                    + 0.15 * self._library_quality(track)
                )
            else:
                score = self._library_quality(track)

            plays = history_counts.get(path, 0)

            if plays:
                score = min(1.0, score + 0.03 * math.log1p(plays))

            ranked.append({
                "track": track,
                "score": round(max(0.0, min(1.0, score)), 4),
                "reason": self._explain(
                    track, current_data, profile, has_profile,
                    is_favorite, favorite_artists,
                ),
                "_favorite": is_favorite,
                "_path": path,
            })

        ranked.sort(
            key=lambda item: (
                -item["score"],
                self._title(item["track"]),
                item["_path"],
            )
        )

        regular = [item for item in ranked if not item["_favorite"]]
        favorite_items = [item for item in ranked if item["_favorite"]]

        selected = self._select_diverse(regular, limit)

        if len(selected) < limit:
            selected.extend(
                self._select_diverse(favorite_items, limit - len(selected))
            )

        return [
            {
                "track": item["track"],
                "score": item["score"],
                "reason": item["reason"],
            }
            for item in selected[:limit]
        ]

    def _select_diverse(self, ranked, limit):
        """Take the best items without letting one artist dominate."""
        if limit <= 0:
            return []

        artist_cap = max(2, math.ceil(limit * 0.35))
        selected = []
        deferred = []
        artist_counts = Counter()

        for item in ranked:
            artist = self._artist(item["track"]) or "\0unknown"

            if artist_counts[artist] >= artist_cap:
                deferred.append(item)
                continue

            selected.append(item)
            artist_counts[artist] += 1

            if len(selected) >= limit:
                return selected

        selected.extend(deferred[:limit - len(selected)])
        return selected

    # ---------------------------------------------------------
    # Cold-start quality and explanations
    # ---------------------------------------------------------

    @classmethod
    def _library_quality(cls, track):
        """
        Metadata completeness (0..1). A deterministic cold-start fallback;
        it makes no claim about how a track sounds.
        """
        fields = (
            cls._title(track),
            cls._artist(track),
            cls._album(track),
            bool(cls._genres(track)),
        )

        return sum(bool(value) for value in fields) / len(fields)

    @classmethod
    def _explain(cls, track, current, profile, has_profile,
                 is_favorite=False, favorite_artists=frozenset()):
        if is_favorite:
            return "One of your favorites"

        artists = set(cls._artists(track))
        genres = cls._genres(track)
        album = cls._album(track)

        if current:
            if artists & set(cls._artists(current)):
                return "Similar artist"

            if genres & cls._genres(current):
                return "Matching genre"

            if album and album == cls._album(current):
                return "Same album"

        if has_profile:
            if artists & set(favorite_artists):
                return "Based on your favorite artists"

            if any(profile["artists"].get(a, 0) > 0 for a in artists):
                return "Based on artists you listen to"

            if any(profile["genres"].get(g, 0) > 0 for g in genres):
                return "Based on your listening taste"

            if album and profile["albums"].get(album, 0) > 0:
                return "From an album you enjoy"

            return "Selected from your library"

        if genres:
            return "Explore your library"

        return "Local library pick"


# -------------------------------------------------------------
# Database adapter
# -------------------------------------------------------------

def recommend_for_library(
    db,
    tracks=None,
    available_paths=None,
    current_path=None,
    limit=10,
    service=None,
    history_limit=200,
    allow_favorites=True,
):
    """
    Recommend tracks using a ``LibraryDatabase``-compatible object.

    ``tracks`` defaults to ``db.get_all_tracks()``. Candidates are limited
    to ``available_paths`` when given, otherwise to files that exist on
    disk, so stale/invalid database paths are never recommended.

    Favorites come from ``db.get_favorites()``. Listening history comes from
    ``db.get_history()`` (newest first) and is reversed here into the
    oldest -> newest order that :meth:`RecommendationService.recommend`
    expects. Non-local history (YouTube) is ignored.
    """
    service = service or RecommendationService()

    if tracks is None:
        tracks = db.get_all_tracks()

    def normalize(path):
        return RecommendationService._path(path)

    if available_paths is not None:
        allowed = {normalize(path) for path in available_paths}
        allowed.discard("")
        tracks = [
            track for track in tracks
            if normalize(track) in allowed
        ]
    else:
        tracks = [
            track for track in tracks
            if normalize(track) and os.path.isfile(normalize(track))
        ]

    favorites = db.get_favorites()

    history = [
        row for row in db.get_history(limit=history_limit)
        if str(row.get("source") or "local") == "local"
        and row.get("path")
    ]
    history.reverse()  # database order is newest first

    return service.recommend(
        tracks=tracks,
        current_track=current_path,
        favorites=favorites,
        listening_history=history,
        limit=limit,
        allow_favorites=allow_favorites,
    )
