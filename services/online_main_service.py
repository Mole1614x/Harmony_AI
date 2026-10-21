
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.jamendo_service import JamendoService
from ui.persistent_main_window import PersistentMainWindow

try:
    import vlc
except (ImportError, OSError):
    vlc = None


class OnlineMainWindow(PersistentMainWindow):
    """SkullCandy with Jamendo search and online audio playback."""

    def __init__(self):
        self.current_source = "local"
        self.current_online_track = None
        self.online_tracks = []
        self.current_online_index = -1

        self.jamendo_service = JamendoService()

        super().__init__()

        self.setup_online_music_ui()
        self.add_online_navigation()

    # =========================================================
    # Online Music UI
    # =========================================================
    def setup_online_music_ui(self):
        self.online_panel = QFrame()
        self.online_panel.setObjectName("onlinePanel")

        panel_layout = QVBoxLayout(self.online_panel)
        panel_layout.setContentsMargins(0, 8, 0, 0)
        panel_layout.setSpacing(12)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)

        self.online_search_bar = QLineEdit()
        self.online_search_bar.setObjectName("searchBar")
        self.online_search_bar.setMinimumHeight(44)
        self.online_search_bar.setPlaceholderText(
            "Search Jamendo songs or artists..."
        )
        self.online_search_bar.setClearButtonEnabled(True)
        self.online_search_bar.returnPressed.connect(
            self.search_online_music
        )

        self.online_search_button = QPushButton("Search")
        self.online_search_button.setObjectName("playButton")
        self.online_search_button.setMinimumHeight(44)
        self.online_search_button.setMinimumWidth(100)
        self.online_search_button.clicked.connect(
            self.search_online_music
        )

        search_row.addWidget(self.online_search_bar, 1)
        search_row.addWidget(self.online_search_button)

        panel_layout.addLayout(search_row)

        self.online_hint = QLabel(
            "Search Jamendo to discover music available for streaming."
        )
        self.online_hint.setObjectName("subtitle")
        self.online_hint.setWordWrap(True)
        panel_layout.addWidget(self.online_hint)

        self.online_results_list = QListWidget()
        self.online_results_list.setObjectName("libraryList")
        self.online_results_list.setSpacing(5)
        self.online_results_list.itemDoubleClicked.connect(
            self.play_selected_online_track
        )
        panel_layout.addWidget(self.online_results_list, 1)

        # Insert the online panel before the existing featured content.
        self.main_layout.insertWidget(4, self.online_panel, 1)
        self.online_panel.hide()

        self.online_panel.setStyleSheet("""
            QFrame#onlinePanel {
                background-color: transparent;
                border: none;
            }
        """)

    def add_online_navigation(self):
        sidebar_layout = self.add_music_button.parentWidget().layout()

        self.online_nav_button = QPushButton("Online Music")
        self.online_nav_button.setObjectName("navButton")
        self.online_nav_button.setCheckable(True)
        self.online_nav_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.nav_group.addButton(self.online_nav_button)
        sidebar_layout.insertWidget(
            sidebar_layout.indexOf(self.add_music_button),
            self.online_nav_button,
        )

        self.online_nav_button.clicked.connect(
            lambda checked=False: self.show_page("Online Music")
        )

    # =========================================================
    # Online search
    # =========================================================
    def search_online_music(self):
        query = self.online_search_bar.text().strip()

        if not query:
            self.online_hint.setText(
                "Enter a song title, artist, or keyword."
            )
            self.online_search_bar.setFocus()
            return

        self.online_search_button.setEnabled(False)
        self.online_search_button.setText("Searching...")
        self.online_hint.setText(
            f'Searching Jamendo for "{query}"...'
        )

        try:
            # This first prototype performs the request synchronously.
            # A worker thread can be added later to keep the UI responsive.
            results = self.jamendo_service.search_tracks(query)

            self.online_tracks = results
            self.current_online_index = -1
            self.online_results_list.clear()

            for index, track in enumerate(results):
                duration = self.format_seconds(track["duration"])

                display = (
                    f"♫  {track['title']}\n"
                    f"     {track['artist']}  •  "
                    f"{track['album']}  •  {duration}"
                )

                item = QListWidgetItem(display)
                item.setData(Qt.ItemDataRole.UserRole, index)

                license_url = track.get("license_url") or (
                    "No licence URL supplied by the API"
                )

                flags = track.get("license_flags", {})
                licence_notes = []

                if flags.get("non_commercial"):
                    licence_notes.append("Non-commercial restriction")

                if flags.get("no_derivatives"):
                    licence_notes.append("No derivatives")

                if flags.get("share_alike"):
                    licence_notes.append("Share-alike condition")

                tooltip = (
                    f"Title: {track['title']}\n"
                    f"Artist: {track['artist']}\n"
                    f"Album: {track['album']}\n"
                    f"Duration: {duration}\n"
                    f"Provider: Jamendo\n"
                    f"Licence: {license_url}"
                )

                if licence_notes:
                    tooltip += (
                        "\nLicence notes: "
                        + ", ".join(licence_notes)
                    )

                item.setToolTip(tooltip)
                self.online_results_list.addItem(item)

            if results:
                self.online_hint.setText(
                    f"Found {len(results)} track(s). "
                    "Double-click a result to play it."
                )
            else:
                self.online_hint.setText(
                    f'No playable results found for "{query}". '
                    "Try a different search."
                )

        except Exception as exc:
            self.online_hint.setText("Online search failed.")
            QMessageBox.warning(
                self,
                "Jamendo search error",
                str(exc),
            )

        finally:
            self.online_search_button.setEnabled(True)
            self.online_search_button.setText("Search")

    def play_selected_online_track(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)

        if index is not None:
            self.play_online_track(int(index))

    # =========================================================
    # Online playback
    # =========================================================
    def play_online_track(self, index):
        if not self.ensure_audio_backend():
            return

        if not 0 <= index < len(self.online_tracks):
            return

        track = self.online_tracks[index]
        stream_url = track.get("audio")

        if not stream_url:
            QMessageBox.warning(
                self,
                "Stream unavailable",
                "Jamendo did not supply an audio stream for this track.",
            )
            return

        try:
            # URL playback is deliberately separate from local files.
            media = self.vlc_instance.media_new(stream_url)
            self.audio_player.set_media(media)
            self.audio_player.audio_set_volume(
                self.volume_slider.value()
            )

            if self.audio_player.play() == -1:
                self.show_playback_error(
                    "VLC could not start this online stream. "
                    "The stream may be unavailable or unsupported."
                )
                return

            self.current_source = "online"
            self.current_online_track = track
            self.current_online_index = index
            self.current_track_index = -1
            self._track_ended = False
            self.is_seeking = False

            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(0)
            self.seek_slider.blockSignals(False)

            self.elapsed_label.setText("0:00")
            self.duration_label.setText(
                self.format_seconds(track.get("duration", 0))
            )

            self.track_info.setText(
                f"{track['title']}\n{track['artist']} • Jamendo"
            )
            self.track_info.setToolTip(
                f"Title: {track['title']}\n"
                f"Artist: {track['artist']}\n"
                f"Album: {track['album']}\n"
                f"Provider: Jamendo\n"
                f"Licence: {track.get('license_url') or 'Not supplied'}"
            )

            self.update_online_artwork(track.get("image", ""))
            self.play_button.setText("❚❚")

            self.online_results_list.setCurrentRow(index)
            self.online_hint.setText(
                f"Now playing: {track['title']} — {track['artist']}"
            )

        except Exception as exc:
            self.show_playback_error(
                f"Could not play the online track:\n{exc}"
            )

    def update_online_artwork(self, image_url):
        if not image_url:
            self.set_placeholder_artwork()
            return

        try:
            request = Request(
                image_url,
                headers={"User-Agent": "SkullCandyMusicPlayer/1.0"},
            )

            with urlopen(request, timeout=5) as response:
                image_data = response.read(5 * 1024 * 1024 + 1)

            # Avoid loading an unexpectedly large image.
            if len(image_data) > 5 * 1024 * 1024:
                self.set_placeholder_artwork()
                return

            pixmap = QPixmap()

            if not pixmap.loadFromData(image_data):
                self.set_placeholder_artwork()
                return

            self.album_cover.setText("")
            self.album_cover.setPixmap(
                pixmap.scaled(
                    self.ARTWORK_SIZE,
                    self.ARTWORK_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        except (HTTPError, URLError, TimeoutError, OSError):
            self.set_placeholder_artwork()

    # =========================================================
    # Page navigation
    # =========================================================
    def show_page(self, page):
        if page != "Online Music":
            if hasattr(self, "online_panel"):
                self.online_panel.hide()

            super().show_page(page)
            return

        self.current_page = "Online Music"
        self.collection_tracks = None
        self.collection_title = ""

        self.heading.setText("Online Music")
        self.subtitle.setText(
            "Discover and stream music from Jamendo."
        )

        self.featured_banner.hide()
        self.section_heading.hide()
        self.description.hide()
        self.album_scroll.hide()
        self.library_list.hide()
        self.search_bar.hide()
        self.search_hint.hide()

        self.online_panel.show()

        self.online_nav_button.setChecked(True)
        self.online_search_bar.setFocus()

    # =========================================================
    # Playback controls
    # =========================================================
    def play_track(self, index):
        # Preserve the original local playback implementation.
        self.current_source = "local"
        self.current_online_track = None
        self.current_online_index = -1
        super().play_track(index)

    def toggle_play_button(self):
        if self.current_source != "online":
            super().toggle_play_button()
            return

        if not self.ensure_audio_backend():
            return

        if self.current_online_track is None:
            selected = self.online_results_list.currentRow()

            if selected < 0:
                selected = 0

            if self.online_tracks:
                self.play_online_track(selected)
            else:
                QMessageBox.information(
                    self,
                    "No online track selected",
                    "Search for music first, then select a result.",
                )
            return

        try:
            state = self.audio_player.get_state()

            if state == vlc.State.Playing:
                self.audio_player.pause()
                self.play_button.setText("▶")

            elif state == vlc.State.Paused:
                self.audio_player.set_pause(0)
                self.play_button.setText("❚❚")

            elif state == vlc.State.Ended:
                self.play_online_track(self.current_online_index)

            else:
                if self.audio_player.get_media() is None:
                    self.play_online_track(self.current_online_index)
                else:
                    result = self.audio_player.play()

                    if result == -1:
                        self.show_playback_error(
                            "VLC could not resume this online track."
                        )
                    else:
                        self.play_button.setText("❚❚")

        except Exception as exc:
            self.show_playback_error(str(exc))

    def next_track(self):
        if self.current_source != "online":
            super().next_track()
            return

        if not self.online_tracks:
            return

        next_index = (
            self.current_online_index + 1
        ) % len(self.online_tracks)

        self.play_online_track(next_index)

    def previous_track(self):
        if self.current_source != "online":
            super().previous_track()
            return

        if not self.online_tracks:
            return

        if (
            self.audio_player is not None
            and self.audio_player.get_time() > 3000
        ):
            self.audio_player.set_time(0)
            self._track_ended = False
            return

        previous_index = (
            self.current_online_index - 1
        ) % len(self.online_tracks)

        self.play_online_track(previous_index)

    def update_playback_position(self):
        # Keep the existing local playback timer intact.
        if self.current_source != "online":
            super().update_playback_position()
            return

        if self.audio_player is None or self.current_online_track is None:
            return

        try:
            state = self.audio_player.get_state()

            if state == vlc.State.Ended and not self._track_ended:
                self._track_ended = True

                if len(self.online_tracks) > 1:
                    self.next_track()
                else:
                    self.play_button.setText("▶")
                    self.seek_slider.setValue(0)
                    self.elapsed_label.setText("0:00")

                return

            duration = self.audio_player.get_length()
            current_time = self.audio_player.get_time()

            if duration > 0:
                self.duration_label.setText(
                    self.format_time(duration)
                )

                if not self.is_seeking:
                    position = int(
                        max(0, min(1000, current_time / duration * 1000))
                    )

                    self.seek_slider.blockSignals(True)
                    self.seek_slider.setValue(position)
                    self.seek_slider.blockSignals(False)

            if current_time >= 0:
                self.elapsed_label.setText(
                    self.format_time(current_time)
                )

            if state in (vlc.State.Stopped, vlc.State.Ended):
                self.play_button.setText("▶")
            elif state == vlc.State.Playing:
                self.play_button.setText("❚❚")

        except Exception:
            pass

    def finish_seeking(self):
        if self.current_source != "online":
            super().finish_seeking()
            return

        if self.audio_player is None:
            self.is_seeking = False
            return

        duration = self.audio_player.get_length()

        if duration > 0:
            position = self.seek_slider.value() / 1000
            target_ms = int(position * duration)
            self.audio_player.set_time(target_ms)
            self.elapsed_label.setText(self.format_time(target_ms))

        self.is_seeking = False
