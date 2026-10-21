from pathlib import Path
import os
import re
import unicodedata

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QWidget,
)

from services.recommendation_service import (
    RecommendationService,
    recommend_for_library,
)
from ui.main_window import MainWindow
from ui.library_database import LibraryDatabase

try:
    import vlc
except (ImportError, OSError):
    vlc = None


class PersistentMainWindow(MainWindow):
    """SQLite-backed library with favorites, history, and playlists."""

    RECOMMENDATION_LIMIT = 12

    def __init__(self, database_path=None, music_folder=None):
        self.library_db = LibraryDatabase(database_path)
        self.music_folder = (
            Path(music_folder).expanduser()
            if music_folder is not None
            else Path(__file__).resolve().parent.parent / "music"
        )
        self.recommendation_service = RecommendationService()
        self._last_history_key = None
        self.current_playlist_name = None
        self._extended_ui_ready = False

        super().__init__()

        self.deduplicate_music_queue()

        self.setup_extended_navigation()
        self.setup_library_actions()
        self._extended_ui_ready = True

        self.history_timer = QTimer(self)
        self.history_timer.setInterval(1000)
        self.history_timer.timeout.connect(self.record_current_playback)
        self.history_timer.start()

        self.refresh_library_list()

    # =========================================================
    # Path normalization and duplicate prevention
    # =========================================================
    @staticmethod
    def normalize_path(path):
        """Return a canonical comparison key for an audio file path."""
        try:
            if not path:
                return ""

            expanded = os.path.expanduser(os.fspath(path))
            resolved = os.path.realpath(expanded)

            return os.path.normcase(resolved).casefold()
        except (TypeError, ValueError, OSError):
            return ""

    def deduplicate_music_queue(self):
        """
        Remove duplicate references to the same physical file.

        Preserve queue order and remap the current track and collection
        indices. Distinct files with identical metadata are retained.
        """
        tracks = getattr(self, "music_files", None)

        if not isinstance(tracks, list):
            return

        old_tracks = list(tracks)
        old_current_index = getattr(self, "current_track_index", -1)
        old_collection = getattr(self, "collection_tracks", None)

        unique_tracks = []
        seen = {}
        old_to_new = {}

        for old_index, path in enumerate(old_tracks):
            key = self.normalize_path(path)

            # Keep an unusable path rather than silently discarding an
            # entry whose path cannot be normalized.
            if not key:
                key = f"__invalid_path_{old_index}"

            if key in seen:
                old_to_new[old_index] = seen[key]
                continue

            new_index = len(unique_tracks)
            seen[key] = new_index
            old_to_new[old_index] = new_index
            unique_tracks.append(path)

        changed = len(unique_tracks) != len(old_tracks)

        if changed:
            self.music_files = unique_tracks

            if 0 <= old_current_index < len(old_tracks):
                self.current_track_index = old_to_new.get(
                    old_current_index, -1
                )
            elif not unique_tracks:
                self.current_track_index = -1
            else:
                self.current_track_index = -1

        if isinstance(old_collection, list):
            remapped_collection = []
            seen_indices = set()

            for index in old_collection:
                if index not in old_to_new:
                    continue

                new_index = old_to_new[index]

                if new_index not in seen_indices:
                    remapped_collection.append(new_index)
                    seen_indices.add(new_index)

            self.collection_tracks = remapped_collection

    # =========================================================
    # Persistent queue integration
    # =========================================================
    def add_tracks_to_queue(self, files, show_message=True):
        """Add only new, valid file paths to the base queue."""
        if not hasattr(self, "music_files"):
            self.music_files = []

        self.deduplicate_music_queue()

        existing = {
            key
            for path in self.music_files
            if (key := self.normalize_path(path))
        }

        new_files = []
        submitted = set()

        for path in files:
            try:
                candidate = str(
                    Path(path).expanduser().resolve(strict=False)
                )
            except (TypeError, ValueError, OSError):
                continue

            key = self.normalize_path(candidate)

            if not key or key in existing or key in submitted:
                continue

            try:
                if not Path(candidate).is_file():
                    continue
            except OSError:
                continue

            new_files.append(candidate)
            submitted.add(key)

        if new_files:
            super().add_tracks_to_queue(
                new_files,
                show_message=show_message,
            )

        self.deduplicate_music_queue()

        # Save only unique queue paths to SQLite.
        for path in self.music_files:
            try:
                metadata = self.get_track_metadata(path)

                if not metadata:
                    continue

                metadata = dict(metadata)
                metadata["path"] = str(
                    Path(path).expanduser().resolve(strict=False)
                )
                self.library_db.save_track(metadata)

            except Exception as error:
                print(f"Could not save track {path}: {error}")

        if getattr(self, "_extended_ui_ready", False):
            self.refresh_library_list()

            if getattr(self, "current_page", "") == "Listen Now":
                self.populate_albums()

    # =========================================================
    # Missing-file recovery
    # =========================================================
    @staticmethod
    def normalize_text(value):
        value = unicodedata.normalize("NFKC", str(value or ""))
        value = value.casefold()
        value = re.sub(r"[\W_]+", " ", value)
        return " ".join(value.split())

    def metadata_matches(self, saved, current):
        saved_title = self.normalize_text(saved.get("title"))
        current_title = self.normalize_text(current.get("title"))

        if not saved_title or saved_title != current_title:
            return False

        saved_artist = self.normalize_text(saved.get("artist"))
        current_artist = self.normalize_text(current.get("artist"))
        unknown_artists = {"", "unknown artist", "unknown"}

        if (
            saved_artist not in unknown_artists
            and current_artist not in unknown_artists
            and saved_artist != current_artist
        ):
            return False

        saved_album = self.normalize_text(saved.get("album"))
        current_album = self.normalize_text(current.get("album"))
        unknown_albums = {"", "unknown album", "unknown"}

        if (
            saved_album not in unknown_albums
            and current_album not in unknown_albums
            and saved_album != current_album
        ):
            return False

        try:
            old_duration = float(saved.get("duration") or 0)
            new_duration = float(current.get("duration") or 0)
        except (TypeError, ValueError):
            old_duration = new_duration = 0

        if old_duration > 0 and new_duration > 0:
            if abs(old_duration - new_duration) > 3:
                return False

        return True

    def load_music_from_folder(self):
        """Restore the saved library and discover new local audio files."""
        saved_tracks = self.library_db.get_all_tracks()
        music_folder = self.music_folder

        candidate_paths = []

        if music_folder.is_dir():
            candidate_paths = sorted(
                (
                    path.resolve()
                    for path in music_folder.rglob("*")
                    if path.is_file()
                    and path.suffix.lower() in self.AUDIO_EXTENSIONS
                ),
                key=lambda path: str(path).casefold(),
            )

        existing_paths = set()

        for record in saved_tracks:
            path_value = record.get("path")

            if not path_value:
                continue

            try:
                path = Path(path_value).expanduser()

                if (
                    path.is_file()
                    and path.suffix.lower() in self.AUDIO_EXTENSIONS
                ):
                    existing_paths.add(self.normalize_path(path))
            except (OSError, TypeError, ValueError):
                continue

        new_candidate_paths = [
            str(path)
            for path in candidate_paths
            if self.normalize_path(path) not in existing_paths
        ]

        candidate_metadata = []

        for path in new_candidate_paths:
            try:
                metadata = self.get_track_metadata(path)

                if metadata:
                    metadata = dict(metadata)
                    metadata["path"] = path
                    candidate_metadata.append(metadata)

            except Exception as error:
                print(f"Could not inspect {path}: {error}")

        claimed_paths = set(existing_paths)

        # Recover moved files only when metadata produces one unambiguous
        # match. This avoids attaching an old database entry to the wrong
        # file when multiple tracks have similar metadata.
        for saved in saved_tracks:
            saved_path = saved.get("path")

            if not saved_path:
                continue

            old_path = Path(saved_path).expanduser()

            if old_path.is_file():
                continue

            matches = [
                candidate
                for candidate in candidate_metadata
                if self.normalize_path(candidate["path"])
                not in claimed_paths
                and self.metadata_matches(saved, candidate)
            ]

            if len(matches) == 1:
                recovered = matches[0]

                try:
                    self.library_db.update_track_path(
                        saved_path, recovered
                    )

                    claimed_paths.add(
                        self.normalize_path(recovered["path"])
                    )

                    print(
                        "Recovered missing track: "
                        f"{saved.get('title', old_path.name)}"
                    )

                except Exception as error:
                    print(
                        f"Could not recover {saved_path}: {error}"
                    )

        restored_paths = []

        for path in self.library_db.get_all_paths():
            try:
                candidate = Path(path).expanduser()

                if (
                    candidate.is_file()
                    and candidate.suffix.lower()
                    in self.AUDIO_EXTENSIONS
                ):
                    restored_paths.append(
                        str(candidate.resolve())
                    )
            except (OSError, TypeError, ValueError):
                continue

        all_paths = []
        seen = set()

        for path in restored_paths + [
            str(path) for path in candidate_paths
        ]:
            normalized = self.normalize_path(path)

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            all_paths.append(
                str(Path(path).expanduser().resolve())
            )

        self.add_tracks_to_queue(
            all_paths,
            show_message=False,
        )

    # =========================================================
    # Recommendations
    # =========================================================
    def _current_local_path(self):
        """Return the local track currently loaded in VLC, if any."""
        if getattr(self, "current_source", "local") != "local":
            return None

        index = getattr(self, "current_track_index", -1)

        if not 0 <= index < len(self.music_files):
            return None

        if not self._local_playback_active():
            return None

        return self.music_files[index]

    def _local_playback_active(self):
        player = getattr(self, "audio_player", None)

        if player is None or vlc is None:
            return False

        try:
            state = player.get_state()
        except Exception:
            return False

        return state in (
            vlc.State.Opening,
            vlc.State.Buffering,
            vlc.State.Playing,
            vlc.State.Paused,
        )

    def get_recommendations(self, limit=None):
        """Return ranked recommendations for the unique local library."""
        self.deduplicate_music_queue()

        if not self.music_files:
            return []

        tracks = []

        for path in self.music_files:
            try:
                metadata = self.get_track_metadata(path)

                if metadata:
                    tracks.append({**metadata, "path": path})

            except Exception as error:
                print(
                    f"Could not read metadata for {path}: {error}"
                )

        try:
            return recommend_for_library(
                self.library_db,
                tracks=tracks,
                available_paths=self.music_files,
                current_path=self._current_local_path(),
                limit=limit or self.RECOMMENDATION_LIMIT,
                service=self.recommendation_service,
            )
        except Exception as error:
            print(f"Could not build recommendations: {error}")
            return []

    def populate_recommendations(self, columns):
        if not self.music_files:
            return False

        recommendations = self.get_recommendations()

        if not recommendations:
            self.add_empty_collection_message(
                "No recommendations yet",
                "Add more music to your library to get recommendations.",
            )
            return True

        for position, item in enumerate(recommendations):
            track = item["track"]
            path = track["path"]
            title = track.get("title") or Path(path).stem
            artist = track.get("artist") or "Unknown Artist"

            card = self.create_collection_card(
                title,
                artist,
                path,
                lambda checked=False, target=path:
                    self.play_recommended_track(target),
            )
            card.setToolTip(
                f"{title}\n{artist}\n{item['reason']}"
            )
            self.album_grid.addWidget(
                card, position // columns, position % columns
            )

        return True

    def play_recommended_track(self, path):
        """Play a recommended track through the normal playback flow."""
        try:
            target = str(
                Path(path).expanduser().resolve(strict=False)
            )
        except (TypeError, ValueError, OSError):
            target = str(path)

        target_key = self.normalize_path(target)

        self.deduplicate_music_queue()

        for index, candidate in enumerate(self.music_files):
            if self.normalize_path(candidate) == target_key:
                self.play_track(index)
                return True

        if Path(target).is_file():
            self.add_tracks_to_queue(
                [target],
                show_message=False,
            )

            for index, candidate in enumerate(self.music_files):
                if self.normalize_path(candidate) == target_key:
                    self.play_track(index)
                    return True

        QMessageBox.information(
            self,
            "Track unavailable",
            "The recommended audio file could not be found.",
        )
        return False

    def _refresh_recommendations_if_visible(self):
        if getattr(self, "current_page", "") == "Listen Now":
            self.populate_albums()

    # =========================================================
    # Additional sidebar navigation
    # =========================================================
    def setup_extended_navigation(self):
        sidebar_layout = (
            self.nav_buttons["Your Library"].parentWidget().layout()
        )

        for name in ("Favorites", "History"):
            button = QPushButton(name)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

            self.nav_group.addButton(button)
            self.nav_buttons[name] = button

            sidebar_layout.insertWidget(
                sidebar_layout.indexOf(
                    self.nav_buttons["Your Library"]
                ),
                button,
            )

            button.clicked.connect(
                lambda checked=False, page=name: self.show_page(page)
            )

    # =========================================================
    # Page actions
    # =========================================================
    def setup_library_actions(self):
        self.library_actions = QWidget()
        action_layout = QHBoxLayout(self.library_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.favorite_button = QPushButton("♡ Add Favorite")
        self.create_playlist_button = QPushButton("+ Create Playlist")
        self.add_to_playlist_button = QPushButton("Add to Playlist")
        self.remove_from_playlist_button = QPushButton(
            "Remove from Playlist"
        )
        self.delete_playlist_button = QPushButton("Delete Playlist")
        self.clear_history_button = QPushButton("Clear History")

        self.favorite_button.clicked.connect(self.toggle_favorite)
        self.create_playlist_button.clicked.connect(self.create_playlist)
        self.add_to_playlist_button.clicked.connect(
            self.add_selected_to_playlist
        )
        self.remove_from_playlist_button.clicked.connect(
            self.remove_selected_from_playlist
        )
        self.delete_playlist_button.clicked.connect(
            self.delete_current_playlist
        )
        self.clear_history_button.clicked.connect(
            self.clear_listening_history
        )

        for button in (
            self.favorite_button,
            self.create_playlist_button,
            self.add_to_playlist_button,
            self.remove_from_playlist_button,
            self.delete_playlist_button,
            self.clear_history_button,
        ):
            action_layout.addWidget(button)

        action_layout.addStretch(1)
        self.main_layout.insertWidget(4, self.library_actions)
        self.library_actions.hide()

    def _set_action_visibility(self, page):
        self.library_actions.setVisible(
            page in (
                "Favorites",
                "History",
                "Playlists",
                "Your Library",
            )
        )

        self.favorite_button.setVisible(
            page in ("Favorites", "Your Library")
        )
        self.create_playlist_button.setVisible(page == "Playlists")
        self.add_to_playlist_button.setVisible(
            page in ("Your Library", "Favorites", "Playlists")
        )
        self.remove_from_playlist_button.setVisible(
            page == "Playlists"
            and self.current_playlist_name is not None
        )
        self.delete_playlist_button.setVisible(
            page == "Playlists"
            and self.current_playlist_name is not None
        )
        self.clear_history_button.setVisible(page == "History")

        self.update_favorite_button()

    def show_page(self, page):
        if not getattr(self, "_extended_ui_ready", False):
            super().show_page(page)
            return

        if page not in ("Favorites", "History", "Playlists"):
            self.current_playlist_name = None
            super().show_page(page)
            self._set_action_visibility(page)
            return

        self.current_page = page
        self.collection_tracks = None
        self.collection_title = ""

        super().show_page(page)

        self.heading.setText(page)

        subtitles = {
            "Favorites": "Your saved favorite local tracks.",
            "History": "Recently played local and YouTube tracks.",
            "Playlists": (
                "Create playlists and organize your local music."
            ),
        }
        self.subtitle.setText(subtitles[page])

        self.featured_banner.hide()
        self.section_heading.hide()
        self.album_scroll.hide()
        self.search_bar.hide()
        self.search_hint.hide()
        self.description.show()
        self.library_list.show()

        if page == "Favorites":
            self.current_playlist_name = None
            self.description.setText("Your favorite tracks.")
        elif page == "History":
            self.current_playlist_name = None
            self.description.setText(
                "Your recent listening activity."
            )
        else:
            self.current_playlist_name = None
            self.description.setText(
                "Double-click a playlist to open it."
            )

        self._set_action_visibility(page)
        self.refresh_library_list()

        button = self.nav_buttons.get(page)

        if button is not None:
            button.setChecked(True)

    # =========================================================
    # Library list population
    # =========================================================
    def refresh_library_list(self):
        if not hasattr(self, "library_list"):
            return

        self.deduplicate_music_queue()
        page = getattr(self, "current_page", "")

        if page == "Favorites":
            self._show_favorites()
            return

        if page == "History":
            self._show_history()
            return

        if (
            page == "Playlists"
            and self.current_playlist_name is None
        ):
            self._show_playlists()
            return

        super().refresh_library_list()

    def _show_favorites(self):
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
                f"♥  {metadata.get('title') or 'Unknown title'}\n"
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
            item = QListWidgetItem(f"♥  {title}\n     {artist}  •  YouTube")
            item.setData(Qt.ItemDataRole.UserRole, {"online_favorite": record})
            item.setToolTip(f"{title}\n{artist}\n{record.get('url', '')}")
            self.library_list.addItem(item)
            count += 1

        self.description.setText(f"{count} favorite track(s).")

    def _show_history(self):
        self.library_list.clear()

        records = self.library_db.get_history(limit=200)

        for record in records:
            title = record.get("title") or "Unknown title"
            artist = record.get("artist") or "Unknown artist"
            source = record.get("source") or "local"
            played_at = record.get("played_at") or ""

            if source == "online":
                subtitle = f"{artist}  •  YouTube  •  {played_at}"
            else:
                subtitle = f"{artist}  •  Local music  •  {played_at}"

            item = QListWidgetItem(f"♫  {title}\n     {subtitle}")
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"history_record": record},
            )
            item.setToolTip(
                f"Title: {title}\nArtist: {artist}\n"
                f"Source: {source}\nPlayed: {played_at}\n"
                f"URL: {record.get('url', '')}"
            )
            self.library_list.addItem(item)

        self.description.setText(
            f"{len(records)} listening-history record(s)."
        )

    def _show_playlists(self):
        self.library_list.clear()
        playlists = self.library_db.get_playlists()

        for playlist in playlists:
            name = playlist["name"]
            count = playlist["track_count"]

            item = QListWidgetItem(
                f"▤  {name}\n     {count} track(s)"
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"playlist_name": name},
            )
            self.library_list.addItem(item)

        self.description.setText(
            f"{len(playlists)} playlist(s). Double-click one to open it."
        )

    # =========================================================
    # Double-click behavior
    # =========================================================
    def play_selected_library_track(self, item):
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
            super().play_selected_library_track(item)

    def open_playlist(self, name):
        self.deduplicate_music_queue()
        self.current_playlist_name = name
        paths = self.library_db.get_playlist_tracks(name)

        existing = {
            self.normalize_path(path)
            for path in self.music_files
        }

        missing_from_queue = []

        for path in paths:
            try:
                if (
                    Path(path).is_file()
                    and self.normalize_path(path) not in existing
                ):
                    missing_from_queue.append(path)
                    existing.add(self.normalize_path(path))
            except (OSError, TypeError, ValueError):
                continue

        if missing_from_queue:
            self.add_tracks_to_queue(
                missing_from_queue,
                show_message=False,
            )

        path_to_index = {
            self.normalize_path(path): index
            for index, path in enumerate(self.music_files)
        }

        self.collection_tracks = []
        seen_playlist_paths = set()

        for path in paths:
            key = self.normalize_path(path)

            if not key or key in seen_playlist_paths:
                continue

            if key in path_to_index:
                self.collection_tracks.append(path_to_index[key])
                seen_playlist_paths.add(key)

        self.heading.setText(name)
        self.subtitle.setText("Double-click a track to play it.")
        self.description.setText(
            f"{len(self.collection_tracks)} track(s) in this playlist."
        )

        self._set_action_visibility("Playlists")
        self.refresh_library_list()

    def play_history_record(self, record):
        source = record.get("source")

        if source == "online":
            video_id = record.get("video_id") or ""

            if not video_id:
                QMessageBox.information(
                    self,
                    "Video unavailable",
                    "This history entry has no saved YouTube video ID.",
                )
                return

            if not hasattr(self, "play_online_track"):
                QMessageBox.information(
                    self,
                    "YouTube unavailable",
                    "Online playback is not available in this window.",
                )
                return

            self.online_tracks = [{
                "id": video_id,
                "title": record.get("title") or "Unknown title",
                "channel": record.get("artist") or "Unknown channel",
                "description": "",
                "url": record.get("url") or (
                    f"https://www.youtube.com/watch?v={video_id}"
                ),
            }]

            self.current_playlist_name = None
            self.show_page("Online Music")
            self.play_online_track(0)
            return

        path = record.get("path") or ""

        if not path or not Path(path).is_file():
            QMessageBox.information(
                self,
                "Track unavailable",
                "The original audio file could not be found.",
            )
            return

        normalized = self.normalize_path(path)

        if normalized not in {
            self.normalize_path(item)
            for item in self.music_files
        }:
            self.add_tracks_to_queue(
                [path],
                show_message=False,
            )

        for index, candidate in enumerate(self.music_files):
            if self.normalize_path(candidate) == normalized:
                self.play_track(index)
                return

    # =========================================================
    # Favorites
    # =========================================================
    def get_selected_local_path(self):
        item = self.library_list.currentItem()

        if item is not None:
            data = item.data(Qt.ItemDataRole.UserRole)

            if (
                isinstance(data, int)
                and 0 <= data < len(self.music_files)
            ):
                return self.music_files[data]

        index = getattr(self, "current_track_index", -1)

        if 0 <= index < len(self.music_files):
            return self.music_files[index]

        return None

    def toggle_favorite(self, path=None):
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
        )

    def create_playlist(self):
        name, accepted = QInputDialog.getText(
            self,
            "Create Playlist",
            "Playlist name:",
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            return

        if not self.library_db.create_playlist(name):
            QMessageBox.information(
                self,
                "Playlist not created",
                "A playlist with that name may already exist.",
            )
            return

        self.current_playlist_name = None
        self.show_page("Playlists")

    def add_selected_to_playlist(self):
        path = self.get_selected_local_path()

        if not path:
            QMessageBox.information(
                self,
                "No track selected",
                "Select a local track before adding it to a playlist.",
            )
            return

        playlists = self.library_db.get_playlists()

        if not playlists:
            QMessageBox.information(
                self,
                "No playlists",
                "Create a playlist first.",
            )
            return

        names = [item["name"] for item in playlists]
        default_name = (
            self.current_playlist_name
            if self.current_playlist_name in names
            else names[0]
        )

        name, accepted = QInputDialog.getItem(
            self,
            "Add to Playlist",
            "Choose a playlist:",
            names,
            names.index(default_name),
            False,
        )

        if not accepted:
            return

        metadata = dict(self.get_track_metadata(path))
        metadata["path"] = path
        self.library_db.save_track(metadata)

        if not self.library_db.add_to_playlist(name, path):
            QMessageBox.warning(
                self,
                "Playlist error",
                "Could not add this track.",
            )
            return

        QMessageBox.information(
            self,
            "Playlist updated",
            f"Added “{metadata.get('title', 'Unknown title')}” "
            f"to “{name}”.",
        )

        if self.current_page == "Playlists":
            self.refresh_library_list()

    def remove_selected_from_playlist(self):
        if not self.current_playlist_name:
            return

        path = self.get_selected_local_path()

        if not path:
            QMessageBox.information(
                self,
                "No track selected",
                "Select a track in the open playlist first.",
            )
            return

        self.library_db.remove_from_playlist(
            self.current_playlist_name,
            path,
        )
        self.open_playlist(self.current_playlist_name)

    def delete_current_playlist(self):
        if not self.current_playlist_name:
            return

        name = self.current_playlist_name
        answer = QMessageBox.question(
            self,
            "Delete Playlist",
            f"Delete the playlist “{name}”?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.library_db.delete_playlist(name)
        self.current_playlist_name = None
        self.show_page("Playlists")

    # =========================================================
    # Listening history
    # =========================================================
    def record_current_playback(self):
        try:
            # The online player switches tracks independently of MainWindow.
            # Refreshing here keeps the heart state synchronized across songs.
            self.refresh_like_button()
            source = getattr(self, "current_source", "local")

            if source == "online":
                video = getattr(self, "current_online_track", None)

                if not video:
                    self._last_history_key = None
                    return

                video_id = str(video.get("id") or "")

                if not video_id:
                    return

                key = f"online:{video_id}"

                if key == self._last_history_key:
                    return

                self.library_db.add_history(
                    source="online",
                    track_key=key,
                    title=video.get("title") or "Unknown title",
                    artist=video.get("channel") or "Unknown channel",
                    video_id=video_id,
                    url=video.get("url") or (
                        f"https://www.youtube.com/watch?v={video_id}"
                    ),
                )
                self._last_history_key = key

                if self.current_page == "History":
                    self.refresh_library_list()

                return

            self.deduplicate_music_queue()

            index = getattr(self, "current_track_index", -1)

            if not 0 <= index < len(self.music_files):
                self._last_history_key = None
                return

            if not self._local_playback_active():
                if getattr(self, "audio_player", None) is not None:
                    self._last_history_key = None
                return

            path = self.music_files[index]

            if not Path(path).is_file():
                return

            key = f"local:{self.normalize_path(path)}"

            if key == self._last_history_key:
                return

            metadata = dict(self.get_track_metadata(path))
            resolved_path = str(Path(path).resolve())

            self.library_db.save_track({
                **metadata,
                "path": resolved_path,
            })

            self.library_db.add_history(
                source="local",
                track_key=key,
                path=resolved_path,
                title=metadata.get("title"),
                artist=metadata.get("artist"),
                album=metadata.get("album"),
            )

            self._last_history_key = key

            if self.current_page == "History":
                self.refresh_library_list()

            self._refresh_recommendations_if_visible()

        except Exception as error:
            print(f"Could not record playback history: {error}")

    def clear_listening_history(self):
        answer = QMessageBox.question(
            self,
            "Clear History",
            "Clear all listening-history records?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.library_db.clear_history()
        self._last_history_key = None
        self.refresh_library_list()
        self._refresh_recommendations_if_visible()

    # =========================================================
    # Shutdown
    # =========================================================
    def closeEvent(self, event):
        if hasattr(self, "history_timer"):
            self.history_timer.stop()

        try:
            super().closeEvent(event)
        finally:
            self.library_db.close()