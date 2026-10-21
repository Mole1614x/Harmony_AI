# Harmony AI 🎵
### Personalized Music Player & Recommendation System

Harmony AI is a desktop-based music player built with Python and PySide6. It combines local music library management, online music discovery, persistent listening history, favorites, playlists, and personalized music recommendations in one application.

The goal is to make music discovery more personal by recommending tracks based on the user's listening activity and music preferences.

## ✨ Features

- **Music Playback:** Play and manage music through a desktop interface.
- **Local Music Library:** Import and organize music stored on your computer.
- **Personalized Recommendations:** Discover tracks based on listening history and favorite songs.
- **Made for Your Taste:** Get recommendations tailored to your music library and listening preferences.
- **Online Music Discovery:** Explore music through the application's online discovery interface.
- **Favorites:** Save favorite tracks for quick access.
- **Listening History:** Maintain a persistent record of played music.
- **Playlist Management:** Organize music into playlists.
- **Persistent Storage:** Store library information, favorites, playlists, and listening history using SQLite.
- **Recommendation Engine:** Generate recommendations using available library data and user preferences.

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| Desktop GUI | PySide6 |
| Database | SQLite |
| Music Metadata | Mutagen |
| Music Playback | VLC integration |
| Recommendation Logic | Python |
| Testing | pytest |
| Version Control | Git and GitHub |

## 📁 Project Structure

```text
harmony_ai_2/
├── main.py
├── config/
├── models/
├── services/
│   ├── recommendation_service.py
│   └── ...
├── ui/
│   ├── main_window.py
│   ├── library_database.py
│   ├── persistent_main_window.py
│   ├── online_main_window.py
│   └── ...
├── tests/
├── assets/
├── music/
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── AUDIT_REPORT.md
├── .gitignore
└── README.md
```

*Note: The exact contents of folders may vary as the project evolves.*

## ⚙️ Prerequisites

Before running Harmony AI, make sure you have:

- Python 3 installed
- pip package manager
- VLC media player or the required VLC runtime libraries for your platform
- Git, if cloning the repository

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/Mole1614x/Harmony_AI.git
cd Harmony_AI
```

### 2. Create a virtual environment

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows**

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For development and testing dependencies:

```bash
pip install -r requirements-dev.txt
```

### 4. Run the application

```bash
python main.py
```

## 🎧 Using Harmony AI

1. Launch the application.
2. Import music into your local library, if needed.
3. Play tracks and build your listening history.
4. Mark tracks as favorites and create playlists.
5. Open **Listen Now** and explore **Made for Your Taste**.
6. Select a recommended track to start playback.
7. Explore the available online music discovery features.

Recommendations may improve as the application collects more listening history and preference data.

## 🧠 Recommendation System

Harmony AI includes a recommendation service that uses available music library information and user activity to generate personalized suggestions.

The recommendation workflow is designed to:

- Use the local music library as recommendation input.
- Consider listening history and favorite tracks.
- Avoid duplicate recommendations for the same song when possible.
- Filter unsupported history entries, such as online tracks that do not correspond to local music files.
- Refresh recommendations when relevant library or listening activity changes.
- Integrate recommendations with the existing playback interface.

The recommendation experience depends on the available library data and the recommendation logic implemented in the current version.

## 🗄️ Data Storage

Harmony AI uses SQLite to persist music-related information, including supported library records, favorites, playlists, and listening history.

The database is maintained locally by the application. Back up your database before making manual changes to it.

## 🧪 Running Tests

To run the project's automated tests:

```bash
python -m pytest -v
```

To run tests with a summary of passed and failed tests:

```bash
python -m pytest
```

Tests may cover recommendation logic, database behavior, metadata handling, and application integration. Platform-dependent playback and online functionality should also be tested on the target machine.

## 🔒 Security and Privacy

- Keep passwords, API keys, access tokens, and other secrets out of source code.
- Do not commit personal music files or local database contents unless intended.
- Use the provided `.gitignore` to exclude virtual environments, cache files, and sensitive local data.
- Review changes for secrets before pushing to GitHub.

## 🔮 Future Improvements

Potential future enhancements include:

- More advanced content-based and collaborative recommendation techniques.
- Improved music discovery and search.
- Better integration between online discovery and personalized recommendations.
- Enhanced recommendation explanations.
- Additional playback controls and user interface improvements.
- Expanded automated testing across platforms.

## 👨‍💻 Author

**Anmol Gangwar**

- GitHub: [@Mole1614x](https://github.com/Mole1614x)
- LinkedIn: [Anmol Gangwar](https://www.linkedin.com/in/anmolgangwar/)

## 📄 License

No license has been specified yet. Unless a license is added to this repository, reuse and redistribution are subject to applicable copyright law.
