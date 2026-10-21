
import json
import re

from PySide6.QtCore import Qt, QUrl, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from services.youtube_service import YouTubeService
from ui.persistent_main_window import PersistentMainWindow


APP_ORIGIN = "https://com.skullcandy.desktop"


class ClickableArtwork(QLabel):
    """Clickable thumbnail used to expand or collapse the video."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_click = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.on_click is not None
        ):
            self.on_click()
            event.accept()
            return

        super().mousePressEvent(event)


class OnlineMainWindow(PersistentMainWindow):
    """Local music and YouTube playback with an expandable video overlay."""

    def __init__(self, database_path=None, music_folder=None):
        self.current_source = "local"
        self.current_online_track = None
        self.online_tracks = []
        self.current_online_index = -1

        self.youtube_service = YouTubeService()

        self._youtube_update_pending = False
        self._youtube_page_loaded = False
        self._track_ended = False
        self._last_online_duration = 0.0

        self._player_expanded = False
        self._artwork_layout = None
        self._artwork_index = -1

        super().__init__(
            database_path=database_path,
            music_folder=music_folder,
        )

        self.setup_online_music_ui()
        self.install_artwork_player()
        self.add_online_navigation()

    # =========================================================
    # Online search UI
    # =========================================================
    def setup_online_music_ui(self):
        self.online_panel = QFrame()
        self.online_panel.setObjectName("onlinePanel")

        panel_layout = QVBoxLayout(self.online_panel)
        panel_layout.setContentsMargins(0, 8, 0, 0)
        panel_layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)

        self.online_search_bar = QLineEdit()
        self.online_search_bar.setObjectName("searchBar")
        self.online_search_bar.setMinimumHeight(44)
        self.online_search_bar.setPlaceholderText(
            "Search YouTube songs, artists, or music videos..."
        )
        self.online_search_bar.setClearButtonEnabled(True)
        self.online_search_bar.returnPressed.connect(
            self.search_online_music
        )

        # Compact search icon button instead of the clipped "Search" text.
        self.online_search_button = QPushButton("⌕")
        self.online_search_button.setObjectName("onlineSearchButton")
        self.online_search_button.setFixedSize(44, 44)
        self.online_search_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.online_search_button.setToolTip("Search YouTube")
        self.online_search_button.setAccessibleName("Search YouTube")
        self.online_search_button.setStyleSheet("""
            QPushButton#onlineSearchButton {
                background-color: #303030;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                font-size: 27px;
                font-weight: 600;
                padding: 0px;
            }

            QPushButton#onlineSearchButton:hover {
                background-color: #454545;
            }

            QPushButton#onlineSearchButton:pressed {
                background-color: #202020;
            }

            QPushButton#onlineSearchButton:disabled {
                color: #888888;
                background-color: #292929;
            }
        """)
        self.online_search_button.clicked.connect(
            self.search_online_music
        )

        search_row.addWidget(self.online_search_bar, 1)
        search_row.addWidget(self.online_search_button)
        panel_layout.addLayout(search_row)

        self.online_hint = QLabel(
            "Search YouTube and double-click a result to play it."
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

        # Reuse the existing main layout.
        self.main_layout.insertWidget(4, self.online_panel, 1)
        self.online_panel.hide()

        self.online_panel.setStyleSheet("""
            QFrame#onlinePanel {
                background-color: transparent;
                border: none;
            }
        """)

        self.thumbnail_manager = QNetworkAccessManager(self)

        # One persistent YouTube player is reused for online playback.
        self.youtube_player_view = QWebEngineView()
        self.youtube_player_view.setObjectName("youtubePlayer")
        self.youtube_player_view.setMinimumSize(360, 203)
        self.youtube_player_view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.youtube_player_view.hide()

        settings = self.youtube_player_view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled,
            True,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,
            False,
        )

        self.youtube_player_view.loadFinished.connect(
            self._on_youtube_page_loaded
        )

        self.youtube_player_view.setStyleSheet("""
            QWebEngineView#youtubePlayer {
                background-color: #000000;
                border: none;
                border-radius: 12px;
            }
        """)

        self.load_youtube_player_page()

    # =========================================================
    # Artwork slot and expanded video overlay
    # =========================================================
    def install_artwork_player(self):
        """Install the online thumbnail in the existing artwork slot."""
        if not hasattr(self, "album_cover"):
            raise AttributeError(
                "MainWindow must expose self.album_cover."
            )

        parent = self.album_cover.parentWidget()

        if parent is None or parent.layout() is None:
            raise RuntimeError(
                "Could not locate the existing album artwork layout."
            )

        self._artwork_layout = parent.layout()
        self._artwork_index = self._artwork_layout.indexOf(
            self.album_cover
        )

        if self._artwork_index < 0:
            raise RuntimeError(
                "Could not locate album_cover in its parent layout."
            )

        self.artwork_container = QFrame(parent)
        self.artwork_container.setObjectName("artworkPlayerContainer")
        self.artwork_container.setFixedSize(64, 64)

        artwork_layout = QVBoxLayout(self.artwork_container)
        artwork_layout.setContentsMargins(0, 0, 0, 0)
        artwork_layout.setSpacing(0)

        self.online_artwork = ClickableArtwork(self.artwork_container)
        self.online_artwork.setObjectName("onlineArtwork")
        self.online_artwork.setFixedSize(64, 64)
        self.online_artwork.setText("♫")
        self.online_artwork.setToolTip("Click to expand the video")
        self.online_artwork.on_click = self.toggle_player_expanded

        artwork_layout.addWidget(self.online_artwork)

        self._artwork_layout.removeWidget(self.album_cover)
        self.album_cover.hide()

        self._artwork_layout.insertWidget(
            self._artwork_index,
            self.artwork_container,
        )
        self.artwork_container.hide()

        # Overlay is independent of the bottom player bar.
        self.expanded_player_overlay = QFrame(self)
        self.expanded_player_overlay.setObjectName(
            "expandedPlayerOverlay"
        )
        self.expanded_player_overlay.setFixedSize(500, 340)
        self.expanded_player_overlay.hide()

        overlay_layout = QVBoxLayout(self.expanded_player_overlay)
        overlay_layout.setContentsMargins(12, 12, 12, 12)
        overlay_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        self.expanded_track_title = QLabel("Now Playing")
        self.expanded_track_title.setObjectName("expandedTrackTitle")
        self.expanded_track_title.setWordWrap(False)
        self.expanded_track_title.setMinimumWidth(0)
        self.expanded_track_title.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.collapse_player_button = QPushButton("×")
        self.collapse_player_button.setObjectName(
            "collapsePlayerButton"
        )
        self.collapse_player_button.setFixedSize(32, 32)
        self.collapse_player_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.collapse_player_button.setToolTip("Collapse video")
        self.collapse_player_button.clicked.connect(
            self.collapse_player
        )

        header_layout.addWidget(self.expanded_track_title, 1)
        header_layout.addWidget(self.collapse_player_button)
        overlay_layout.addLayout(header_layout)

        overlay_layout.addWidget(self.youtube_player_view, 1)

        self.expanded_track_channel = QLabel("YouTube")
        self.expanded_track_channel.setObjectName(
            "expandedTrackChannel"
        )
        self.expanded_track_channel.setWordWrap(False)
        overlay_layout.addWidget(self.expanded_track_channel)

        self.expanded_player_overlay.setStyleSheet("""
            QFrame#expandedPlayerOverlay {
                background-color: #181818;
                border: 1px solid #373737;
                border-radius: 16px;
            }

            QLabel#expandedTrackTitle {
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
                background: transparent;
                border: none;
            }

            QLabel#expandedTrackChannel {
                color: #a8a8a8;
                font-size: 12px;
                background: transparent;
                border: none;
            }

            QPushButton#collapsePlayerButton {
                background-color: #303030;
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 24px;
            }

            QPushButton#collapsePlayerButton:hover {
                background-color: #484848;
            }

            QLabel#onlineArtwork {
                background-color: #252525;
                color: #eeeeee;
                border-radius: 8px;
                font-size: 30px;
            }
        """)

    def _show_local_artwork_slot(self):
        """Restore local album artwork to its original layout slot."""
        self._artwork_layout.removeWidget(self.artwork_container)
        self.artwork_container.hide()

        self._artwork_layout.insertWidget(
            self._artwork_index,
            self.album_cover,
        )
        self.album_cover.show()

    def _show_online_artwork_slot(self):
        """Show the online thumbnail in the original artwork slot."""
        self._artwork_layout.removeWidget(self.album_cover)
        self.album_cover.hide()

        self._artwork_layout.insertWidget(
            self._artwork_index,
            self.artwork_container,
        )
        self.artwork_container.show()

    def toggle_player_expanded(self):
        if self.current_source != "online":
            return

        if self._player_expanded:
            self.collapse_player()
        else:
            self.expand_player()

    def expand_player(self):
        """Show the video overlay above the bottom player bar."""
        if (
            self.current_source != "online"
            or self.current_online_track is None
        ):
            return

        self._player_expanded = True

        video = self.current_online_track
        self.expanded_track_title.setText(
            video.get("title", "Unknown title")
        )
        self.expanded_track_channel.setText(
            video.get("channel", "Unknown channel")
        )

        self._position_expanded_overlay()
        self.expanded_player_overlay.show()
        self.expanded_player_overlay.raise_()
        self.youtube_player_view.show()

    def collapse_player(self):
        """Hide the expanded panel without explicitly stopping playback."""
        self._player_expanded = False

        if hasattr(self, "expanded_player_overlay"):
            self.expanded_player_overlay.hide()

        if hasattr(self, "youtube_player_view"):
            self.youtube_player_view.hide()

    def _position_expanded_overlay(self):
        """Position the video overlay above the bottom player bar."""
        if not hasattr(self, "expanded_player_overlay"):
            return

        margin = 16
        overlay_width = min(500, max(320, self.width() - margin * 2))
        overlay_height = 340

        self.expanded_player_overlay.setFixedSize(
            overlay_width,
            overlay_height,
        )

        player_bar = getattr(self, "player_bar", None)

        if player_bar is not None:
            bar_top = player_bar.mapTo(self, QPoint(0, 0)).y()
        else:
            bar_top = self.height() - 120

        x = self.width() - overlay_width - margin
        y = bar_top - overlay_height - 12

        x = max(margin, min(x, self.width() - overlay_width - margin))
        y = max(margin, y)

        self.expanded_player_overlay.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if getattr(self, "_player_expanded", False):
            self._position_expanded_overlay()
            self.expanded_player_overlay.raise_()

    def update_online_artwork(self, video):
        title = video.get("title", "Unknown title")
        channel = video.get("channel", "Unknown channel")
        video_id = str(video.get("id") or "").strip()

        self.online_artwork.setPixmap(QPixmap())
        self.online_artwork.setText("♫")
        self.online_artwork.setToolTip(
            f"{title}\n{channel}\nClick to expand the video"
        )

        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return

        thumbnail_url = (
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        )

        request = QNetworkRequest(QUrl(thumbnail_url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )

        reply = self.thumbnail_manager.get(request)
        reply.finished.connect(
            lambda r=reply: self._on_thumbnail_loaded(r)
        )

    def _on_thumbnail_loaded(self, reply):
        try:
            if reply.error():
                return

            pixmap = QPixmap()
            if not pixmap.loadFromData(reply.readAll()):
                return

            scaled = pixmap.scaled(
                self.online_artwork.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

            self.online_artwork.setText("")
            self.online_artwork.setPixmap(scaled)

        finally:
            reply.deleteLater()

    # =========================================================
    # Navigation
    # =========================================================
    def add_online_navigation(self):
        sidebar_layout = self.add_music_button.parentWidget().layout()

        self.online_nav_button = QPushButton("YouTube Music")
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
    # YouTube IFrame Player API
    # =========================================================
    def load_youtube_player_page(self):
        origin_json = json.dumps(APP_ORIGIN)

        html = r"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport"
                  content="width=device-width, initial-scale=1">
            <style>
                html, body {
                    margin: 0;
                    padding: 0;
                    width: 100%;
                    height: 100%;
                    overflow: hidden;
                    background: #000;
                    font-family: sans-serif;
                }

                #player-container {
                    position: relative;
                    width: 100%;
                    height: 100%;
                    background: #000;
                    overflow: hidden;
                }

                #player {
                    position: absolute;
                    inset: 0;
                    width: 100%;
                    height: 100%;
                }

                #player iframe {
                    width: 100%;
                    height: 100%;
                    border: 0;
                }

                #message {
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    color: #bbb;
                    font-size: 12px;
                    text-align: center;
                    width: 90%;
                    line-height: 1.5;
                    pointer-events: none;
                    z-index: 2;
                }
            </style>
        </head>
        <body>
            <div id="player-container">
                <div id="player"></div>
                <div id="message">Connecting to YouTube...</div>
            </div>

            <script>
                const APP_ORIGIN = __APP_ORIGIN__;

                window.skullPlayer = null;
                window.skullPlayerReady = false;
                window.pendingVideoId = null;
                window.skullPlayerError = null;

                function showMessage(text) {
                    const message = document.getElementById("message");
                    if (message) {
                        message.textContent = text;
                        message.style.display = "block";
                    }
                }

                function hideMessage() {
                    const message = document.getElementById("message");
                    if (message) {
                        message.style.display = "none";
                    }
                }

                function isValidVideoId(videoId) {
                    return typeof videoId === "string" &&
                        /^[A-Za-z0-9_-]{11}$/.test(videoId);
                }

                function loadPendingVideo() {
                    if (
                        !window.skullPlayerReady ||
                        !window.skullPlayer ||
                        !window.pendingVideoId
                    ) {
                        return;
                    }

                    const videoId = window.pendingVideoId;
                    window.pendingVideoId = null;

                    if (!isValidVideoId(videoId)) {
                        showMessage("Invalid YouTube video ID.");
                        return;
                    }

                    showMessage("Loading video...");
                    window.skullPlayer.loadVideoById({
                        videoId: videoId
                    });
                }

                function onYouTubeIframeAPIReady() {
                    window.skullPlayer = new YT.Player("player", {
                        width: "100%",
                        height: "100%",
                        playerVars: {
                            autoplay: 0,
                            controls: 0,
                            disablekb: 1,
                            fs: 0,
                            playsinline: 1,
                            rel: 0,
                            enablejsapi: 1,
                            origin: APP_ORIGIN,
                            cc_load_policy: 0,
                            iv_load_policy: 3
                        },
                        events: {
                            onReady: function(event) {
                                window.skullPlayerReady = true;
                                window.skullPlayerError = null;
                                event.target.setVolume(70);

                                if (window.pendingVideoId) {
                                    loadPendingVideo();
                                } else {
                                    showMessage(
                                        "Select a YouTube result to play."
                                    );
                                }
                            },

                            onStateChange: function(event) {
                                if (event.data === YT.PlayerState.PLAYING) {
                                    hideMessage();
                                } else if (
                                    event.data === YT.PlayerState.BUFFERING
                                ) {
                                    showMessage("Buffering...");
                                } else if (
                                    event.data === YT.PlayerState.PAUSED ||
                                    event.data === YT.PlayerState.ENDED ||
                                    event.data === YT.PlayerState.CUED
                                ) {
                                    hideMessage();
                                }
                            },

                            onError: function(event) {
                                window.skullPlayerError = event.data;

                                const errors = {
                                    2: "Invalid video ID.",
                                    5: "Embedded playback error.",
                                    100: "Video unavailable or private.",
                                    101: "Embedding is disabled for this video.",
                                    150: "Embedding is disabled for this video.",
                                    153: "YouTube could not verify the player request."
                                };

                                showMessage(
                                    errors[event.data] ||
                                    "YouTube playback error: " + event.data
                                );

                                console.error(
                                    "YouTube player error:",
                                    event.data
                                );
                            }
                        }
                    });
                }

                const tag = document.createElement("script");
                tag.src = "https://www.youtube.com/iframe_api";

                tag.onerror = function() {
                    showMessage(
                        "Could not load YouTube. Check your internet connection."
                    );
                };

                document.head.appendChild(tag);
            </script>
        </body>
        </html>
        """

        html = html.replace("__APP_ORIGIN__", origin_json)

        self.youtube_player_view.setHtml(
            html,
            QUrl(APP_ORIGIN + "/"),
        )

    def _on_youtube_page_loaded(self, success):
        self._youtube_page_loaded = bool(success)

        if not success:
            self.online_hint.setText(
                "The YouTube player could not load. Check your connection."
            )
            return

        self.online_hint.setText(
            "YouTube player ready. Search for a song to begin."
        )

    def _run_youtube_js(self, script, callback=None):
        if not hasattr(self, "youtube_player_view"):
            if callback:
                callback(None)
            return

        page = self.youtube_player_view.page()

        if callback is None:
            page.runJavaScript(script)
        else:
            page.runJavaScript(script, callback)

    # =========================================================
    # YouTube search
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
        self.online_search_button.setText("…")
        self.online_search_button.setToolTip("Searching YouTube...")
        self.online_hint.setText(f'Searching YouTube for "{query}"...')

        try:
            results = self.youtube_service.search_videos(
                query,
                limit=20,
            )

            self.online_tracks = results or []
            self.current_online_index = -1
            self.online_results_list.clear()

            for index, video in enumerate(self.online_tracks):
                title = video.get("title", "Unknown title")
                channel = video.get("channel", "Unknown channel")

                item = QListWidgetItem(
                    f"♫  {title}\n"
                    f"     {channel}  •  YouTube"
                )
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(
                    f"Title: {title}\n"
                    f"Channel: {channel}\n\n"
                    f"{video.get('description', '')}\n\n"
                    f"Open on YouTube:\n{video.get('url', '')}"
                )

                self.online_results_list.addItem(item)

            if self.online_tracks:
                self.online_hint.setText(
                    f"Found {len(self.online_tracks)} video(s). "
                    "Double-click a result to play it."
                )
            else:
                self.online_hint.setText(
                    f'No YouTube videos found for "{query}".'
                )

        except Exception as exc:
            self.online_hint.setText("YouTube search failed.")
            QMessageBox.warning(
                self,
                "YouTube Search Error",
                str(exc),
            )

        finally:
            self.online_search_button.setEnabled(True)
            self.online_search_button.setText("⌕")
            self.online_search_button.setToolTip("Search YouTube")

    def play_selected_online_track(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)

        if index is not None:
            self.play_online_track(int(index))

    # =========================================================
    # Online playback
    # =========================================================
    def play_online_track(self, index):
        if not 0 <= index < len(self.online_tracks):
            return

        video = self.online_tracks[index]
        video_id = str(video.get("id") or "").strip()

        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            QMessageBox.warning(
                self,
                "Video Unavailable",
                "This result does not have a valid YouTube video ID.\n\n"
                "Check services/youtube_service.py.",
            )
            return

        audio_player = getattr(self, "audio_player", None)
        if audio_player is not None:
            try:
                audio_player.stop()
            except Exception:
                pass

        self.current_source = "online"
        self.current_online_track = video
        self.current_online_index = index
        self.current_track_index = -1
        self._track_ended = False
        self._youtube_update_pending = False
        self._last_online_duration = 0.0
        self.is_seeking = False

        self.collapse_player()
        self._show_online_artwork_slot()

        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(0)
        self.seek_slider.blockSignals(False)

        self.elapsed_label.setText("0:00")
        self.duration_label.setText("--:--")

        title = video.get("title", "Unknown title")
        channel = video.get("channel", "Unknown channel")

        self.track_info.setText(f"{title}\n{channel} • YouTube")
        self.track_info.setToolTip(
            f"Title: {title}\n"
            f"Channel: {channel}\n"
            f"URL: {video.get('url', '')}"
        )

        self.expanded_track_title.setText(title)
        self.expanded_track_channel.setText(channel)

        self.set_placeholder_artwork()
        self.update_online_artwork(video)

        self.play_button.setText("❚❚")
        self.online_results_list.setCurrentRow(index)
        self.online_hint.setText(f"Loading: {title} — {channel}")

        safe_video_id = json.dumps(video_id)

        script = f"""
            (function() {{
                var videoId = {safe_video_id};

                if (!/^[A-Za-z0-9_-]{{11}}$/.test(videoId)) {{
                    console.error("Invalid YouTube video ID:", videoId);
                    return;
                }}

                if (window.skullPlayerReady && window.skullPlayer) {{
                    window.skullPlayer.stopVideo();
                    window.pendingVideoId = null;
                    window.skullPlayer.loadVideoById({{
                        videoId: videoId
                    }});
                }} else {{
                    window.pendingVideoId = videoId;
                }}
            }})();
        """

        self._run_youtube_js(script)

    # =========================================================
    # Page navigation
    # =========================================================
    def show_page(self, page):
        # Discover and YouTube Music share one online search interface.
        if page in ("Discover", "Online Music"):
            if hasattr(self, "expanded_player_overlay"):
                self.expanded_player_overlay.hide()
                self._player_expanded = False

            self.current_page = page
            self.collection_tracks = None
            self.collection_title = ""

            if page == "Discover":
                self.heading.setText("Discover")
                self.subtitle.setText(
                    "Explore and play music from YouTube."
                )
            else:
                self.heading.setText("YouTube Music")
                self.subtitle.setText(
                    "Search and play music videos from YouTube."
                )

            self.featured_banner.hide()
            self.section_heading.hide()
            self.description.hide()
            self.album_scroll.hide()
            self.library_list.hide()
            self.search_bar.hide()
            self.search_hint.hide()

            self.online_panel.show()

            if page == "Online Music":
                self.online_nav_button.setChecked(True)

            self.online_search_bar.setFocus()
            return

        if hasattr(self, "online_panel"):
            self.online_panel.hide()

        if hasattr(self, "expanded_player_overlay"):
            self.expanded_player_overlay.hide()
            self._player_expanded = False

        super().show_page(page)

    # =========================================================
    # Local playback
    # =========================================================
    def play_track(self, index):
        self._run_youtube_js("""
            window.pendingVideoId = null;

            if (window.skullPlayerReady && window.skullPlayer) {
                window.skullPlayer.stopVideo();
            }
        """)

        self.current_source = "local"
        self.current_online_track = None
        self.current_online_index = -1
        self._youtube_update_pending = False
        self._track_ended = False
        self._last_online_duration = 0.0

        self.collapse_player()
        self._show_local_artwork_slot()

        super().play_track(index)

    # =========================================================
    # Shared player controls
    # =========================================================
    def toggle_play_button(self):
        if self.current_source == "online":
            if self.current_online_track is None:
                selected = self.online_results_list.currentRow()
                if selected < 0:
                    selected = 0

                if self.online_tracks:
                    self.play_online_track(selected)
                else:
                    QMessageBox.information(
                        self,
                        "No Video Selected",
                        "Search for music first, then select a result.",
                    )
                return

            self._run_youtube_js("""
                if (window.skullPlayerReady && window.skullPlayer) {
                    var state = window.skullPlayer.getPlayerState();

                    if (
                        state === YT.PlayerState.PLAYING ||
                        state === YT.PlayerState.BUFFERING
                    ) {
                        window.skullPlayer.pauseVideo();
                    } else {
                        window.skullPlayer.playVideo();
                    }
                }
            """)
            return

        self._run_youtube_js("""
            window.pendingVideoId = null;

            if (window.skullPlayerReady && window.skullPlayer) {
                window.skullPlayer.stopVideo();
            }
        """)

        super().toggle_play_button()

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

        def seek_or_go_previous(current_time):
            try:
                current_time = float(current_time or 0)
            except (TypeError, ValueError):
                current_time = 0

            if current_time > 3:
                self._run_youtube_js("""
                    if (window.skullPlayerReady && window.skullPlayer) {
                        window.skullPlayer.seekTo(0, true);
                    }
                """)
                return

            previous_index = (
                self.current_online_index - 1
            ) % len(self.online_tracks)

            self.play_online_track(previous_index)

        self._run_youtube_js(
            """
            (window.skullPlayerReady && window.skullPlayer)
                ? window.skullPlayer.getCurrentTime()
                : 0
            """,
            seek_or_go_previous,
        )

    def change_volume(self, value):
        super().change_volume(value)

        if self.current_source == "online":
            volume = max(0, min(100, int(value)))

            self._run_youtube_js(
                f"""
                if (window.skullPlayerReady && window.skullPlayer) {{
                    window.skullPlayer.setVolume({volume});
                }}
                """
            )

    # =========================================================
    # Playback progress
    # =========================================================
    def update_playback_position(self):
        if self.current_source != "online":
            super().update_playback_position()
            return

        if self.current_online_track is None:
            return

        if self._youtube_update_pending:
            return

        self._youtube_update_pending = True

        script = """
            (function() {
                try {
                    if (
                        !window.skullPlayerReady ||
                        !window.skullPlayer
                    ) {
                        return JSON.stringify({ready: false});
                    }

                    var currentTime =
                        Number(window.skullPlayer.getCurrentTime());
                    var duration =
                        Number(window.skullPlayer.getDuration());
                    var state =
                        Number(window.skullPlayer.getPlayerState());

                    return JSON.stringify({
                        ready: true,
                        currentTime: Number.isFinite(currentTime)
                            ? currentTime : 0,
                        duration: Number.isFinite(duration)
                            ? duration : 0,
                        state: Number.isFinite(state) ? state : -1
                    });
                } catch (error) {
                    return JSON.stringify({
                        ready: false,
                        error: String(error)
                    });
                }
            })();
        """

        self._run_youtube_js(
            script,
            self._on_youtube_progress,
        )

    def _on_youtube_progress(self, result):
        self._youtube_update_pending = False

        if self.current_source != "online":
            return

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return

        if not isinstance(result, dict) or not result.get("ready", False):
            return

        try:
            current_time = max(
                0.0,
                float(result.get("currentTime", 0) or 0),
            )
            duration = max(
                0.0,
                float(result.get("duration", 0) or 0),
            )
            state = int(result.get("state", -1))
        except (TypeError, ValueError):
            return

        if duration > 0:
            self._last_online_duration = duration
            self.duration_label.setText(
                self.format_seconds(duration)
            )

            if not self.is_seeking:
                position = int(
                    max(
                        0,
                        min(1000, (current_time / duration) * 1000),
                    )
                )

                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(position)
                self.seek_slider.blockSignals(False)

        self.elapsed_label.setText(
            self.format_seconds(current_time)
        )

        if state == 1:
            self.play_button.setText("❚❚")
            self._track_ended = False

        elif state == 2:
            self.play_button.setText("▶")

        elif state == 0 and not self._track_ended:
            self._track_ended = True

            if len(self.online_tracks) > 1:
                self.next_track()
            else:
                self.play_button.setText("▶")

                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(0)
                self.seek_slider.blockSignals(False)

                self.elapsed_label.setText("0:00")

    # =========================================================
    # Seeking
    # =========================================================
    def start_seeking(self):
        self.is_seeking = True

    def finish_seeking(self):
        if self.current_source != "online":
            super().finish_seeking()
            return

        if self.current_online_track is None:
            self.is_seeking = False
            return

        position = max(
            0,
            min(1000, self.seek_slider.value()),
        )
        fraction = position / 1000.0
        self.is_seeking = True

        script = f"""
            (function() {{
                try {{
                    if (
                        !window.skullPlayerReady ||
                        !window.skullPlayer
                    ) {{
                        return JSON.stringify({{ready: false}});
                    }}

                    var duration =
                        Number(window.skullPlayer.getDuration());

                    if (!Number.isFinite(duration) || duration <= 0) {{
                        return JSON.stringify({{ready: false}});
                    }}

                    var target = duration * {fraction};
                    window.skullPlayer.seekTo(target, true);

                    return JSON.stringify({{
                        ready: true,
                        currentTime: target,
                        duration: duration
                    }});
                }} catch (error) {{
                    return JSON.stringify({{
                        ready: false,
                        error: String(error)
                    }});
                }}
            }})();
        """

        self._run_youtube_js(
            script,
            self._on_youtube_seek_complete,
        )

    def _on_youtube_seek_complete(self, result):
        if self.current_source != "online":
            return

        self.is_seeking = False

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return

        if not isinstance(result, dict) or not result.get("ready"):
            return

        try:
            current_time = max(
                0.0,
                float(result.get("currentTime", 0) or 0),
            )
            duration = max(
                0.0,
                float(result.get("duration", 0) or 0),
            )
        except (TypeError, ValueError):
            return

        self.elapsed_label.setText(
            self.format_seconds(current_time)
        )

        if duration > 0:
            self._last_online_duration = duration
            self.duration_label.setText(
                self.format_seconds(duration)
            )

            position = int(
                max(
                    0,
                    min(1000, (current_time / duration) * 1000),
                )
            )

            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(position)
            self.seek_slider.blockSignals(False)
