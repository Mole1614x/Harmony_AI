"""Unit tests for the pure recommendation engine (no Qt, no database)."""

import random

import pytest

from services.recommendation_service import RecommendationService


def track(name, artist="Unknown Artist", album="Unknown Album",
          genre="Unknown Genre", duration=200.0, directory="/music"):
    return {
        "path": f"{directory}/{name}.mp3",
        "title": name,
        "artist": artist,
        "album_artist": artist,
        "album": album,
        "genre": genre,
        "duration": duration,
    }


@pytest.fixture
def service():
    return RecommendationService()


@pytest.fixture
def library():
    return [
        track("P1", "Pop Star", "Sunny", "Pop"),
        track("P2", "Pop Star", "Sunny", "Pop"),
        track("P3", "Other Pop", "Beach", "Pop"),
        track("R1", "Rock Band", "Loud", "Rock"),
        track("R2", "Rock Band", "Louder", "Rock"),
        track("J1", "Jazz Trio", "Blue", "Jazz"),
    ]


def titles(results):
    return [item["track"]["title"] for item in results]


def paths(results):
    return [item["track"]["path"] for item in results]


# ---------------------------------------------------------------- empty
def test_empty_library_returns_nothing(service):
    assert service.recommend([]) == []
    assert service.recommend(None) == []
    assert service.recommend([], favorites=[track("X")],
                             listening_history=[track("X")]) == []


# ------------------------------------------------------ several tracks
def test_several_artists_and_genres(service, library):
    results = service.recommend(library, limit=4)

    assert len(results) == 4
    assert len(set(paths(results))) == 4
    assert all(0.0 <= item["score"] <= 1.0 for item in results)
    assert all(item["reason"] for item in results)


def test_current_track_never_recommended_and_drives_similarity(
        service, library):
    results = service.recommend(library, current_track=library[0], limit=5)

    assert "P1" not in titles(results)
    # Same artist/genre/album as the current track ranks first.
    assert titles(results)[0] == "P2"
    assert results[0]["reason"] == "Similar artist"
    # Different genre ranks last.
    assert titles(results)[-1] in {"R1", "R2", "J1"}


def test_current_track_can_be_a_path(service, library):
    results = service.recommend(library, current_track=library[3]["path"])

    assert "R1" not in titles(results)
    assert titles(results)[0] == "R2"


# ------------------------------------------------------------ favorites
def test_favorite_changes_recommendations(service, library):
    pop_fav = service.recommend(library, favorites=[library[0]], limit=5)
    rock_fav = service.recommend(library, favorites=[library[3]], limit=5)

    assert titles(pop_fav)[0] == "P2"        # same artist/genre/album
    assert titles(rock_fav)[0] == "R2"
    assert titles(pop_fav) != titles(rock_fav)


def test_favorites_are_ranked_after_other_candidates(service, library):
    results = service.recommend(library, favorites=[library[0]], limit=6)

    assert titles(results)[-1] == "P1"
    assert results[-1]["reason"] == "One of your favorites"


def test_favorites_can_be_excluded(service, library):
    results = service.recommend(
        library, favorites=[library[0]], limit=6, allow_favorites=False
    )

    assert "P1" not in titles(results)


def test_favorites_accept_paths(service, library):
    by_dict = service.recommend(library, favorites=[library[3]], limit=5)
    by_path = service.recommend(
        library, favorites=[library[3]["path"]], limit=5
    )

    assert titles(by_dict) == titles(by_path)


# -------------------------------------------------------------- history
def test_history_changes_recommendations(service, library):
    rock = service.recommend(library, listening_history=[library[3]] * 3,
                             limit=5, exclude_paths=[library[3]["path"]])
    jazz = service.recommend(library, listening_history=[library[5]] * 3,
                             limit=5, exclude_paths=[library[5]["path"]])

    assert titles(rock)[0] == "R2"             # same artist and genre
    assert titles(jazz)[0] != titles(rock)[0]
    assert rock[0]["reason"] == "Based on artists you listen to"


