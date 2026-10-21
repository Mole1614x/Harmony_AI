"""Helpers that create tiny, valid, silent MP3 files with ID3 tags."""

from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

# MPEG-1 Layer III, 128 kbps, 44.1 kHz, no padding, stereo: 417-byte frames.
_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def make_mp3(path, title=None, artist=None, album=None, genre=None,
             album_artist=None, frames=200):
    """Write a silent MP3 (about 5 s) and tag only the fields provided."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_FRAME * frames)

    tags = {
        "title": title,
        "artist": artist,
        "album": album,
        "genre": genre,
        "albumartist": album_artist,
    }
    tags = {key: value for key, value in tags.items() if value}

    if tags:
        try:
            audio = EasyID3(str(path))
        except ID3NoHeaderError:
            audio = EasyID3()

        for key, value in tags.items():
            audio[key] = value

        audio.save(str(path))

    return str(path)
