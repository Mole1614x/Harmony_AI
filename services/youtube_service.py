import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


# Resolve the project root independently of the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Load environment variables from harmony_ai_2/.env.
load_dotenv(dotenv_path=ENV_FILE, override=False)


class YouTubeService:
    """Search YouTube and filter out Shorts and unrelated videos."""

    API_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_API_URL = "https://www.googleapis.com/youtube/v3/videos"

    EXCLUDED_TITLE_PATTERNS = [
        r"#shorts\b",
        r"\bshorts\b",
        r"\bshort video\b",
        r"\breels?\b",
        r"\bofficial trailer\b",
        r"\bmovie trailer\b",
        r"\bteaser\b",
        r"\bfull movie\b",
        r"\bfull episode\b",
        r"\bepisode\s+\d+\b",
        r"\bbehind the scenes\b",
        r"\bmaking of\b",
        r"\binterview\b",
        r"\breaction video\b",
        r"\bgameplay\b",
        r"\bpodcast\b",
        r"\bnews\b",
        r"\bwhatsapp status\b",
        r"\bstatus video\b",
    ]

    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY", "").strip()

    def _api_get(self, url, params):
        """Send a GET request to the YouTube API and return JSON."""
        request_url = f"{url}?{urlencode(params)}"

        request = Request(
            request_url,
            headers={"Accept": "application/json"},
        )

        try:
            with urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))

        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")

            try:
                error_data = json.loads(details)
                message = error_data.get("error", {}).get(
                    "message",
                    "Unknown YouTube API error",
                )
            except json.JSONDecodeError:
                message = details or str(exc)

            raise RuntimeError(
                f"YouTube API returned HTTP {exc.code}: {message}"
            ) from exc

        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Could not connect to YouTube: {exc}"
            ) from exc

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "YouTube returned an invalid JSON response."
            ) from exc

    @staticmethod
    def _parse_duration(duration):
        """Convert ISO 8601 durations such as PT3M45S to seconds."""
        if not duration:
            return None

        pattern = (
            r"P"
            r"(?:(\d+)D)?"
            r"(?:T"
            r"(?:(\d+)H)?"
            r"(?:(\d+)M)?"
            r"(?:(\d+)S)?"
            r")?"
        )

        match = re.fullmatch(pattern, duration)

        if not match:
            return None

        days, hours, minutes, seconds = (
            int(value or 0) for value in match.groups()
        )

        return (
            days * 86400
            + hours * 3600
            + minutes * 60
            + seconds
        )

    @staticmethod
    def _is_excluded(title, description=""):
        """Identify obvious Shorts and unrelated video content."""
        text = f"{title} {description}".casefold()

        return any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in YouTubeService.EXCLUDED_TITLE_PATTERNS
        )

    def _get_video_durations(self, video_ids):
        """Retrieve video durations using the YouTube Videos API."""
        if not video_ids:
            return {}

        durations = {}

        for start in range(0, len(video_ids), 50):
            batch = video_ids[start:start + 50]

            payload = self._api_get(
                self.VIDEOS_API_URL,
                {
                    "key": self.api_key,
                    "part": "contentDetails",
                    "id": ",".join(batch),
                },
            )

            for item in payload.get("items", []):
                video_id = item.get("id")
                iso_duration = item.get(
                    "contentDetails", {}
                ).get("duration")

                if video_id and iso_duration:
                    durations[video_id] = self._parse_duration(
                        iso_duration
                    )

        return durations

    def search_videos(self, query, limit=20):
        """
        Search YouTube and return filtered video results.

        Each result contains:
        id, title, channel, description, thumbnail, url
        """
        query = (query or "").strip()

        if not query:
            return []

        if not self.api_key:
            raise RuntimeError(
                "YouTube API key is missing.\n\n"
                f"Expected configuration file: {ENV_FILE}\n"
                "Add YOUTUBE_API_KEY=your_key to that file "
                "and restart SkullCandy."
            )

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20

        limit = max(1, min(limit, 25))

        params = {
            "key": self.api_key,
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 25,
            "regionCode": "IN",
            "relevanceLanguage": "en",
            "safeSearch": "moderate",
        }

        payload = self._api_get(self.API_URL, params)

        candidates = []
        seen_ids = set()

        for item in payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})

            if not video_id or video_id in seen_ids:
                continue

            seen_ids.add(video_id)

            title = snippet.get("title", "Unknown title")
            description = snippet.get("description", "")

            if self._is_excluded(title, description):
                continue

            thumbnails = snippet.get("thumbnails", {})
            thumbnail = (
                thumbnails.get("high")
                or thumbnails.get("medium")
                or thumbnails.get("default")
                or {}
            )

            candidates.append(
                {
                    "id": video_id,
                    "title": title,
                    "channel": snippet.get(
                        "channelTitle", "Unknown channel"
                    ),
                    "description": description,
                    "thumbnail": thumbnail.get("url", ""),
                    "url": (
                        "https://www.youtube.com/watch?v="
                        f"{video_id}"
                    ),
                }
            )

        if not candidates:
            return []

        durations = self._get_video_durations(
            [video["id"] for video in candidates]
        )

        videos = []

        for video in candidates:
            duration = durations.get(video["id"])

            # Exclude short clips when duration is available.
            if duration is not None and duration < 60:
                continue

            videos.append(video)

            if len(videos) >= limit:
                break

        return videos