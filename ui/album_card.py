
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class AlbumCard(QFrame):
    def __init__(self, title, artist, color="#303039", parent=None):
        super().__init__(parent)

        self.title = title
        self.artist = artist

        self.setObjectName("albumCard")
        self.setFixedWidth(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Album artwork placeholder
        self.artwork = QLabel("♫")
        self.artwork.setObjectName("albumArtwork")
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artwork.setFixedSize(180, 180)
        self.artwork.setStyleSheet(
            f"""
            background-color: {color};
            border-radius: 12px;
            font-size: 42px;
            color: white;
            """
        )
        layout.addWidget(self.artwork)

        # Album title
        title_label = QLabel(title)
        title_label.setObjectName("albumTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # Artist name
        artist_label = QLabel(artist)
        artist_label.setObjectName("albumArtist")
        artist_label.setWordWrap(True)
        layout.addWidget(artist_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            print(f"Selected album: {self.title} — {self.artist}")

        super().mousePressEvent(event)
