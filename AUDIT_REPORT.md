# Harmony AI — Audit, Recommendation Integration, Test Report

Environment used: Linux, Python 3.12, PySide6 6.9.3, python-vlc 3.0.21203 with
VLC 3.0.20 (dummy audio output), Qt `offscreen` platform.

## Run the tests

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements-dev.txt
    python -m pytest -v

(62 tests, ~7 s. Tests use a temporary database and temporary music files and
never touch `skullcandy.db` or `music/`, except one read-only test that reads
the tags of the MP3s in `music/`.)

## A. Audit report

### What was already working
- `main.py` launches `ui.online_main_window.OnlineMainWindow`, which inherits
  `PersistentMainWindow` -> `MainWindow`. This chain is the real UI; the
  Jamendo-based `services/online_main_service.py` is not imported anywhere.
- SQLite layer (`ui/library_database.py`): tracks, favorites, listening
  history, playlists; schema migrations; path normalisation.
- VLC local playback, source switching to/from the YouTube panel, library,
  albums, artists, search, playlists, favorites and history pages.
- `RecommendationService` was real logic (artist/genre/album similarity,
  weighted favorites + history profile, cold-start fallback, artist-diversity
  cap) — not random or placeholder.

### What was broken or incomplete
1. **Not connected.** Nothing imported `RecommendationService`. The
   "Made for Your Taste" section on Listen Now showed hard-coded fake albums.
2. **History order bug (integration trap).** The engine expects history
   oldest->newest; `LibraryDatabase.get_history()` returns newest first, so
   recency weighting would have been inverted.
3. **History rows used as tracks.** `_path()` fell back to `id`, which for a
   history row is the DB auto-increment, and history rows were used with their
   own (genre-less) metadata instead of the library's; YouTube rows were not
   filtered out.
4. **Duplicates.** Duplicate input paths and the same song stored under two
   paths were returned twice (the real DB contains such a duplicate).
5. **Multi-artist tags** ("Lata Mangeshkar, S. P. Balasubrahmanyam") never
   matched "Lata Mangeshkar".
6. **Self-comparison / docstring drift.** History tracks were compared with
   themselves; the docstring claimed favorites were excluded but they were only
   boosted (so favorites always dominated the list).
7. **Phantom listening history.** `record_current_playback` logged the default
   queue position (track 0) every launch although nothing was playing
   (reproduced: history rows 5 -> 6 after 2.5 s idle). This would have
   polluted the personalisation signal.
8. **Placeholder test.** `services/test_recommendations.py` was a script that
   ran at import time and did not use the database or application.

### What I changed
- `services/recommendation_service.py`: fixes for items 2–6 above; favorites
  now rank after non-favorites and only fill remaining slots
  (`allow_favorites=False` removes them); duplicate paths and same-recording
  duplicates removed; current track (and its duplicate) never recommended;
  `sqlite3.Row`/Mapping accepted; paths resolved once per call; added
  `recommend_for_library(db, ...)` adapter that reads favorites/history from
  `LibraryDatabase`, ignores non-local history, reverses history into
  chronological order and drops missing/invalid files.
- `ui/main_window.py`: `populate_recommendations()` hook (base returns False,
  so the original sample cards remain when no provider exists).
- `ui/persistent_main_window.py`: implements the hook for Listen Now ->
  "Made for Your Taste" using the in-app track metadata, DB favorites and DB
  history; each card plays through `play_recommended_track()` ->
  existing `play_track()` flow; cards refresh after favorite toggles, new
  history entries, clearing history and library imports; history is recorded
  only when VLC is actually playing/paused, and a finished track can be
  counted again on replay. New optional constructor args `database_path`,
  `music_folder` (defaults unchanged) so tests can use temporary data.
