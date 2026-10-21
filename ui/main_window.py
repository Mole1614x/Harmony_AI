
import os
import base64
import re
import unicodedata
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import Picture

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.album_card import AlbumCard

try:
    import vlc
except (ImportError, OSError):
    vlc = None


class MainWindow(QMainWindow):
    AUDIO_EXTENSIONS = {
        ".mp3", ".wav", ".flac", ".m4a", ".aac",
        ".ogg", ".opus", ".wma", ".aiff", ".ape",
    }

    ARTWORK_SIZE = 64
    COLLECTION_ART_SIZE = 140

    def __init__(self):
        super().__init__()

        self.setWindowTitle("SkullCandy")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)

        self.sample_albums = [
            ("Midnight Echoes", "Nova Lane", "#49364f"),
            ("Golden Hour", "The Sundrops", "#77533e"),
            ("Neon Dreams", "Luna Waves", "#354b70"),
            ("After the Rain", "River North", "#3d665c"),
            ("Electric Soul", "The Frequencies", "#70404f"),
            ("Blue Horizon", "Atlas Skies", "#3e5979"),
            ("Quiet Moments", "Mira Sol", "#625c4a"),
            ("City Lights", "Night Avenue", "#5c3f68"),
        ]

        # Local music collection
        self.music_files = []
        self.current_track_index = -1
        self.track_metadata = {}
        self.artwork_cache = {}

        # Browsing state
        self.current_page = "Listen Now"
        self.collection_tracks = None
        self.collection_title = ""

        # Playback state
        self.is_seeking = False
        self._track_ended = False
        self.shuffle_enabled = False
        self.repeat_mode = 0  # 0=off, 1=repeat all, 2=repeat one
        self._liked_paths = set()
        self.vlc_instance = None
        self.audio_player = None
        self.audio_error = None

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # ---------------- Sidebar ----------------
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 24, 20, 20)
        sidebar_layout.setSpacing(12)

        logo = QLabel("♫ SkullCandy")
        logo.setObjectName("logo")
        sidebar_layout.addWidget(logo)
        sidebar_layout.addSpacing(20)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}

        for name in [
            "Listen Now", "Discover", "Search", "Albums",
            "Artists", "Playlists", "Your Library",
        ]:
            button = QPushButton(name)
            button.setObjectName("navButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setCheckable(True)

            self.nav_group.addButton(button)
            self.nav_buttons[name] = button
            sidebar_layout.addWidget(button)

            button.clicked.connect(
                lambda checked=False, page=name: self.show_page(page)
            )

        self.nav_buttons["Listen Now"].setChecked(True)

        sidebar_layout.addSpacing(12)

        self.add_music_button = QPushButton("+  Add Music")
        self.add_music_button.setObjectName("addMusicButton")
        self.add_music_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.add_music_button.clicked.connect(self.add_music_files)
        sidebar_layout.addWidget(self.add_music_button)
        sidebar_layout.addStretch()

        # ---------------- Main content ----------------
        self.main_area = QWidget()
        self.main_layout = QVBoxLayout(self.main_area)
        self.main_layout.setContentsMargins(32, 28, 32, 24)
        self.main_layout.setSpacing(16)

        self.heading = QLabel("Listen Now")
        self.heading.setObjectName("heading")
        self.main_layout.addWidget(self.heading)

        self.subtitle = QLabel(
            "Your music library and personalized discoveries."
        )
        self.subtitle.setObjectName("subtitle")
        self.main_layout.addWidget(self.subtitle)

        # Search controls: shown only on the Search page
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText(
            "Search songs, artists, or albums..."
        )
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.setMinimumHeight(44)
        self.search_bar.textChanged.connect(self.search_library)
        self.search_bar.hide()
        self.main_layout.addWidget(self.search_bar)

        self.search_hint = QLabel(
            "Search across your imported local music."
        )
        self.search_hint.setObjectName("subtitle")
        self.search_hint.hide()
        self.main_layout.addWidget(self.search_hint)

        # Featured banner
        self.featured_banner = QFrame()
        self.featured_banner.setObjectName("featuredBanner")
        self.featured_banner.setMinimumHeight(165)
        self.featured_banner.setMaximumHeight(185)

        banner_layout = QVBoxLayout(self.featured_banner)
        banner_layout.setContentsMargins(24, 20, 24, 20)
        banner_layout.setSpacing(8)

        banner_tag = QLabel("YOUR PERSONAL MUSIC SPACE")
        banner_tag.setObjectName("bannerTag")
        banner_layout.addWidget(banner_tag)

        banner_title = QLabel("Your Sound, Your World")
        banner_title.setObjectName("bannerTitle")
        banner_layout.addWidget(banner_title)

        banner_description = QLabel(
            "Discover music. Find your sound. Build your collection."
        )
        banner_description.setObjectName("bannerDescription")
        banner_layout.addWidget(banner_description)
        banner_layout.addStretch()

        self.main_layout.addWidget(self.featured_banner)

        self.section_heading = QLabel("Made for Your Taste")
        self.section_heading.setObjectName("sectionHeading")
        self.main_layout.addWidget(self.section_heading)

        self.description = QLabel(
            "Discover music selected for your listening experience."
        )
        self.description.setObjectName("subtitle")
        self.description.setWordWrap(True)
        self.main_layout.addWidget(self.description)

        # Album and artist cards
        self.album_scroll = QScrollArea()
        self.album_scroll.setObjectName("albumScroll")
        self.album_scroll.setWidgetResizable(True)
        self.album_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.album_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.album_container = QWidget()
        self.album_container.setObjectName("albumContainer")

        self.album_grid = QGridLayout(self.album_container)
        self.album_grid.setContentsMargins(0, 8, 0, 12)
        self.album_grid.setHorizontalSpacing(20)
        self.album_grid.setVerticalSpacing(24)
        self.album_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.album_scroll.setWidget(self.album_container)
        self.main_layout.addWidget(self.album_scroll, 1)

        # Track list used by Search, Albums, Artists, and Your Library
        self.library_list = QListWidget()
        self.library_list.setObjectName("libraryList")
        self.library_list.setSpacing(5)
        self.library_list.itemDoubleClicked.connect(
            self.play_selected_library_track
        )
        self.library_list.hide()
        self.main_layout.addWidget(self.library_list, 1)

        content.addWidget(sidebar)
        content.addWidget(self.main_area, 1)
        root.addLayout(content, 1)

        # ---------------- Bottom player ----------------
        player_bar = QFrame()
        player_bar.setObjectName("playerBar")
        player_bar.setFixedHeight(104)

        player_layout = QHBoxLayout(player_bar)
        player_layout.setContentsMargins(24, 8, 24, 8)
        player_layout.setSpacing(16)

        self.album_cover = QLabel()
        self.album_cover.setObjectName("albumCover")
        self.album_cover.setFixedSize(
            self.ARTWORK_SIZE, self.ARTWORK_SIZE
        )
        self.album_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_placeholder_artwork()

        self.track_info = QLabel("No track selected")
        self.track_info.setObjectName("trackInfo")
        self.track_info.setMinimumWidth(0)
        self.track_info.setWordWrap(True)
        self.track_info.setAlignment(
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter
        )
        self.track_info.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        track_details = QWidget()
        track_details.setObjectName("trackDetails")
        track_details.setFixedWidth(285)

        track_details_layout = QHBoxLayout(track_details)
        track_details_layout.setContentsMargins(0, 0, 0, 0)
        track_details_layout.setSpacing(12)
        track_details_layout.addWidget(self.album_cover)
        track_details_layout.addWidget(self.track_info, 1)
        player_layout.addWidget(track_details)

        # Playback controls
        center_player = QWidget()
        center_player.setObjectName("centerPlayer")
        center_player.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        center_layout = QVBoxLayout(center_player)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(16)
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.shuffle_button = QPushButton("🔀")
        self.previous_button = QPushButton("⏮")
        self.play_button = QPushButton("▶")
        self.next_button = QPushButton("⏭")
        self.repeat_button = QPushButton("↻")

        self.shuffle_button.setObjectName("modeButton")
        self.repeat_button.setObjectName("modeButton")
        self.previous_button.setObjectName("skipButton")
        self.play_button.setObjectName("playButton")
        self.next_button.setObjectName("skipButton")

        self.shuffle_button.setFixedSize(34, 34)
        self.previous_button.setFixedSize(38, 38)
        self.play_button.setFixedSize(42, 42)
        self.next_button.setFixedSize(38, 38)
        self.repeat_button.setFixedSize(34, 34)
        self.shuffle_button.setCheckable(True)
        self.repeat_button.setCheckable(True)
        self.shuffle_button.setToolTip("Shuffle")
        self.repeat_button.setToolTip("Repeat off")

        self.shuffle_button.clicked.connect(self.toggle_shuffle)
        self.repeat_button.clicked.connect(self.cycle_repeat_mode)
        self.previous_button.clicked.connect(self.previous_track)
        self.play_button.clicked.connect(self.toggle_play_button)
        self.next_button.clicked.connect(self.next_track)

        controls_layout.addWidget(self.previous_button)
        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.next_button)

        seek_layout = QHBoxLayout()
        seek_layout.setContentsMargins(0, 0, 0, 0)
        seek_layout.setSpacing(8)

        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("timeLabel")
        self.elapsed_label.setFixedWidth(36)
        self.elapsed_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setObjectName("seekSlider")
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setFixedHeight(18)
        self.seek_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.seek_slider.sliderPressed.connect(self.start_seeking)
        self.seek_slider.sliderReleased.connect(self.finish_seeking)

        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("timeLabel")
        self.duration_label.setFixedWidth(36)

        seek_layout.addWidget(self.elapsed_label)
        seek_layout.addWidget(self.seek_slider, 1)
        seek_layout.addWidget(self.duration_label)

        center_layout.addStretch(1)
        center_layout.addLayout(controls_layout)
        center_layout.addLayout(seek_layout)
        center_layout.addStretch(1)

        player_layout.addWidget(center_player, 1)

        # Volume
        volume_widget = QWidget()
        volume_widget.setObjectName("volumeWidget")
        volume_widget.setFixedWidth(180)

        volume_layout = QVBoxLayout(volume_widget)
        volume_layout.setContentsMargins(0, 2, 0, 2)
        volume_layout.setSpacing(8)

        # Apple Music-inspired utility row: Like, Shuffle, Repeat above volume.
        utility_row = QHBoxLayout()
        utility_row.setContentsMargins(0, 0, 0, 0)
        utility_row.setSpacing(10)
        utility_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.like_button = QPushButton("♡")
        self.like_button.setObjectName("likeButton")
        self.like_button.setToolTip("Add to Favorites")
        self.like_button.setFixedSize(30, 30)
        self.like_button.clicked.connect(self.toggle_current_like)

        utility_row.addWidget(self.like_button)
        utility_row.addWidget(self.shuffle_button)
        utility_row.addWidget(self.repeat_button)
        volume_layout.addLayout(utility_row)

        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.setSpacing(6)

        volume_label = QLabel("Volume")
        volume_label.setObjectName("volumeLabel")
        volume_label.setFixedWidth(42)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(118)
        self.volume_slider.setFixedHeight(18)
        self.volume_slider.valueChanged.connect(self.change_volume)

        volume_row.addWidget(volume_label)
        volume_row.addWidget(self.volume_slider)
        volume_layout.addLayout(volume_row)

        player_layout.addWidget(volume_widget)
        root.addWidget(player_bar)

        self.initialize_audio()

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(250)
        self.playback_timer.timeout.connect(
            self.update_playback_position
        )
        self.playback_timer.start()

        self.apply_styles()
        self.load_music_from_folder()
        self.show_page("Listen Now")

    # =========================================================
    # Metadata
    # =========================================================
    @staticmethod
    def _tag_text(tags, *keys):
        if tags is None:
            return ""

        for key in keys:
            try:
                value = tags.get(key)
            except (AttributeError, TypeError):
                value = None

            if value is None:
                continue

            if isinstance(value, (list, tuple)):
                value = value[0] if value else ""

            value = str(value).strip()

            if value:
                return value

        return ""

    def get_track_metadata(self, path):
        path = str(Path(path).resolve())

        if path in self.track_metadata:
            return self.track_metadata[path]

        metadata = {
            "path": path,
            "title": Path(path).stem,
            "artist": "Unknown Artist",
            "album_artist": "Unknown Artist",
            "album": "Unknown Album",
            "genre": "Unknown Genre",
            "date": "",
            "track_number": "",
            "duration": 0.0,
        }

        try:
            audio = MutagenFile(path, easy=True)

            if audio is not None:
                tags = audio.tags

                metadata["title"] = (
                    self._tag_text(tags, "title")
                    or Path(path).stem
                )
                metadata["artist"] = (
                    self._tag_text(tags, "artist")
                    or "Unknown Artist"
                )
                metadata["album_artist"] = (
                    self._tag_text(tags, "albumartist", "artist")
                    or "Unknown Artist"
                )
                metadata["album"] = (
                    self._tag_text(tags, "album")
                    or "Unknown Album"
                )
                metadata["genre"] = (
                    self._tag_text(tags, "genre")
                    or "Unknown Genre"
                )
                metadata["date"] = self._tag_text(
                    tags, "date", "originaldate", "year"
                )
                metadata["track_number"] = self._tag_text(
                    tags, "tracknumber"
                )

                if audio.info is not None:
                    metadata["duration"] = float(
                        getattr(audio.info, "length", 0.0) or 0.0
                    )

        except Exception as exc:
            print(f"Could not read metadata for {path}: {exc}")

        self.track_metadata[path] = metadata
        return metadata

    @staticmethod
    def _normalize_track_text(value):
        """Normalize tags so spacing, punctuation, and Unicode variants match."""
        value = unicodedata.normalize("NFKC", str(value or "")).casefold()
        value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
        return " ".join(value.split())

    @classmethod
    def _track_metadata_is_duplicate(cls, first, second):
        """Compare track metadata without merging obvious different versions."""
        first_title = cls._normalize_track_text(first.get("title"))
        second_title = cls._normalize_track_text(second.get("title"))
        if not first_title or first_title != second_title:
            return False

        unknown_artists = {"", "unknown", "unknown artist", "various artists"}
        first_artist = cls._normalize_track_text(
            first.get("artist") or first.get("album_artist")
        )
        second_artist = cls._normalize_track_text(
            second.get("artist") or second.get("album_artist")
        )
        if (
            first_artist not in unknown_artists
            and second_artist not in unknown_artists
            and first_artist != second_artist
        ):
            return False

        unknown_albums = {"", "unknown", "unknown album"}
        first_album = cls._normalize_track_text(first.get("album"))
        second_album = cls._normalize_track_text(second.get("album"))
        if (
            first_album not in unknown_albums
            and second_album not in unknown_albums
            and first_album != second_album
        ):
            return False

        # Preserve separately numbered tracks when both files have valid,
        # different track numbers (e.g. a repeated song on a deluxe album).
        def track_number(value):
            value = str(value or "").strip().split("/", 1)[0]
            return int(value) if value.isdigit() else None

        first_number = track_number(first.get("track_number"))
        second_number = track_number(second.get("track_number"))
        if (
            first_number is not None
            and second_number is not None
            and first_number != second_number
        ):
            return False

        try:
            first_duration = float(first.get("duration") or 0)
            second_duration = float(second.get("duration") or 0)
        except (TypeError, ValueError):
            first_duration = second_duration = 0.0

        if first_duration > 0 and second_duration > 0:
            if abs(first_duration - second_duration) > 3.0:
                return False

        return True

    def _find_duplicate_track_index(self, metadata, indices=None):
        """Find a duplicate among queue indices, optionally in a collection."""
        candidates = (
            range(len(self.music_files)) if indices is None else indices
        )
        for index in candidates:
            if not 0 <= index < len(self.music_files):
                continue
            existing = self.get_track_metadata(self.music_files[index])
            if self._track_metadata_is_duplicate(metadata, existing):
                return index
        return None

    @staticmethod
    def format_seconds(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    # =========================================================
    # Artwork
    # =========================================================
    def set_placeholder_artwork(self):
        self.album_cover.setPixmap(QPixmap())
        self.album_cover.setText("♫")
        self.album_cover.setToolTip("No embedded album artwork")

    def extract_album_artwork(self, path):
        path = str(Path(path).resolve())

        if path in self.artwork_cache:
            return self.artwork_cache[path]

        artwork = None

        try:
            audio = MutagenFile(path)

            if audio is not None:
                tags = audio.tags

                if tags is not None and hasattr(tags, "getall"):
                    pictures = tags.getall("APIC")
                    if pictures:
                        artwork = pictures[0].data

                if artwork is None:
                    pictures = getattr(audio, "pictures", None)
                    if pictures:
                        artwork = pictures[0].data

                if artwork is None and tags is not None:
                    try:
                        covers = tags.get("covr", [])
                        if covers:
                            artwork = bytes(covers[0])
                    except (AttributeError, TypeError, ValueError):
                        pass

                if artwork is None and tags is not None:
                    encoded_pictures = tags.get(
                        "metadata_block_picture", []
                    )

                    if isinstance(encoded_pictures, str):
                        encoded_pictures = [encoded_pictures]

                    for encoded in encoded_pictures:
                        try:
                            picture = Picture(
                                base64.b64decode(encoded)
                            )
                            artwork = picture.data
                            if artwork:
                                break
                        except Exception:
                            continue

        except Exception as exc:
            print(f"Could not extract artwork from {path}: {exc}")

        self.artwork_cache[path] = artwork
        return artwork

    def update_album_artwork(self, path):
        artwork = self.extract_album_artwork(path)

        if not artwork:
            self.set_placeholder_artwork()
            return

        pixmap = QPixmap()

        if not pixmap.loadFromData(artwork):
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

    def get_collection_pixmap(self, path):
        artwork = self.extract_album_artwork(path)
        pixmap = QPixmap()

        if artwork and pixmap.loadFromData(artwork):
            return pixmap.scaled(
                self.COLLECTION_ART_SIZE,
                self.COLLECTION_ART_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        placeholder = QPixmap(
            self.COLLECTION_ART_SIZE,
            self.COLLECTION_ART_SIZE,
        )
        placeholder.fill(Qt.GlobalColor.darkGray)
        return placeholder

    # =========================================================
    # VLC audio engine
    # =========================================================
    def initialize_audio(self):
        if vlc is None:
            self.audio_error = (
                "python-vlc or the VLC native libraries could not load."
            )
            return

        try:
            self.vlc_instance = vlc.Instance("--no-video", "--quiet")

            if self.vlc_instance is None:
                raise RuntimeError("Could not create a VLC instance.")

            self.audio_player = self.vlc_instance.media_player_new()
            self.audio_player.audio_set_volume(
                self.volume_slider.value()
            )

        except Exception as exc:
            self.audio_error = str(exc)
            self.vlc_instance = None
            self.audio_player = None

    def ensure_audio_backend(self):
        if self.audio_player is not None:
            return True

        QMessageBox.warning(
            self,
            "Audio engine unavailable",
            "SkullCandy could not initialize VLC playback.\n\n"
            f"{self.audio_error or 'Unknown VLC error.'}\n\n"
            "Install VLC on your Mac and restart SkullCandy.",
        )
        return False

    # =========================================================
    # Import music
    # =========================================================
    def load_music_from_folder(self):
        music_folder = Path(__file__).resolve().parent.parent / "music"

        if not music_folder.is_dir():
            return

        files = [
            str(path.resolve())
            for path in sorted(music_folder.iterdir())
            if path.is_file()
            and path.suffix.lower() in self.AUDIO_EXTENSIONS
        ]

        self.add_tracks_to_queue(files, show_message=False)

    def add_music_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Music to SkullCandy",
            str(Path.home()),
            (
                "Audio Files (*.mp3 *.wav *.flac *.m4a *.aac "
                "*.ogg *.opus *.wma *.aiff *.ape);;"
                "All Files (*)"
            ),
        )

        if files:
            self.add_tracks_to_queue(files, show_message=True)

    def add_tracks_to_queue(self, files, show_message=True):
        """Import unique paths and avoid duplicate tagged copies of a track."""
        existing_paths = {
            os.path.normcase(os.path.realpath(path)).casefold()
            for path in self.music_files
        }

        added = []
        duplicates = []
        unsupported = []

        for path in files:
            candidate = Path(path).expanduser()

            try:
                if not candidate.is_file():
                    continue
            except OSError:
                continue

            if candidate.suffix.lower() not in self.AUDIO_EXTENSIONS:
                unsupported.append(candidate.name)
                continue

            try:
                resolved = str(candidate.resolve())
            except OSError:
                resolved = str(candidate.absolute())

            normalized_path = os.path.normcase(
                os.path.realpath(resolved)
            ).casefold()

            if normalized_path in existing_paths:
                duplicates.append(candidate.name)
                continue

            metadata = self.get_track_metadata(resolved)
            if self._find_duplicate_track_index(metadata) is not None:
                duplicates.append(candidate.name)
                # Do not put the second copy in the queue. This fixes the
                # source data used by Your Library, Albums, Artists, and search.
                continue

            self.music_files.append(resolved)
            existing_paths.add(normalized_path)
            added.append(resolved)

        if self.current_track_index == -1 and self.music_files:
            self.current_track_index = 0
            self.update_track_info()

        self.refresh_library_list()
        self.populate_albums()

        if not show_message:
            return

        if added:
            message = f"Added {len(added)} track(s)."
            if duplicates:
                message += (
                    "\n\nSkipped duplicates: " + ", ".join(duplicates)
                )
            if unsupported:
                message += (
                    "\n\nUnsupported files: " + ", ".join(unsupported)
                )
            QMessageBox.information(self, "Music added", message)
        else:
            QMessageBox.information(
                self,
                "No new tracks",
                "No new tracks were added. The selected files may already "
                "be in your library, be duplicate copies, or use unsupported formats.",
            )

    # =========================================================
    # Search
    # =========================================================
    def search_library(self, query):
        """Search title, artist, album, and file name as-you-type."""
        if self.current_page != "Search":
            return

        query = query.strip().casefold()
        matches = []

        for index, path in enumerate(self.music_files):
            metadata = self.get_track_metadata(path)

            searchable_text = " ".join([
                metadata["title"],
                metadata["artist"],
                metadata["album_artist"],
                metadata["album"],
                Path(path).name,
            ]).casefold()

            if not query or query in searchable_text:
                matches.append(index)

        self.collection_tracks = matches
        self.refresh_library_list()

        if not self.music_files:
            self.search_hint.setText(
                "Your library is empty. Click Add Music to import songs."
            )
        elif not query:
            self.search_hint.setText(
                f"{len(self.music_files)} track(s) available. "
                "Type a song, artist, or album name."
            )
        elif matches:
            self.search_hint.setText(
                f"{len(matches)} result(s) for “{query}”."
            )
        else:
            self.search_hint.setText(
                f"No results for “{query}”. Try another title, "
                "artist, or album."
            )

    # =========================================================
    # Real albums and artists
    # =========================================================
    def get_album_groups(self):
        groups = {}

        for index, path in enumerate(self.music_files):
            metadata = self.get_track_metadata(path)
            album_artist = metadata.get("album_artist") or metadata.get("artist") or "Unknown Artist"
            album_title = metadata.get("album") or "Unknown Album"
            key = (
                self._normalize_track_text(album_artist),
                self._normalize_track_text(album_title),
            )

            if key not in groups:
                groups[key] = {
                    "title": album_title.strip() or "Unknown Album",
                    "artist": album_artist.strip() or "Unknown Artist",
                    "tracks": [],
                    "cover_path": path,
                }

            # Defensive display-level filtering also protects this page if a
            # duplicate was restored into the queue by another code path.
            if self._find_duplicate_track_index(
                metadata, indices=groups[key]["tracks"]
            ) is None:
                groups[key]["tracks"].append(index)

            if not self.extract_album_artwork(
                groups[key]["cover_path"]
            ) and self.extract_album_artwork(path):
                groups[key]["cover_path"] = path

        return sorted(
            groups.values(),
            key=lambda item: (
                self._normalize_track_text(item["artist"]),
                self._normalize_track_text(item["title"]),
            ),
        )

    def get_artist_groups(self):
        groups = {}

        for index, path in enumerate(self.music_files):
            metadata = self.get_track_metadata(path)
            artist = metadata.get("album_artist") or "Unknown Artist"

            if self._normalize_track_text(artist) in {
                "", "unknown artist", "unknown"
            }:
                artist = metadata.get("artist") or "Unknown Artist"

            key = self._normalize_track_text(artist)

            if key not in groups:
                groups[key] = {
                    "title": artist.strip() or "Unknown Artist",
                    "tracks": [],
                    "cover_path": path,
                }

            if self._find_duplicate_track_index(
                metadata, indices=groups[key]["tracks"]
            ) is None:
                groups[key]["tracks"].append(index)

            if not self.extract_album_artwork(
                groups[key]["cover_path"]
            ) and self.extract_album_artwork(path):
                groups[key]["cover_path"] = path

        return sorted(
            groups.values(),
            key=lambda item: self._normalize_track_text(item["title"]),
        )

    def create_collection_card(self, title, subtitle, cover_path, callback):
        card = QToolButton()
        card.setObjectName("collectionCard")
        card.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(180, 215)

        pixmap = self.get_collection_pixmap(cover_path)
        card.setIcon(QIcon(pixmap))
        card.setIconSize(pixmap.size())
        card.setText(f"{title}\n{subtitle}")
        card.setToolTip(f"{title}\n{subtitle}")

        card.clicked.connect(callback)
        return card

    def show_collection_tracks(self, title, track_indices):
        self.collection_title = title
        self.collection_tracks = list(track_indices)

        self.heading.setText(title)
        self.subtitle.setText("Double-click a track to play it.")
        self.section_heading.hide()
        self.featured_banner.hide()
        self.album_scroll.hide()
        self.search_bar.hide()
        self.search_hint.hide()

        self.description.show()
        self.description.setText(
            f"{len(self.collection_tracks)} track(s)"
        )

        self.library_list.show()
        self.refresh_library_list()

    def populate_albums(self):
        if not hasattr(self, "album_grid"):
            return

        while self.album_grid.count():
            item = self.album_grid.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        columns = max(
            1, self.album_scroll.viewport().width() // 200
        )

        if self.current_page == "Albums":
            albums = self.get_album_groups()

            if not albums:
                self.add_empty_collection_message(
                    "No albums yet",
                    "Add local music to see your albums here.",
                )
                return

            for index, album in enumerate(albums):
                card = self.create_collection_card(
                    album["title"],
                    album["artist"],
                    album["cover_path"],
                    lambda checked=False, item=album:
                        self.show_collection_tracks(
                            item["title"], item["tracks"]
                        ),
                )
                self.album_grid.addWidget(
                    card, index // columns, index % columns
                )

        elif self.current_page == "Artists":
            artists = self.get_artist_groups()

            if not artists:
                self.add_empty_collection_message(
                    "No artists yet",
                    "Add local music to discover your artists here.",
                )
                return

            for index, artist in enumerate(artists):
                count = len(artist["tracks"])
                subtitle = f"{count} track(s)"

                card = self.create_collection_card(
                    artist["title"],
                    subtitle,
                    artist["cover_path"],
                    lambda checked=False, item=artist:
                        self.show_collection_tracks(
                            item["title"], item["tracks"]
                        ),
                )
                self.album_grid.addWidget(
                    card, index // columns, index % columns
                )

        elif self.current_page == "Listen Now":
            # PersistentMainWindow supplies database-backed recommendations.
            # If no recommendation provider is available, show real local
            # library tracks rather than fabricated demo albums.
            if self.populate_recommendations(columns):
                return

            if not self.music_files:
                self.add_empty_collection_message(
                    "Your library is empty",
                    "No playable local songs were found in your music database/library. "
                    "Import music or check that the database paths point to existing files.",
                )
                return

            for index, path in enumerate(self.music_files):
                metadata = self.get_track_metadata(path)
                card = self.create_collection_card(
                    metadata["title"],
                    metadata["artist"],
                    path,
                    lambda checked=False, track_index=index:
                        self.play_track(track_index),
                )
                self.album_grid.addWidget(
                    card, index // columns, index % columns
                )

        else:
            self.add_empty_collection_message(
                "Nothing to show yet",
                "This section will display content when it is available.",
            )

    def populate_recommendations(self, columns=None):
        """Hook for database-aware subclasses to populate Listen Now cards.

        Return True when a subclass populated the recommendation grid.
        The base window returns False so Listen Now falls back to real local
        tracks from the application's loaded library.
        """
        return False

    def add_empty_collection_message(self, title, message):
        empty_widget = QWidget()
        layout = QVBoxLayout(empty_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(20, 30, 20, 20)

        title_label = QLabel(title)
        title_label.setObjectName("sectionHeading")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        message_label = QLabel(message)
        message_label.setObjectName("subtitle")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(message_label)

        self.album_grid.addWidget(empty_widget, 0, 0, 1, 3)

    # =========================================================
    # Track list
    # =========================================================
    def refresh_library_list(self):
        if not hasattr(self, "library_list"):
            return

        self.library_list.clear()

        if self.collection_tracks is None:
            indices = list(range(len(self.music_files)))
        else:
            indices = list(self.collection_tracks)

        visible_indices = []
        for index in indices:
            if not 0 <= index < len(self.music_files):
                continue
            metadata = self.get_track_metadata(self.music_files[index])
            if self._find_duplicate_track_index(
                metadata, indices=visible_indices
            ) is None:
                visible_indices.append(index)

        for index in visible_indices:
            path = self.music_files[index]
            metadata = self.get_track_metadata(path)

            title = metadata["title"]
            artist = metadata["artist"]
            album = metadata["album"]
            duration = self.format_seconds(metadata["duration"])

            if index == self.current_track_index:
                display = (
                    f"♫  {title}  —  NOW PLAYING\n"
                    f"     {artist}  •  {album}  •  {duration}"
                )
            else:
                display = (
                    f"♫  {title}\n"
                    f"     {artist}  •  {album}  •  {duration}"
                )

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(
                f"Title: {title}\n"
                f"Artist: {artist}\n"
                f"Album: {album}\n"
                f"Duration: {duration}\n"
                f"File: {path}"
            )

            self.library_list.addItem(item)

    def play_selected_library_track(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)

        if index is not None:
            self.play_track(int(index))

    # =========================================================
    # Navigation
    # =========================================================
    def show_page(self, page):
        self.current_page = page
        self.collection_tracks = None
        self.collection_title = ""

        self.heading.setText(page)

        subtitles = {
            "Listen Now": "Your music library and personalized recommendations.",
            "Discover": "Explore online music and discover new artists.",
            "Search": "Search your local music collection.",
            "Albums": "Browse albums in your local collection.",
            "Artists": "Explore artists in your collection.",
            "Playlists": "Organize your music into playlists.",
            "Your Library": "Your imported local audio files.",
            "Favorites": "Your favorite tracks.",
            "History": "Your recently played tracks.",
        }

        sections = {
            "Listen Now": "Made for Your Taste",
            "Discover": "Discover New Music",
            "Search": "Search Results",
            "Albums": "Your Albums",
            "Artists": "Your Artists",
            "Playlists": "Your Playlists",
            "Your Library": "Your Music Library",
            "Favorites": "Your Favorites",
            "History": "Recently Played",
        }

        # Navigation may be extended by PersistentMainWindow. Unknown page
        # names should never crash the base window with a KeyError.
        self.subtitle.setText(subtitles.get(page, f"Browse {page.lower()}."))
        self.section_heading.setText(sections.get(page, page))

        show_cards = page in (
            "Listen Now", "Discover", "Albums", "Artists"
        )
        show_library = page == "Your Library"
        show_search = page == "Search"

        self.featured_banner.setVisible(page == "Listen Now")
        self.section_heading.setVisible(show_cards)
        self.album_scroll.setVisible(show_cards)
        self.library_list.setVisible(show_library or show_search)
        self.search_bar.setVisible(show_search)
        self.search_hint.setVisible(show_search)

        self.description.setVisible(
            not show_cards and not show_library and not show_search
        )

        if page == "Albums":
            self.description.setText(
                f"{len(self.get_album_groups())} album(s) in your library."
            )

        elif page == "Artists":
            self.description.setText(
                f"{len(self.get_artist_groups())} artist(s) in your library."
            )

        elif page == "Your Library":
            self.description.setText(
                f"{len(self.music_files)} track(s) in your library."
            )
            self.description.setVisible(True)
            self.refresh_library_list()

        elif page == "Search":
            self.search_bar.setFocus()
            self.search_library(self.search_bar.text())

        elif page == "Playlists":
            self.description.setText(
                "Playlist management will be added in a later step."
            )
            self.description.setVisible(True)

        if show_cards:
            self.populate_albums()

    # =========================================================
    # Playback
    # =========================================================
    def toggle_play_button(self):
        if not self.ensure_audio_backend():
            return

        if not self.music_files:
            self.add_music_files()
            if not self.music_files:
                return

        if self.current_track_index < 0:
            self.play_track(0)
            return

        try:
            state = self.audio_player.get_state()

            if state == vlc.State.Playing:
                self.audio_player.pause()
                self.play_button.setText("▶")
                return

            if state == vlc.State.Paused:
                self.audio_player.set_pause(0)
                self.play_button.setText("❚❚")
                return

            if state == vlc.State.Ended:
                self.play_track(self.current_track_index)
                return

            if self.audio_player.get_media() is None:
                self.play_track(self.current_track_index)
                return

            result = self.audio_player.play()

            if result == -1:
                self.show_playback_error(
                    "VLC could not start this track."
                )
                return

            self.play_button.setText("❚❚")

        except Exception as exc:
            self.show_playback_error(str(exc))

    def play_track(self, index):
        if not self.ensure_audio_backend():
            return

        if not 0 <= index < len(self.music_files):
            return

        path = self.music_files[index]

        if not os.path.isfile(path):
            QMessageBox.warning(
                self, "File not found",
                f"The audio file no longer exists:\n{path}",
            )
            return

        try:
            media = self.vlc_instance.media_new_path(path)
            self.audio_player.set_media(media)
            self.audio_player.audio_set_volume(
                self.volume_slider.value()
            )

            if self.audio_player.play() == -1:
                self.show_playback_error(
                    "VLC could not start this file. Check the file "
                    "format and whether the file is playable."
                )
                return

            self.current_track_index = index
            self._track_ended = False
            self.is_seeking = False

            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(0)
            self.seek_slider.blockSignals(False)

            self.elapsed_label.setText("0:00")

            metadata = self.get_track_metadata(path)
            self.duration_label.setText(
                self.format_seconds(metadata["duration"])
            )

            self.update_track_info()
            self.refresh_like_button(str(Path(path).resolve()))
            self.update_album_artwork(path)
            self.play_button.setText("❚❚")
            self.refresh_library_list()

        except Exception as exc:
            self.show_playback_error(str(exc))

    def next_track(self):
        if not self.music_files:
            self.add_music_files()
            if not self.music_files:
                return

        if self.repeat_mode == 2 and self.current_track_index >= 0:
            self.play_track(self.current_track_index)
            return

        if self.shuffle_enabled and len(self.music_files) > 1:
            import random
            choices = [i for i in range(len(self.music_files)) if i != self.current_track_index]
            index = random.choice(choices)
        else:
            index = (
                0 if self.current_track_index < 0
                else self.current_track_index + 1
            )
            if index >= len(self.music_files):
                if self.repeat_mode == 1:
                    index = 0
                else:
                    self.play_button.setText("▶")
                    return
        self.play_track(index)

    def previous_track(self):
        if not self.music_files:
            return

        if (
            self.audio_player is not None
            and self.audio_player.get_time() > 3000
        ):
            self.audio_player.set_time(0)
            self._track_ended = False
            return

        index = (
            0 if self.current_track_index < 0
            else (self.current_track_index - 1) % len(self.music_files)
        )
        self.play_track(index)

    def change_volume(self, value):
        if self.audio_player is not None:
            self.audio_player.audio_set_volume(value)

    # =========================================================
    # Seek and timing
    # =========================================================
    def start_seeking(self):
        self.is_seeking = True

    def finish_seeking(self):
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

    def update_playback_position(self):
        if self.audio_player is None or not self.music_files:
            return

        try:
            state = self.audio_player.get_state()

            if state == vlc.State.Ended and not self._track_ended:
                self._track_ended = True

                if self.repeat_mode == 2:
                    self.play_track(self.current_track_index)
                elif self.shuffle_enabled or self.repeat_mode == 1:
                    self.next_track()
                elif self.current_track_index + 1 < len(self.music_files):
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

    @staticmethod
    def format_time(milliseconds):
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60}:{seconds % 60:02d}"

    def toggle_shuffle(self):
        self.shuffle_enabled = self.shuffle_button.isChecked()
        self.shuffle_button.setProperty("active", self.shuffle_enabled)
        self.shuffle_button.style().unpolish(self.shuffle_button)
        self.shuffle_button.style().polish(self.shuffle_button)
        self.shuffle_button.setToolTip("Shuffle on" if self.shuffle_enabled else "Shuffle off")

    def cycle_repeat_mode(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        labels = {0: "Repeat off", 1: "Repeat all", 2: "Repeat one"}
        symbols = {0: "↻", 1: "↻", 2: "↻¹"}
        self.repeat_button.setText(symbols[self.repeat_mode])
        self.repeat_button.setToolTip(labels[self.repeat_mode])
        self.repeat_button.setChecked(self.repeat_mode != 0)
        self.repeat_button.setProperty("active", self.repeat_mode != 0)
        self.repeat_button.style().unpolish(self.repeat_button)
        self.repeat_button.style().polish(self.repeat_button)

    def toggle_current_like(self):
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
        self.like_button.style().polish(self.like_button)

    def update_track_info(self):
        if not 0 <= self.current_track_index < len(self.music_files):
            self.track_info.setText("No track selected")
            self.set_placeholder_artwork()
            return

        path = self.music_files[self.current_track_index]
        metadata = self.get_track_metadata(path)

        self.track_info.setText(
            f"{metadata['title']}\n{metadata['artist']}"
        )
        self.track_info.setToolTip(
            f"Title: {metadata['title']}\n"
            f"Artist: {metadata['artist']}\n"
            f"Album: {metadata['album']}\n"
            f"File: {path}"
        )
        self.update_album_artwork(path)

    def show_playback_error(self, message):
        self.play_button.setText("▶")
        QMessageBox.warning(self, "Playback error", message)

    # =========================================================
    # Resize and cleanup
    # =========================================================
    def resizeEvent(self, event):
        super().resizeEvent(event)

        if (
            hasattr(self, "album_scroll")
            and self.current_page in (
                "Listen Now", "Discover", "Albums", "Artists"
            )
        ):
            self.populate_albums()

    def closeEvent(self, event):
        if hasattr(self, "playback_timer"):
            self.playback_timer.stop()

        if self.audio_player is not None:
            self.audio_player.stop()
            self.audio_player.release()
            self.audio_player = None

        if self.vlc_instance is not None:
            self.vlc_instance.release()
            self.vlc_instance = None

        super().closeEvent(event)

    # =========================================================
    # Styles
    # =========================================================
    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #17171c;
                color: #f5f5f7;
                font-family: Arial;
                font-size: 14px;
            }

            QFrame#sidebar {
                background-color: #202026;
                border: none;
                border-right: 1px solid #303038;
            }

            QFrame#playerBar {
                background-color: #202026;
                border: none;
                border-top: 1px solid #303038;
            }

            QLabel {
                background-color: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }

            QLabel#logo {
                font-size: 22px;
                font-weight: bold;
                color: #ffffff;
            }

            QLabel#heading {
                font-size: 32px;
                font-weight: bold;
                color: #ffffff;
            }

            QLabel#subtitle {
                color: #a1a1aa;
                font-size: 14px;
            }

            QLabel#sectionHeading {
                font-size: 21px;
                font-weight: bold;
                color: #ffffff;
            }

            QPushButton#navButton {
                text-align: left;
                padding: 11px 12px;
                border: none;
                border-radius: 10px;
                background-color: transparent;
                color: #c4c4cc;
            }

            QPushButton#navButton:hover {
                background-color: #2c2c34;
                color: #ffffff;
            }

            QPushButton#navButton:checked {
                background-color: #322630;
                color: #fa4268;
                font-weight: bold;
            }

            QPushButton#addMusicButton {
                text-align: left;
                padding: 11px 12px;
                border: 1px solid #493047;
                border-radius: 10px;
                background-color: #30232f;
                color: #fa7893;
                font-weight: bold;
            }

            QPushButton#addMusicButton:hover {
                background-color: #493047;
                color: #ffffff;
            }

            QPushButton#modeButton {
                background-color: transparent;
                color: #a7a7b0;
                border: none;
                border-radius: 17px;
                padding: 3px;
                font-size: 17px;
            }

            QPushButton#modeButton:hover {
                background-color: #34343d;
                color: #ffffff;
            }

            QPushButton#modeButton:checked, QPushButton#modeButton[active="true"] {
                color: #fa4268;
                background-color: #38252f;
            }

            QPushButton#likeButton {
                background-color: transparent;
                color: #a7a7b0;
                border: none;
                padding: 2px;
                font-size: 22px;
            }

            QPushButton#likeButton:hover, QPushButton#likeButton[active="true"] {
                color: #fa4268;
            }

            QPushButton {
                background-color: #303039;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px;
            }

            QPushButton:hover {
                background-color: #41414b;
            }

            QLineEdit#searchBar {
                background-color: #25252d;
                color: #ffffff;
                border: 1px solid #41414b;
                border-radius: 12px;
                padding: 10px 14px;
                selection-background-color: #fa4268;
            }

            QLineEdit#searchBar:focus {
                border: 1px solid #fa4268;
            }

            QWidget#centerPlayer,
            QWidget#volumeWidget,
            QWidget#trackDetails {
                background-color: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }

            QLabel#albumCover {
                background-color: #30232f;
                color: #fa7893;
                border: 1px solid #493047;
                border-radius: 8px;
                font-size: 28px;
                font-weight: bold;
            }

            QLabel#trackInfo {
                color: #f5f5f7;
                font-size: 12px;
                font-weight: bold;
            }

            QPushButton#skipButton {
                background-color: transparent;
                color: #e4e4e7;
                border: none;
                border-radius: 19px;
                padding: 0;
                margin: 0;
                font-size: 17px;
            }

            QPushButton#skipButton:hover {
                background-color: #303039;
                color: #fa4268;
            }

            QPushButton#playButton {
                background-color: #fa4268;
                color: #ffffff;
                border: none;
                border-radius: 21px;
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                padding: 0;
                margin: 0;
                font-size: 16px;
                font-weight: bold;
            }

            QPushButton#playButton:hover {
                background-color: #df3157;
            }

            QLabel#timeLabel {
                color: #a1a1aa;
                font-size: 11px;
            }

            QLabel#volumeLabel {
                color: #c4c4cc;
                font-size: 12px;
            }

            QSlider#seekSlider,
            QSlider#volumeSlider {
                background-color: transparent;
                border: none;
                padding: 0;
                margin: 0;
            }

            QSlider#seekSlider::groove:horizontal,
            QSlider#volumeSlider::groove:horizontal {
                height: 4px;
                background-color: #41414b;
                border: none;
                border-radius: 2px;
            }

            QSlider#seekSlider::sub-page:horizontal,
            QSlider#volumeSlider::sub-page:horizontal {
                background-color: #fa4268;
                border: none;
                border-radius: 2px;
            }

            QSlider#seekSlider::add-page:horizontal,
            QSlider#volumeSlider::add-page:horizontal {
                background-color: #41414b;
                border: none;
                border-radius: 2px;
            }

            QSlider#seekSlider::handle:horizontal,
            QSlider#volumeSlider::handle:horizontal {
                background-color: #fa4268;
                border: none;
                width: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }

            QFrame#featuredBanner {
                background-color: #30232f;
                border: 1px solid #493047;
                border-radius: 16px;
            }

            QLabel#bannerTag {
                color: #fa7893;
                font-size: 11px;
                font-weight: bold;
            }

            QLabel#bannerTitle {
                color: #ffffff;
                font-size: 25px;
                font-weight: bold;
            }

            QLabel#bannerDescription {
                color: #c8bac8;
                font-size: 13px;
            }

            QScrollArea#albumScroll {
                background-color: transparent;
                border: none;
            }

            QWidget#albumContainer {
                background-color: transparent;
                border: none;
            }

            QToolButton#collectionCard {
                background-color: #202026;
                color: #f5f5f7;
                border: 1px solid #303038;
                border-radius: 12px;
                padding: 8px;
                font-size: 12px;
                font-weight: bold;
            }

            QToolButton#collectionCard:hover {
                background-color: #30232f;
                border: 1px solid #fa4268;
            }

            QListWidget#libraryList {
                background-color: #202026;
                alternate-background-color: #26262e;
                color: #f5f5f7;
                border: 1px solid #303038;
                border-radius: 12px;
                padding: 8px;
                outline: none;
            }

            QListWidget#libraryList::item {
                padding: 12px;
                border-radius: 7px;
            }

            QListWidget#libraryList::item:selected {
                background-color: #493047;
                color: #fa7893;
            }

            QListWidget#libraryList::item:hover {
                background-color: #303039;
            }

            QScrollBar:vertical {
                background-color: #202026;
                width: 8px;
                margin: 0;
                border: none;
            }

            QScrollBar::handle:vertical {
                background-color: #41414b;
                min-height: 30px;
                border-radius: 4px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #5a5a66;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
                border: none;
            }
        """)