def test_history_is_oldest_to_newest_and_recent_plays_weigh_more(service):
    # Candidates are perfectly symmetric, so only recency can separate them.
    x1 = track("X1", "Pop Artist", "PopAlbum", "Pop")
    x2 = track("X2", "Pop Artist", "PopAlbum", "Pop")
    y1 = track("Y1", "Rock Artist", "RockAlbum", "Rock")
    y2 = track("Y2", "Rock Artist", "RockAlbum", "Rock")
    library = [x1, x2, y1, y2]
    played = [x1["path"], y1["path"]]

    pop_then_rock = service.recommend(
        library, listening_history=[x1, y1], exclude_paths=played
    )
    rock_then_pop = service.recommend(
        library, listening_history=[y1, x1], exclude_paths=played
    )

    assert titles(pop_then_rock) == ["Y2", "X2"]   # rock played most recently
    assert titles(rock_then_pop) == ["X2", "Y2"]


def test_a_track_is_not_boosted_by_comparing_it_with_itself(service):
    a = track("A", "Artist", "Album", "Pop")
    b = track("B", "Artist", "Album", "Pop")

    once = service.recommend([a, b], listening_history=[a])
    scores = {item["track"]["title"]: item["score"] for item in once}

    # A was played once: only the small play-count bonus separates them.
    assert 0 < scores["A"] - scores["B"] <= 0.03


def test_non_local_history_rows_are_ignored(service, library):
    youtube_only = [
        {"id": 7, "source": "online", "path": "", "video_id": "abc",
         "title": "Some video", "artist": "Pop Star", "album": "Sunny"},
    ]

    with_online = service.recommend(library, listening_history=youtube_only)
    without = service.recommend(library)

    assert with_online == without


def test_history_row_id_is_not_mistaken_for_a_path(service, library):
    row = {"id": 5, "source": "local", "path": library[3]["path"],
           "title": "R1", "artist": "Rock Band", "album": "Loud"}

    results = service.recommend(library, listening_history=[row], limit=5,
                                exclude_paths=[library[3]["path"]])

    assert titles(results)[0] == "R2"


def test_history_resolves_to_library_metadata(service):
    # The history row carries no artist/genre; the library entry does.
    played = track("Z1", "Artist Z", "Album Z", "Rock")
    same_genre = track("Z2", "Artist ZZ", "Album ZZ", "Rock")
    other = track("APop", "Artist P", "Album P", "Pop")
    row = {"source": "local", "path": played["path"], "title": "Z1"}

    results = service.recommend(
        [played, same_genre, other], listening_history=[row],
        exclude_paths=[played["path"]],
    )

    # Alphabetical/cold-start order would put "APop" first.
    assert titles(results) == ["Z2", "APop"]


# ----------------------------------------------------------- cold start
def test_cold_start_without_any_signal_is_deterministic_and_diverse(service):
    many = [track(f"A{i}", "Artist A", "AlbumA", "Pop") for i in range(8)]
    many += [track("B1", "Artist B", "AlbumB", "Rock"),
             track("C1", "Artist C", "AlbumC", "Jazz")]

    results = service.recommend(many, limit=4)
    artists = [item["track"]["artist"] for item in results]

    assert len(results) == 4
    assert artists.count("Artist A") <= 2          # artist cap applies
    assert "Artist B" in artists and "Artist C" in artists


def test_cold_start_prefers_complete_metadata(service):
    tracks = [
        track("Empty"),
        track("Full", "Someone", "Something", "Pop"),
    ]

    assert titles(service.recommend(tracks))[0] == "Full"


def test_single_track_library(service):
    only = [track("Only", "A", "B", "Pop")]

    assert titles(service.recommend(only)) == ["Only"]
    assert service.recommend(only, current_track=only[0]) == []


# ------------------------------------------------------ missing metadata
def test_missing_and_incomplete_metadata(service):
    tracks = [
        {"path": "/m/bare.mp3"},
        {"path": "/m/none.mp3", "title": None, "artist": None,
         "album": None, "genre": None},
        {"path": "/m/unknown.mp3", "title": "Unknown Title",
         "artist": "Unknown Artist", "album": "Unknown Album",
         "genre": "Unknown Genre"},
        {"path": "/m/various.mp3", "title": "V", "artist": "Various Artists",
         "album": "Mix", "genre": ""},
        track("Real", "Artist", "Album", "Pop"),
    ]

    for kwargs in (
        {},
        {"current_track": tracks[4]},
        {"favorites": [tracks[4]], "listening_history": [tracks[4]]},
        {"favorites": [tracks[0]], "listening_history": [tracks[1]]},
    ):
        results = service.recommend(tracks, limit=10, **kwargs)
        assert all(0.0 <= item["score"] <= 1.0 for item in results)
        assert len(set(paths(results))) == len(results)

    # Unknown placeholders never count as a shared artist/album/genre.
    a = {"path": "/a.mp3", "artist": "Unknown Artist",
         "album": "Unknown Album", "genre": "Unknown Genre"}
    b = dict(a, path="/b.mp3")
    assert service.similarity(a, b) == 0.0


