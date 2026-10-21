#!/usr/bin/env python3
"""Patch SkullCandy's three existing UI/database files for online likes.

Run from the project root:
    python3 fix_online_favorites.py
The script makes .bak copies before changing files.
"""
from pathlib import Path
import re
import shutil
import sys

ROOT = Path.cwd()
FILES = {
    "main": ROOT / "ui" / "main_window.py",
    "persistent": ROOT / "ui" / "persistent_main_window.py",
    "database": ROOT / "ui" / "library_database.py",
}

for key, path in FILES.items():
    if not path.is_file():
        sys.exit(f"Missing required file: {path}\nRun this script from your project root.")


def replace_method(source, method_name, replacement, next_method_name):
    pattern = re.compile(
        rf"(?ms)^    def {re.escape(method_name)}\(.*?(?=^    def {re.escape(next_method_name)}\()"
    )
    updated, count = pattern.subn(lambda match: replacement.rstrip() + "\n\n", source, count=1)
    if count != 1:
        raise RuntimeError(f"Could not safely locate method {method_name}()")
    return updated


def insert_once(source, marker, addition, description):
    if marker in source:
        if addition.strip() in source:
            return source
        source = source.replace(marker, addition + marker, 1)
        return source
    raise RuntimeError(f"Could not find insertion point for {description}")

# ---------------------------- main_window.py ----------------------------
main = FILES["main"].read_text(encoding="utf-8")
main_replacement = '''    def toggle_current_like(self):
        """Toggle the current local or online track's persistent favorite."""
        source = getattr(self, "current_source", "local")

        if source == "online":
            handler = getattr(self, "toggle_favorite", None)
            if callable(handler):
                handler()
            self.refresh_like_button()
            return

        if not (0 <= self.current_track_index < len(self.music_files)):
            self.refresh_like_button()
            return

        path = str(Path(self.music_files[self.current_track_index]).resolve())
        handler = getattr(self, "toggle_favorite", None)
        if callable(handler):
            try:
                handler(path)
            except TypeError:
                handler()
        else:
            # Standalone MainWindow fallback; PersistentMainWindow uses SQLite.
            liked = getattr(self, "_liked_paths", set())
            if path in liked:
                liked.remove(path)
            else:
                liked.add(path)
            self._liked_paths = liked

        self.refresh_like_button(path)

    def refresh_like_button(self, path=None):
        """Refresh the heart from SQLite when available, including YouTube."""
        if not hasattr(self, "like_button"):
            return

        source = getattr(self, "current_source", "local")
        database = getattr(self, "library_db", None)
        liked = False

        if source == "online":
            video = getattr(self, "current_online_track", None) or {}
            video_id = str(video.get("id") or "")
            if database is not None and video_id:
                try:
                    liked = database.is_online_favorite(video_id)
                except (AttributeError, Exception):
                    liked = False
        else:
            if path is None and 0 <= self.current_track_index < len(self.music_files):
                path = str(Path(self.music_files[self.current_track_index]).resolve())
            if database is not None and path:
                try:
                    liked = database.is_favorite(path)
                except Exception:
                    liked = False
            elif path:
                liked = path in getattr(self, "_liked_paths", set())

        self.like_button.setText("♥" if liked else "♡")
        self.like_button.setProperty("active", liked)
        self.like_button.setToolTip("Remove from Favorites" if liked else "Add to Favorites")
        self.like_button.style().unpolish(self.like_button)
        self.like_button.style().polish(self.like_button)'''
main = replace_method(main, "toggle_current_like", main_replacement, "update_track_info")
# Ensure the current heart is refreshed when local track metadata/UI updates.
# This insertion is harmless if the method already refreshes it.
if "self.refresh_like_button(str(Path(path).resolve()))" not in main:
    main = main.replace('''        self.track_info.setToolTip(
            f"Title: {metadata['title']}\\n"''', '''        self.refresh_like_button(str(Path(path).resolve()))
        self.track_info.setToolTip(
            f"Title: {metadata['title']}\\n"''', 1)

# ------------------------ library_database.py -------------------------
db = FILES["database"].read_text(encoding="utf-8")
favorites_table = '''            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS online_favorites (
                    video_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'Unknown Title',
                    artist TEXT NOT NULL DEFAULT 'Unknown Channel',
                    url TEXT NOT NULL DEFAULT '',
                    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

'''
if "CREATE TABLE IF NOT EXISTS online_favorites" not in db:
    db = insert_once(db, '''            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS listening_history (\n''', favorites_table, "online_favorites table")

online_methods = '''    # ---------------------------------------------------------
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

'''
if "def add_online_favorite(" not in db:
    db = insert_once(db, '''    # ---------------------------------------------------------
    # LISTENING HISTORY\n''', online_methods, "online favorite methods")

