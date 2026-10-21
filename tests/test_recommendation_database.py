"""Recommendation engine against the real SQLite schema and track format."""

from pathlib import Path

import pytest
from mutagen import File as MutagenFile

from services.recommendation_service import (
    RecommendationService,
    recommend_for_library,
)
from tests.audio_fixtures import make_mp3
from ui.library_database import LibraryDatabase

PROJECT_MUSIC = Path(__file__).resolve().parent.parent / "music"


@pytest.fixture
def db(tmp_path):
    database = LibraryDatabase(tmp_path / "library.db")
    yield database
    database.close()


def add(db, tmp_path, name, **tags):
    """Create a real tagged mp3 and store it the way the app does."""
    path = make_mp3(tmp_path / "music" / f"{name}.mp3", title=name, **tags)
    audio = MutagenFile(path, easy=True)
    metadata = {
        "path": path,
        "title": name,
        "artist": tags.get("artist") or "Unknown Artist",
        "album_artist": tags.get("album_artist")
        or tags.get("artist") or "Unknown Artist",
        "album": tags.get("album") or "Unknown Album",
        "genre": tags.get("genre") or "Unknown Genre",
        "duration": audio.info.length,
    }
    db.save_track(metadata)
    return db.get_track(path)


def titles(results):
    return [item["track"]["title"] for item in results]


def test_empty_database(db):
    assert recommend_for_library(db) == []


def test_rows_from_the_real_schema_are_accepted(db, tmp_path):
    add(db, tmp_path, "S1", artist="A", album="X", genre="Pop")
    add(db, tmp_path, "S2")  # untagged: defaults from the schema

    row = db.get_all_tracks()[0]
    assert {"path", "title", "artist", "album_artist", "album", "genre",
            "duration"} <= set(row)

    results = recommend_for_library(db, limit=10)

    assert sorted(titles(results)) == ["S1", "S2"]


def test_multiple_artists_cold_start(db, tmp_path):
    add(db, tmp_path, "A1", artist="Artist A", album="AA", genre="Pop")
    add(db, tmp_path, "B1", artist="Artist B", album="BB", genre="Rock")
    add(db, tmp_path, "C1", artist="Artist C", album="CC", genre="Jazz")

    results = recommend_for_library(db, limit=10)

    assert len(results) == 3
    assert len({item["track"]["path"] for item in results}) == 3


def test_database_favorite_influences_ranking(db, tmp_path):
    add(db, tmp_path, "P1", artist="Pop Star", album="Sunny", genre="Pop")
    p2 = add(db, tmp_path, "P2", artist="Pop Star", album="Sunny",
             genre="Pop")
    add(db, tmp_path, "R1", artist="Rock Band", album="Loud", genre="Rock")
    r2 = add(db, tmp_path, "R2", artist="Rock Band", album="Loud",
             genre="Rock")

    p1 = db.get_all_tracks()
    pop = next(t for t in p1 if t["title"] == "P1")
    rock = next(t for t in p1 if t["title"] == "R1")

    db.add_favorite(pop["path"])
    assert titles(recommend_for_library(db, limit=4))[0] == "P2"

    db.remove_favorite(pop["path"])
    db.add_favorite(rock["path"])
    assert titles(recommend_for_library(db, limit=4))[0] == "R2"


def test_database_history_is_read_newest_first_and_reordered(db, tmp_path):
    x1 = add(db, tmp_path, "X1", artist="Pop Artist", album="PopA",
             genre="Pop")
    add(db, tmp_path, "X2", artist="Pop Artist", album="PopA", genre="Pop")
    y1 = add(db, tmp_path, "Y1", artist="Rock Artist", album="RockA",
             genre="Rock")
    add(db, tmp_path, "Y2", artist="Rock Artist", album="RockA",
        genre="Rock")

    def play(track):
        db.add_history(source="local", track_key=f"local:{track['path']}",
                       path=track["path"], title=track["title"],
                       artist=track["artist"], album=track["album"])

    exclude = {x1["path"], y1["path"]}

    def ranking():
        tracks = [t for t in db.get_all_tracks()
                  if t["path"] not in exclude]
        return titles(recommend_for_library(db, tracks=tracks, limit=4))

    play(x1)
    play(y1)                      # rock is the most recent listen
    assert db.get_history()[0]["title"] == "Y1"   # DB returns newest first
    assert ranking() == ["Y2", "X2"]

    db.clear_history()
    play(y1)
    play(x1)                      # now pop is the most recent
    assert ranking() == ["X2", "Y2"]


