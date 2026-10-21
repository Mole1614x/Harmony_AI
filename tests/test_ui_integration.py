"""
End-to-end checks against the real application window.

The window class used here is the one main.py launches. Qt runs offscreen,
VLC runs against its "dummy" audio output, and the database/music folder are
temporary, so the user's real library is never touched.
"""

import sqlite3

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QToolButton,
)

import ui.main_window as main_window_module
from tests.audio_fixtures import make_mp3

vlc = main_window_module.vlc

requires_vlc = pytest.mark.skipif(
    vlc is None, reason="VLC / python-vlc is not available"
)

LIBRARY = [
    # Symmetric pairs so that only the signal under test can separate them.
    dict(name="Pop One", artist="Pop Artist", album="Pop Album",
         genre="Pop"),
    dict(name="Pop Two", artist="Pop Artist", album="Pop Album",
         genre="Pop"),
    dict(name="Rock One", artist="Rock Artist", album="Rock Album",
         genre="Rock"),
    dict(name="Rock Two", artist="Rock Artist", album="Rock Album",
         genre="Rock"),
    dict(name="Untagged"),
]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _VlcWithDummyAudio:
    """Delegates to the real python-vlc but forces the dummy audio output.

    A proxy is used (instead of patching ``vlc.Instance`` itself) because
    python-vlc's own internals reference ``vlc.Instance``.
    """

    def __getattr__(self, name):
        return getattr(vlc, name)

    @staticmethod
    def Instance(*args):
        return vlc.Instance(*args, "--aout=dummy")


@pytest.fixture(autouse=True)
def silent_vlc(monkeypatch):
    """Use VLC's dummy audio output so tests also work headless."""
    if vlc is None:
        return

    import ui.persistent_main_window as persistent_module

    proxy = _VlcWithDummyAudio()
    monkeypatch.setattr(main_window_module, "vlc", proxy)
    monkeypatch.setattr(persistent_module, "vlc", proxy)


@pytest.fixture
def make_window(qapp, tmp_path, monkeypatch):
    from ui.online_main_window import OnlineMainWindow

    created = []
    dialogs = []

    for name in ("information", "warning"):
        monkeypatch.setattr(
            QMessageBox, name,
            staticmethod(lambda *args, _n=name, **kw: dialogs.append(
                (_n, args)
            )),
        )

    def factory(specs=LIBRARY):
        music = tmp_path / "music"
        music.mkdir(exist_ok=True)

        for spec in specs:
            spec = dict(spec)
            name = spec.pop("name")
            make_mp3(music / f"{name}.mp3", title=name if spec else None,
                     **spec)

        window = OnlineMainWindow(
            database_path=tmp_path / "ui.db", music_folder=music
        )
        window.test_dialogs = dialogs
        window.test_db_path = tmp_path / "ui.db"
        created.append(window)
        return window

    yield factory

    for window in created:
        window.close()
        window.deleteLater()

    QTest.qWait(50)


def pump(milliseconds):
    QTest.qWait(milliseconds)


def cards(window):
    found = []

    for index in range(window.album_grid.count()):
        widget = window.album_grid.itemAt(index).widget()

        if isinstance(widget, QToolButton):
            found.append(widget)

    return found


def card_titles(window):
    return [card.text().split("\n")[0] for card in cards(window)]