# ---------------------- persistent_main_window.py ----------------------
persistent = FILES["persistent"].read_text(encoding="utf-8")
toggle_replacement = '''    def toggle_favorite(self, path=None):
        """Toggle a local file favorite or an online YouTube favorite."""
        if getattr(self, "current_source", "local") == "online":
            video = getattr(self, "current_online_track", None) or {}
            video_id = str(video.get("id") or "").strip()
            if not video_id:
                QMessageBox.information(self, "No online track", "Play a YouTube track first.")
                return False

            if self.library_db.is_online_favorite(video_id):
                self.library_db.remove_online_favorite(video_id)
            else:
                self.library_db.add_online_favorite(
                    video_id=video_id,
                    title=video.get("title") or "Unknown Title",
                    artist=video.get("channel") or "Unknown Channel",
                    url=video.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                )

            self.update_favorite_button()
            self.refresh_like_button()
            if getattr(self, "current_page", "") == "Favorites":
                self.refresh_library_list()
            return True

        if path is None:
            path = self.get_selected_local_path()
        if not path:
            QMessageBox.information(
                self, "No local track selected",
                "Select a local track or start local playback first.",
            )
            return False

        if self.library_db.is_favorite(path):
            self.library_db.remove_favorite(path)
        else:
            metadata = dict(self.get_track_metadata(path))
            metadata["path"] = path
            self.library_db.save_track(metadata)
            self.library_db.add_favorite(path)

        self.update_favorite_button()
        self.refresh_like_button(path)
        if getattr(self, "current_page", "") == "Favorites":
            self.refresh_library_list()
        self._refresh_recommendations_if_visible()
        return True

    def update_favorite_button(self):
        if not hasattr(self, "favorite_button"):
            return
        if getattr(self, "current_source", "local") == "online":
            video = getattr(self, "current_online_track", None) or {}
            video_id = str(video.get("id") or "")
            is_favorite = bool(video_id and self.library_db.is_online_favorite(video_id))
        else:
            path = self.get_selected_local_path()
            is_favorite = bool(path and self.library_db.is_favorite(path))
        self.favorite_button.setText(
            "♥ Remove Favorite" if is_favorite else "♡ Add Favorite"
        )'''
persistent = replace_method(persistent, "toggle_favorite", toggle_replacement, "create_playlist")

# Replace _show_favorites as a whole so local and online entries coexist.
show_favorites_replacement = '''    def _show_favorites(self):
        self.library_list.clear()
        count = 0
        favorites = self.library_db.get_favorites()
        available = {
            self.normalize_path(path): index
            for index, path in enumerate(self.music_files)
        }
        shown_paths = set()

        for record in favorites:
            path = record.get("path")
            if not path:
                continue
            normalized = self.normalize_path(path)
            if not normalized or normalized in shown_paths:
                continue
            if normalized not in available:
                try:
                    if Path(path).expanduser().is_file():
                        self.add_tracks_to_queue([path], show_message=False)
                        available = {
                            self.normalize_path(item): index
                            for index, item in enumerate(self.music_files)
                        }
                except (OSError, TypeError, ValueError):
                    continue
            if normalized not in available:
                continue
            index = available[normalized]
            metadata = self.get_track_metadata(self.music_files[index])
            item = QListWidgetItem(
                f"♥  {metadata.get('title') or 'Unknown title'}\\n"
                f"     {metadata.get('artist') or 'Unknown Artist'}"
                f"  •  {metadata.get('album') or 'Unknown Album'}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(str(self.music_files[index]))
            self.library_list.addItem(item)
            shown_paths.add(normalized)
            count += 1

        for record in self.library_db.get_online_favorites():
            video_id = str(record.get("video_id") or "").strip()
            if not video_id:
                continue
            title = record.get("title") or "Unknown Title"
            artist = record.get("artist") or "Unknown Channel"
            item = QListWidgetItem(f"♥  {title}\\n     {artist}  •  YouTube")
            item.setData(Qt.ItemDataRole.UserRole, {"online_favorite": record})
            item.setToolTip(f"{title}\\n{artist}\\n{record.get('url', '')}")
            self.library_list.addItem(item)
            count += 1

        self.description.setText(f"{count} favorite track(s).")'''
persistent = replace_method(persistent, "_show_favorites", show_favorites_replacement, "_show_history")

play_selected_replacement = '''    def play_selected_library_track(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict) and "online_favorite" in data:
            record = data["online_favorite"]
            video_id = str(record.get("video_id") or "").strip()
            if not video_id or not hasattr(self, "play_online_track"):
                QMessageBox.information(
                    self, "YouTube unavailable",
                    "Online playback is not available in this window.",
                )
                return
            self.online_tracks = [{
                "id": video_id,
                "title": record.get("title") or "Unknown Title",
                "channel": record.get("artist") or "Unknown Channel",
                "description": "",
                "url": record.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            }]
            self.current_playlist_name = None
            self.show_page("Online Music")
            self.play_online_track(0)
            return
        if isinstance(data, dict) and "playlist_name" in data:
            self.open_playlist(data["playlist_name"])
            return
        if isinstance(data, dict) and "history_record" in data:
            self.play_history_record(data["history_record"])
            return
        if data is not None:
            super().play_selected_library_track(item)'''
persistent = replace_method(persistent, "play_selected_library_track", play_selected_replacement, "open_playlist")

# Keep the bottom heart in sync after switching online tracks, even though
# online_main_window.py is intentionally not modified by this three-file fix.
record_marker = '''    def record_current_playback(self):
        try:
            source = getattr(self, "current_source", "local")'''
record_replacement = '''    def record_current_playback(self):
        try:
            # The online player switches tracks independently of MainWindow.
            # Refreshing here keeps the heart state synchronized across songs.
            self.refresh_like_button()
            source = getattr(self, "current_source", "local")'''
if record_marker in persistent:
    persistent = persistent.replace(record_marker, record_replacement, 1)

# Save backups, then write patched files.
updated = {"main": main, "persistent": persistent, "database": db}
for key, source in updated.items():
    path = FILES[key]
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    path.write_text(source, encoding="utf-8")

print("Updated online favorites in:")
for path in FILES.values():
    print(f"  - {path.relative_to(ROOT)}")
print("Backups saved beside each file with a .bak extension.")
print("Next run: python3 -m py_compile ui/main_window.py ui/persistent_main_window.py ui/library_database.py ui/online_main_window.py")