def test_genre_list_and_tag_variants(service):
    first = {"path": "/a.mp3", "artist": "X", "genre": "Pop; Dance"}
    second = {"path": "/b.mp3", "artist": "Y", "genres": ["dance", "Rock"]}

    assert 0.0 < service.similarity(first, second) < 1.0


def test_multi_artist_strings_share_performers(service):
    solo = {"path": "/a.mp3", "artist": "Lata Mangeshkar"}
    duet = {"path": "/b.mp3",
            "artist": "Lata Mangeshkar, S. P. Balasubrahmanyam"}
    other = {"path": "/c.mp3", "artist": "Saaj Bhatt"}

    assert service.similarity(solo, duet) == 1.0
    assert service.similarity(solo, other) == 0.0


# ------------------------------------------------------------ duplicates
def test_duplicate_paths_in_input_are_returned_once(service, library):
    doubled = library + [dict(item) for item in library]

    results = service.recommend(doubled, limit=20)

    assert len(paths(results)) == len(set(paths(results))) == len(library)


def test_same_song_at_two_paths_is_returned_once(service):
    a = track("Song", "Artist", "Album", "Pop", 180.2, directory="/music")
    b = track("Song", "Artist", "Album", "Pop", 180.4, directory="/backup")
    other = track("Other", "Artist2", "Album2", "Rock")

    results = service.recommend([a, b, other], limit=10)

    assert titles(results).count("Song") == 1


def test_duplicate_of_current_track_is_not_recommended(service):
    a = track("Song", "Artist", "Album", "Pop", directory="/music")
    b = track("Song", "Artist", "Album", "Pop", directory="/backup")
    other = track("Other", "Artist", "Album", "Pop")

    results = service.recommend([a, b, other], current_track=a)

    assert titles(results) == ["Other"]


def test_exclude_paths(service, library):
    results = service.recommend(
        library, exclude_paths=[library[1]["path"]], limit=10
    )

    assert "P2" not in titles(results)


# ----------------------------------------------------- invalid input
def test_invalid_entries_are_skipped(service, library):
    messy = library + [None, 42, "not a track", {}, {"path": ""},
                       {"title": "no path"}]

    results = service.recommend(messy, limit=50)

    assert len(results) == len(library)


@pytest.mark.parametrize("limit", [0, -3])
def test_non_positive_limit(service, library, limit):
    assert service.recommend(library, limit=limit) == []


def test_invalid_limit_falls_back_to_default(service, library):
    assert len(service.recommend(library, limit="many")) == len(library)


def test_limit_is_respected(service, library):
    assert len(service.recommend(library, limit=2)) == 2


def test_invalid_weights_rejected():
    with pytest.raises(ValueError):
        RecommendationService(0, 0, 0)


# ---------------------------------------------------------- determinism
def test_repeated_calls_are_identical(service, library):
    kwargs = dict(current_track=library[0], favorites=[library[3]],
                  listening_history=[library[1], library[5]], limit=6)

    first = service.recommend(library, **kwargs)

    for _ in range(5):
        assert service.recommend(library, **kwargs) == first


def test_input_order_does_not_change_ranking(service, library):
    kwargs = dict(favorites=[library[3]], listening_history=[library[1]],
                  limit=6)
    expected = service.recommend(library, **kwargs)

    for seed in range(5):
        shuffled = list(library)
        random.Random(seed).shuffle(shuffled)
        assert service.recommend(shuffled, **kwargs) == expected


def test_scores_reflect_taste_not_randomness(service, library):
    results = service.recommend(library, favorites=[library[0]],
                                limit=6, allow_favorites=False)
    scores = [item["score"] for item in results]

    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) > 1
    assert scores[0] > scores[-1]