def history_rows(window):
    connection = sqlite3.connect(str(window.test_db_path))

    try:
        return connection.execute(
            "SELECT source, path, title FROM listening_history ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


def wait_until(predicate, timeout_ms=4000, step=100):
    waited = 0

    while waited < timeout_ms:
        if predicate():
            return True

        pump(step)
        waited += step

    return predicate()


# ------------------------------------------------------------ wiring
def test_entry_point_launches_the_window_that_was_integrated():
    import main
    from ui.main_window import MainWindow
    from ui.online_main_window import OnlineMainWindow
    from ui.persistent_main_window import PersistentMainWindow

    assert main.OnlineMainWindow is OnlineMainWindow
    assert OnlineMainWindow.__mro__[1] is PersistentMainWindow
    assert PersistentMainWindow.__mro__[1] is MainWindow
    assert (
        PersistentMainWindow.populate_recommendations
        is not MainWindow.populate_recommendations
    )


# ------------------------------------------------------ empty library
def test_empty_library_keeps_the_original_sample_cards(make_window):
    window = make_window(specs=[])

    assert window.music_files == []
    assert window.get_recommendations() == []
    assert cards(window) == []                       # no recommendation cards
    assert window.album_grid.count() == len(window.sample_albums)


# ------------------------------------------------------ Listen Now UI
def test_listen_now_shows_real_recommendations(make_window):
    window = make_window()

    assert window.current_page == "Listen Now"
    assert window.section_heading.text() == "Made for Your Taste"
    assert window.section_heading.isVisibleTo(window)
    assert sorted(card_titles(window)) == sorted(
        spec["name"] for spec in LIBRARY
    )


def test_cards_match_the_recommendation_engine(make_window):
    window = make_window()

    expected = [
        item["track"]["title"] for item in window.get_recommendations()
    ]

    assert card_titles(window) == expected


def test_recommendation_cards_are_deterministic(make_window):
    window = make_window()

    first = card_titles(window)
    window.show_page("Albums")
    window.show_page("Listen Now")

    assert card_titles(window) == first


def test_favorite_changes_what_listen_now_shows(make_window):
    window = make_window()
    pop_one = next(p for p in window.music_files if "Pop One" in p)
    rock_one = next(p for p in window.music_files if "Rock One" in p)

    window.library_db.add_favorite(pop_one)
    window.show_page("Listen Now")
    assert card_titles(window)[0] == "Pop Two"
    assert card_titles(window)[-1] == "Pop One"      # favorite fills last

    window.library_db.remove_favorite(pop_one)
    window.library_db.add_favorite(rock_one)
    window.show_page("Listen Now")
    assert card_titles(window)[0] == "Rock Two"


def test_favorite_button_refreshes_the_cards(make_window):
    window = make_window()
    rock_one = next(p for p in window.music_files if "Rock One" in p)
    window.current_track_index = window.music_files.index(rock_one)

    window.favorite_button.click()                    # real UI action

    assert window.library_db.is_favorite(rock_one)
    assert card_titles(window)[0] == "Rock Two"


def test_listening_history_changes_what_listen_now_shows(make_window):
    window = make_window()
    pop_one = next(p for p in window.music_files if "Pop One" in p)
    rock_one = next(p for p in window.music_files if "Rock One" in p)

    for path, title in ((pop_one, "Pop One"), (rock_one, "Rock One")):
        window.library_db.add_history(
            source="local", track_key=f"local:{path}", path=path,
            title=title,
        )
    window.show_page("Listen Now")
    titles_ = card_titles(window)

    # Rock was listened to last, so the rock sibling outranks the pop one.
    assert titles_.index("Rock Two") < titles_.index("Pop Two")


# -------------------------------------------------- playback of a card
@requires_vlc
def test_clicking_a_recommendation_plays_that_exact_track(make_window):
    window = make_window()
    first_card = cards(window)[0]
    expected_title = first_card.text().split("\n")[0]
    expected_path = next(
        p for p in window.music_files if expected_title in p
    )

    first_card.click()

    assert window.music_files[window.current_track_index] == expected_path
    assert window.current_source == "local"
    assert expected_title in window.track_info.text()
    assert wait_until(
        lambda: window.audio_player.get_state() == vlc.State.Playing
    )
    assert window.play_button.text() == "❚❚"

    # ...and the listen is recorded against the same file.
    assert wait_until(lambda: history_rows(window), timeout_ms=3000)
    assert history_rows(window)[-1][1] == expected_path


@requires_vlc
def test_playing_then_recommending_uses_the_current_track(make_window):
    window = make_window()
    rock_one = next(p for p in window.music_files if "Rock One" in p)

    window.play_track(window.music_files.index(rock_one))
    assert wait_until(lambda: window._current_local_path() == rock_one)

    window.show_page("Listen Now")
    names = card_titles(window)

    assert "Rock One" not in names               # never recommends itself
    assert names[0] == "Rock Two"                # similar to what is playing


@requires_vlc
def test_missing_recommended_file_is_handled(make_window):
    window = make_window()
    target = next(p for p in window.music_files if "Pop Two" in p)

    from pathlib import Path
    Path(target).unlink()

    window.play_recommended_track(target)             # must not raise

    assert any(kind == "warning" for kind, _ in window.test_dialogs)


# ----------------------------------------------------- history fix
@requires_vlc
def test_launching_without_playing_does_not_write_history(make_window):
    window = make_window()

    pump(1500)                                        # > one history tick

    assert history_rows(window) == []


@requires_vlc
def test_history_is_recorded_after_real_playback(make_window):
    window = make_window()

    window.play_track(0)

    assert wait_until(lambda: history_rows(window), timeout_ms=3500)
    rows = history_rows(window)
    assert rows[0][0] == "local"
    assert rows[0][1] == window.music_files[0]


# ------------------------------------------------ existing features
def test_existing_pages_still_populate(make_window):
    window = make_window()

    window.show_page("Your Library")
    assert window.library_list.count() == len(LIBRARY)

    window.show_page("Albums")
    assert len(cards(window)) >= 3

    window.show_page("Artists")
    assert len(cards(window)) >= 3

    window.show_page("Discover")
    assert window.album_grid.count() == len(window.sample_albums)

    window.show_page("Search")
    window.search_bar.setText("rock")
    assert window.library_list.count() == 2


def test_library_double_click_still_plays_selected_track(make_window):
    window = make_window()
    window.show_page("Your Library")
    played = []
    window.play_track = played.append

    item = window.library_list.item(1)
    window.library_list.itemDoubleClicked.emit(item)

    assert played == [item.data(0x0100)]


def test_playlists_favorites_and_history_pages(make_window):
    window = make_window()
    path = window.music_files[0]

    assert window.library_db.create_playlist("Road Trip")
    assert window.library_db.add_to_playlist("Road Trip", path)
    window.show_page("Playlists")
    assert window.library_list.count() == 1

    window.open_playlist("Road Trip")
    assert len(window.collection_tracks) == 1

    window.library_db.add_favorite(path)
    window.show_page("Favorites")
    assert window.library_list.count() == 1

    window.library_db.add_history(source="local", track_key="k", path=path,
                                  title="Some Track")
    window.show_page("History")
    assert window.library_list.count() == 1


def test_youtube_panel_and_navigation_still_present(make_window):
    window = make_window()

    assert window.online_nav_button.text() == "YouTube Music"
    window.show_page("Online Music")
    assert window.online_nav_button.isChecked()
    assert window.online_panel.isVisibleTo(window)

    window.show_page("Listen Now")
    assert not window.online_panel.isVisibleTo(window)
    assert cards(window)                               # recommendations back


@requires_vlc
def test_local_playback_after_youtube_page_returns_to_local(make_window):
    window = make_window()
    window.show_page("Online Music")

    window.play_recommended_track(window.music_files[1])

    assert window.current_source == "local"
    assert window.current_track_index == 1
    assert wait_until(
        lambda: window.audio_player.get_state() == vlc.State.Playing
    )