- `ui/online_main_window.py`: passes those two optional args through.
- New: `tests/` (62 tests), `pytest.ini`, `requirements-dev.txt`.
- Removed from the package: `services/test_recommendations.py` (replaced),
  stray empty file `PySide6`, `.DS_Store`, `__pycache__`. `skullcandy.db` is
  shipped exactly as received.

### Remaining / unverified
- Real audio output and macOS behaviour were not exercised (Linux, VLC dummy
  audio device). YouTube search/playback needs network and was not run; only
  the YouTube panel/navigation and the switch back to local playback were
  tested.
- No visual/pixel check of the cards (offscreen rendering only).
- Recommendations use metadata only (artist/genre/album). Tracks tagged
  "Unknown Genre"/"Unknown Artist" carry little signal; artist splitting on
  `,` `;` `&` `feat.` also splits names like "Tyler, The Creator".
- `skullcandy.db` contains absolute macOS paths (`/Users/admin/...`) and a
  duplicate row for one song stored outside `music/`. The app's existing
  missing-file recovery rewrites paths on first launch elsewhere (observed);
  the engine de-duplicates the song.
- Not changed (flagging only): `services/online_main_service.py` is an unused
  older variant of `OnlineMainWindow`; `services/music_provider.py`,
  `services/playback_service.py`, `models/online_track.py`,
  `config/settings.py` are empty files; window title/logo say "SkullCandy".

## C. Test report (all executed, 62 passed)
- `tests/test_recommendation_service.py` — 33 tests: empty/None library;
  several artists/genres; current track (dict or path) excluded and used for
  similarity; favorites change ranking, rank last, can be excluded, accept
  paths; history changes ranking, recency order, no self-boost, non-local rows
  ignored, history `id` not used as a path, library metadata used; cold start
  (diversity cap, metadata completeness, single track); missing/None/"Unknown"
  metadata; genre list variants; multi-artist matching; duplicate paths and
  same-song-two-paths; duplicate of current track; `exclude_paths`; invalid
  entries; limit 0/negative/invalid/respected; invalid weights; repeated calls
  identical; shuffled input gives same ranking; score ordering not random.
- `tests/test_recommendation_database.py` — 11 tests against real
  `LibraryDatabase` + real tagged MP3 files: empty DB; real schema rows;
  multi-artist cold start; DB favorites; DB history newest-first reversal;
  YouTube history ignored; missing files skipped; `available_paths` filter;
  repeatability; deleted track; the project's real `music/` tags (favorite
  "Maye Ni Maye" -> "Didi Tera Devar Deewana" first).
- `tests/test_ui_integration.py` — 18 tests on the real `OnlineMainWindow`
  (offscreen Qt, real VLC with dummy audio, temp DB/music): entry-point class
  chain; empty library keeps sample cards; cards match engine output and are
  deterministic; favorite (DB and button) and history change the cards;
  clicking a card plays the exact file in VLC (state Playing) and records
  history for that path; current track drives suggestions and is never
  recommended; deleted file handled; no history at launch (regression);
  history after real playback; Your Library/Albums/Artists/Discover/Search
  pages; double-click playback; playlists/favorites/history pages; YouTube
  panel navigation; local playback after visiting YouTube page.
- Mutation check (scratch copy, not shipped): re-introducing the phantom
  history bug or removing the history reversal made 3 tests fail, as expected.

## D. Completion checklist
| Item | Status |
|---|---|
| Recommendation algorithm | COMPLETE |
| Favorites-based personalization | COMPLETE |
| Listening-history personalization | COMPLETE |
| Cold-start recommendations | COMPLETE |
| SQLite integration | COMPLETE |
| UI integration | COMPLETE (verified offscreen; not visually inspected) |
| Recommended-track playback | COMPLETE for VLC with dummy audio; real speakers/macOS UNVERIFIED |
| Regression checks for existing features | COMPLETE for local library/playlists/favorites/history/navigation; YouTube search & playback UNVERIFIED (no network) |
| Automated tests | COMPLETE (62 passing) |
