
import sqlite3
from pathlib import Path


class LibraryDatabase:
    """Persistent music library, favorites, listening history, and playlists."""

    def __init__(self, database_path=None):
        project_root = Path(__file__).resolve().parent.parent
        self.database_path = Path(
            database_path or project_root / "skullcandy.db"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(
            str(self.database_path),
            timeout=10,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

        self.create_tables()

    # ---------------------------------------------------------
    # DATABASE INITIALIZATION AND MIGRATIONS
    # ---------------------------------------------------------

    def create_tables(self):
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    path TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'Unknown Title',
                    artist TEXT NOT NULL DEFAULT 'Unknown Artist',
                    album_artist TEXT NOT NULL DEFAULT 'Unknown Artist',
                    album TEXT NOT NULL DEFAULT 'Unknown Album',
                    genre TEXT NOT NULL DEFAULT '',
                    date TEXT DEFAULT '',
                    track_number TEXT DEFAULT '',
                    duration REAL NOT NULL DEFAULT 0,
                    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracks_title
                ON tracks(title)
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracks_artist
                ON tracks(artist)
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracks_album
                ON tracks(album)
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    path TEXT PRIMARY KEY,
                    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS online_favorites (
                    video_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'Unknown Title',
                    artist TEXT NOT NULL DEFAULT 'Unknown Channel',
                    url TEXT NOT NULL DEFAULT '',
                    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS listening_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL DEFAULT 'local',
                    track_key TEXT NOT NULL,
                    path TEXT DEFAULT '',
                    video_id TEXT DEFAULT '',
                    title TEXT NOT NULL DEFAULT 'Unknown Title',
                    artist TEXT NOT NULL DEFAULT '',
                    album TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    played_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_played_at
                ON listening_history(played_at DESC)
            """)

            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_history_track_key
                ON listening_history(track_key)
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (playlist_id, path),
                    FOREIGN KEY (playlist_id)
                        REFERENCES playlists(id) ON DELETE CASCADE
                )
            """)

        # Ensure older databases can use the expected history columns.
        self._ensure_column(
            "listening_history", "path", "TEXT DEFAULT ''"
        )
        self._ensure_column(
            "listening_history", "video_id", "TEXT DEFAULT ''"
        )
        self._ensure_column(
            "listening_history", "url", "TEXT NOT NULL DEFAULT ''"
        )
        self._ensure_column(
            "listening_history", "album", "TEXT NOT NULL DEFAULT ''"
        )

        # Existing history rows may contain NULL values from older code.
        with self.connection:
            self.connection.execute("""
                UPDATE listening_history
                SET url = ''
                WHERE url IS NULL
            """)
            self.connection.execute("""
                UPDATE listening_history
                SET video_id = ''
                WHERE video_id IS NULL
            """)
            self.connection.execute("""
                UPDATE listening_history
                SET path = ''
                WHERE path IS NULL
            """)
            self.connection.execute("""
                UPDATE listening_history
                SET album = ''
                WHERE album IS NULL
            """)

    def _ensure_column(self, table, column, definition):
        """Add a missing column to an existing database table."""
        columns = self.connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()

        existing = {row["name"] for row in columns}

        if column not in existing:
            with self.connection:
                self.connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )

    # ---------------------------------------------------------
    # PATH HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def normalize_path(path):
        if not path:
            return ""

        return str(Path(path).expanduser().resolve())

    # ---------------------------------------------------------
    # MUSIC LIBRARY
    # ---------------------------------------------------------

    def save_track(self, metadata):
        if not metadata or not metadata.get("path"):
            return False

        path = self.normalize_path(metadata["path"])

        try:
            duration = float(metadata.get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0

        values = (
            path,
            str(metadata.get("title") or Path(path).stem),
            str(metadata.get("artist") or "Unknown Artist"),
            str(metadata.get("album_artist") or "Unknown Artist"),
            str(metadata.get("album") or "Unknown Album"),
            str(metadata.get("genre") or ""),
            str(metadata.get("date") or ""),
            str(metadata.get("track_number") or ""),
            duration,
        )

        with self.connection:
            self.connection.execute("""
                INSERT INTO tracks (
                    path, title, artist, album_artist, album,
                    genre, date, track_number, duration
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title = excluded.title,
                    artist = excluded.artist,
                    album_artist = excluded.album_artist,
                    album = excluded.album,
                    genre = excluded.genre,
                    date = excluded.date,
                    track_number = excluded.track_number,
                    duration = excluded.duration,
                    updated_at = CURRENT_TIMESTAMP
            """, values)

        return True

    def get_all_paths(self):
        rows = self.connection.execute("""
            SELECT path FROM tracks
            ORDER BY title COLLATE NOCASE
        """).fetchall()

        return [row["path"] for row in rows]

    def get_all_tracks(self):
        rows = self.connection.execute("""
            SELECT * FROM tracks
            ORDER BY title COLLATE NOCASE
        """).fetchall()

        return [dict(row) for row in rows]

    def get_track(self, path):
        normalized = self.normalize_path(path)

        row = self.connection.execute("""
            SELECT * FROM tracks WHERE path = ?
        """, (normalized,)).fetchone()

        return dict(row) if row else None

    def get_track_count(self):
        row = self.connection.execute(
            "SELECT COUNT(*) AS total FROM tracks"
        ).fetchone()

        return row["total"]

    def remove_track(self, path):
        normalized = self.normalize_path(path)

        with self.connection:
            self.connection.execute(
                "DELETE FROM favorites WHERE path = ?",
                (normalized,),
            )
            self.connection.execute(
                "DELETE FROM playlist_tracks WHERE path = ?",
                (normalized,),
            )
            self.connection.execute(
                "DELETE FROM tracks WHERE path = ?",
                (normalized,),
            )

    def update_track_path(self, old_path, new_metadata):
        if not new_metadata or not new_metadata.get("path"):
            return False

        old_path = self.normalize_path(old_path)
        new_path = self.normalize_path(new_metadata["path"])

        if old_path == new_path:
            return self.save_track(new_metadata)

        old_track = self.get_track(old_path)

        if old_track is None:
            return self.save_track(new_metadata)

        existing_new = self.get_track(new_path)

        if existing_new:
            # Merge favorite and playlist references into the destination.
            with self.connection:
                self.connection.execute("""
                    INSERT OR IGNORE INTO favorites (path, added_at)
                    SELECT ?, added_at FROM favorites WHERE path = ?
                """, (new_path, old_path))

                self.connection.execute("""
                    INSERT OR IGNORE INTO playlist_tracks (
                        playlist_id, path, added_at
                    )
                    SELECT playlist_id, ?, added_at
                    FROM playlist_tracks
                    WHERE path = ?
                """, (new_path, old_path))

                self.connection.execute("""
                    UPDATE listening_history SET path = ?
                    WHERE path = ?
                """, (new_path, old_path))

                self.connection.execute(
                    "DELETE FROM favorites WHERE path = ?",
                    (old_path,),
                )
                self.connection.execute(
                    "DELETE FROM playlist_tracks WHERE path = ?",
                    (old_path,),
                )
                self.connection.execute(
                    "DELETE FROM tracks WHERE path = ?",
                    (old_path,),
                )

            return self.save_track(new_metadata)

        try:
            with self.connection:
                self.connection.execute(
                    "UPDATE tracks SET path = ? WHERE path = ?",
                    (new_path, old_path),
                )

                self.connection.execute("""
                    UPDATE favorites SET path = ?
                    WHERE path = ?
                """, (new_path, old_path))

                self.connection.execute("""
                    UPDATE playlist_tracks SET path = ?
                    WHERE path = ?
                """, (new_path, old_path))

                self.connection.execute("""
                    UPDATE listening_history SET path = ?
                    WHERE path = ?
                """, (new_path, old_path))

            return self.save_track(new_metadata)

        except sqlite3.IntegrityError:
            return False

    # ---------------------------------------------------------
    # FAVORITES
    # ---------------------------------------------------------

    def add_favorite(self, path):
        normalized = self.normalize_path(path)

        if not self.get_track(normalized):
            return False

        with self.connection:
            self.connection.execute("""
                INSERT OR IGNORE INTO favorites (path)
                VALUES (?)
            """, (normalized,))

        return True

    def remove_favorite(self, path):
        normalized = self.normalize_path(path)

        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM favorites WHERE path = ?",
                (normalized,),
            )

        return cursor.rowcount > 0

    def is_favorite(self, path):
        normalized = self.normalize_path(path)

        row = self.connection.execute("""
            SELECT 1 FROM favorites WHERE path = ?
        """, (normalized,)).fetchone()

        return row is not None

    def get_favorites(self):
        rows = self.connection.execute("""
            SELECT t.*
            FROM favorites f
            INNER JOIN tracks t ON t.path = f.path
            ORDER BY f.added_at DESC
        """).fetchall()

        return [dict(row) for row in rows]

    # ---------------------------------------------------------
    # ONLINE FAVORITES
    # ---------------------------------------------------------

    def add_online_favorite(self, video_id, title="Unknown Title", artist="Unknown Channel", url=""):
        video_id = str(video_id or "").strip()
        if not video_id:
            return False
        url = str(url or "").strip() or f"https://www.youtube.com/watch?v={video_id}"
        with self.connection:
            self.connection.execute("""
                INSERT INTO online_favorites (video_id, title, artist, url)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title = excluded.title,
                    artist = excluded.artist,
                    url = excluded.url
            """, (video_id, str(title or "Unknown Title"), str(artist or "Unknown Channel"), url))
        return True

    def remove_online_favorite(self, video_id):
        video_id = str(video_id or "").strip()
        if not video_id:
            return False
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM online_favorites WHERE video_id = ?", (video_id,)
            )
        return cursor.rowcount > 0

    def is_online_favorite(self, video_id):
        video_id = str(video_id or "").strip()
        if not video_id:
            return False
        row = self.connection.execute(
            "SELECT 1 FROM online_favorites WHERE video_id = ?", (video_id,)
        ).fetchone()
        return row is not None

    def get_online_favorites(self):
        rows = self.connection.execute("""
            SELECT video_id, title, artist, url, added_at
            FROM online_favorites ORDER BY added_at DESC
        """).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------
    # LISTENING HISTORY
    # ---------------------------------------------------------

    def add_history(
        self,
        source="local",
        track_key=None,
        title="Unknown Title",
        artist="",
        album="",
        path="",
        video_id="",
        url="",
    ):
        if not track_key:
            track_key = video_id or path

        if not track_key:
            return None

        normalized_path = self.normalize_path(path) if path else ""

        # Never pass None to NOT NULL history columns.
        values = (
            str(source or "local"),
            str(track_key),
            normalized_path or "",
            str(video_id or ""),
            str(title or "Unknown Title"),
            str(artist or ""),
            str(album or ""),
            str(url or ""),
        )

        with self.connection:
            cursor = self.connection.execute("""
                INSERT INTO listening_history (
                    source, track_key, path, video_id,
                    title, artist, album, url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, values)

        return cursor.lastrowid

    def get_history(self, limit=200):
        try:
            limit = max(1, min(int(limit), 2000))
        except (TypeError, ValueError):
            limit = 200

        rows = self.connection.execute("""
            SELECT *
            FROM listening_history
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [dict(row) for row in rows]

    def clear_history(self):
        with self.connection:
            self.connection.execute(
                "DELETE FROM listening_history"
            )

    # ---------------------------------------------------------
    # PLAYLISTS
    # ---------------------------------------------------------

    def create_playlist(self, name):
        name = str(name or "").strip()

        if not name:
            return False

        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO playlists (name) VALUES (?)",
                    (name,),
                )
            return True

        except sqlite3.IntegrityError:
            return False

    def get_playlists(self):
        rows = self.connection.execute("""
            SELECT
                p.id,
                p.name,
                p.created_at,
                COUNT(pt.path) AS track_count
            FROM playlists p
            LEFT JOIN playlist_tracks pt
                ON pt.playlist_id = p.id
            GROUP BY p.id, p.name, p.created_at
            ORDER BY p.name COLLATE NOCASE
        """).fetchall()

        return [dict(row) for row in rows]

    def delete_playlist(self, name):
        with self.connection:
            cursor = self.connection.execute("""
                DELETE FROM playlists
                WHERE name = ? COLLATE NOCASE
            """, (str(name or "").strip(),))

        return cursor.rowcount > 0

    def add_to_playlist(self, playlist_name, path):
        normalized = self.normalize_path(path)
        playlist_name = str(playlist_name or "").strip()

        playlist = self.connection.execute("""
            SELECT id FROM playlists
            WHERE name = ? COLLATE NOCASE
        """, (playlist_name,)).fetchone()

        if playlist is None or not self.get_track(normalized):
            return False

        with self.connection:
            self.connection.execute("""
                INSERT OR IGNORE INTO playlist_tracks (
                    playlist_id, path
                )
                VALUES (?, ?)
            """, (playlist["id"], normalized))

        return True

    def remove_from_playlist(self, playlist_name, path):
        normalized = self.normalize_path(path)
        playlist_name = str(playlist_name or "").strip()

        with self.connection:
            cursor = self.connection.execute("""
                DELETE FROM playlist_tracks
                WHERE playlist_id = (
                    SELECT id FROM playlists
                    WHERE name = ? COLLATE NOCASE
                )
                AND path = ?
            """, (playlist_name, normalized))

        return cursor.rowcount > 0

    def get_playlist_tracks(self, playlist_name):
        playlist = self.connection.execute("""
            SELECT id FROM playlists
            WHERE name = ? COLLATE NOCASE
        """, (str(playlist_name or "").strip(),)).fetchone()

        if playlist is None:
            return []

        rows = self.connection.execute("""
            SELECT pt.path
            FROM playlist_tracks pt
            INNER JOIN tracks t ON t.path = pt.path
            WHERE pt.playlist_id = ?
            ORDER BY pt.added_at, t.title COLLATE NOCASE
        """, (playlist["id"],)).fetchall()

        return [row["path"] for row in rows]

    # ---------------------------------------------------------
    # CLEANUP
    # ---------------------------------------------------------

    def close(self):
        if getattr(self, "connection", None) is not None:
            self.connection.close()
            self.connection = None