def test_youtube_history_does_not_affect_local_recommendations(db, tmp_path):
    add(db, tmp_path, "L1", artist="Local A", album="La", genre="Pop")
    add(db, tmp_path, "L2", artist="Local B", album="Lb", genre="Rock")
    baseline = titles(recommend_for_library(db, limit=5))

    db.add_history(source="online", track_key="online:abc", title="Video",
                   artist="Local B", video_id="abc",
                   url="https://www.youtube.com/watch?v=abc")

    assert titles(recommend_for_library(db, limit=5)) == baseline


def test_missing_files_in_database_are_not_recommended(db, tmp_path):
    keep = add(db, tmp_path, "Keep", artist="A", album="X", genre="Pop")
    gone = add(db, tmp_path, "Gone", artist="A", album="X", genre="Pop")
    Path(gone["path"]).unlink()

    results = recommend_for_library(db, limit=10)

    assert [item["track"]["path"] for item in results] == [keep["path"]]


def test_available_paths_limit_the_candidates(db, tmp_path):
    a = add(db, tmp_path, "A", artist="A", genre="Pop")
    add(db, tmp_path, "B", artist="B", genre="Rock")

    results = recommend_for_library(db, available_paths=[a["path"]])

    assert titles(results) == ["A"]


def test_recommendations_are_repeatable_with_unchanged_data(db, tmp_path):
    for index in range(6):
        add(db, tmp_path, f"T{index}", artist=f"Artist {index % 3}",
            album=f"Album {index % 2}", genre=["Pop", "Rock"][index % 2])

    first = db.get_all_tracks()[0]
    db.add_favorite(first["path"])
    db.add_history(source="local", track_key="k", path=first["path"],
                   title=first["title"])

    runs = [recommend_for_library(db, limit=5) for _ in range(5)]

    assert all(run == runs[0] for run in runs)


def test_deleted_track_removed_from_favorites_is_ignored(db, tmp_path):
    a = add(db, tmp_path, "A", artist="A", genre="Pop")
    add(db, tmp_path, "B", artist="B", genre="Rock")
    db.add_favorite(a["path"])
    db.remove_track(a["path"])

    results = recommend_for_library(db)

    assert titles(results) == ["B"]


@pytest.mark.skipif(
    not (PROJECT_MUSIC.is_dir() and any(PROJECT_MUSIC.glob("*.mp3"))),
    reason="project music folder not present",
)
def test_with_the_projects_real_music_files(tmp_path):
    """Real tags read via mutagen exactly like MainWindow.get_track_metadata."""
    database = LibraryDatabase(tmp_path / "real.db")

    try:
        for mp3 in sorted(PROJECT_MUSIC.glob("*.mp3")):
            audio = MutagenFile(str(mp3), easy=True)
            tags = audio.tags or {}

            def tag(key):
                value = tags.get(key)
                return value[0] if value else ""

            database.save_track({
                "path": str(mp3.resolve()),
                "title": tag("title") or mp3.stem,
                "artist": tag("artist") or "Unknown Artist",
                "album_artist": tag("albumartist") or tag("artist")
                or "Unknown Artist",
                "album": tag("album") or "Unknown Album",
                "genre": tag("genre") or "Unknown Genre",
                "duration": audio.info.length,
            })

        library = database.get_all_tracks()
        favorite = next(t for t in library if t["title"].startswith("Maye"))
        database.add_favorite(favorite["path"])

        results = recommend_for_library(database, limit=10)
        ranked = titles(results)

        # Same album + shared artist (Lata Mangeshkar) must come first.
        assert ranked[0].startswith("Didi Tera Devar")
        assert ranked[-1].startswith("Maye")          # favorite fills last
        assert len(set(ranked)) == len(ranked) == len(library)
    finally:
        database.close()
