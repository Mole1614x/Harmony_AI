
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi


class JamendoService:
    """Search and retrieve playable tracks from the Jamendo API."""

    API_URL = "https://api.jamendo.com/v3.0/tracks/"

    def __init__(self, client_id=None):
        self.client_id = (
            client_id
            or os.environ.get("JAMENDO_CLIENT_ID")
            or "380e8bf3"
        )

        self.ssl_context = ssl.create_default_context(
            cafile=certifi.where()
        )

    def search_tracks(self, query, limit=20):
        query = str(query or "").strip()

        if not query:
            return []

        params = {
            "client_id": self.client_id,
            "format": "json",
            "limit": max(1, min(int(limit), 50)),
            "search": query,
        }

        url = f"{self.API_URL}?{urlencode(params)}"

        request = Request(
            url,
            headers={
                "User-Agent": "SkullCandyMusicPlayer/1.0",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(
                request,
                timeout=20,
                context=self.ssl_context,
            ) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )

        except HTTPError as exc:
            raise RuntimeError(
                f"Jamendo API error: HTTP {exc.code} - {exc.reason}"
            ) from exc

        except URLError as exc:
            reason = getattr(exc, "reason", exc)

            if isinstance(reason, ssl.SSLError):
                raise RuntimeError(
                    "SSL certificate verification failed. "
                    "Check your Python certificates or network proxy."
                ) from exc

            raise RuntimeError(
                f"Could not connect to Jamendo: {reason}"
            ) from exc

        except (TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"Could not retrieve Jamendo results: {exc}"
            ) from exc

        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                "Jamendo returned an invalid JSON response."
            ) from exc

        headers = payload.get("headers", {})

        if headers.get("status") != "success":
            message = (
                headers.get("error_message")
                or headers.get("error_message_to_developer")
                or "Unknown Jamendo API error."
            )
            raise RuntimeError(f"Jamendo API request failed: {message}")

        results = payload.get("results", [])
        tracks = []

        for item in results:
            stream_url = item.get("audio")

            # Only include tracks that have a playable stream URL.
            if not stream_url:
                continue

            tracks.append({
                "id": str(item.get("id") or ""),
                "title": item.get("name") or "Unknown Title",
                "artist": item.get("artist_name") or "Unknown Artist",
                "album": item.get("album_name") or "Unknown Album",
                "duration": int(item.get("duration") or 0),
                "image": item.get("image") or "",
                "audio": stream_url,
                "license_url": item.get("license_ccurl") or "",
                "artist_id": str(item.get("artist_id") or ""),
                "album_id": str(item.get("album_id") or ""),
                "releasedate": item.get("releasedate") or "",
                "source": "Jamendo",
                "license_flags": {
                    "non_commercial": bool(item.get("ccnc", False)),
                    "no_derivatives": bool(item.get("ccnd", False)),
                    "share_alike": bool(item.get("ccsa", False)),
                    "pro_licensing": bool(
                        item.get("prolicensing", False)
                    ),
                    "pro_background": bool(
                        item.get("probackground", False)
                    ),
                },
            })

        # Helpful diagnostic if the API returned tracks but none
        # contained a playable audio URL.
        if results and not tracks:
            print(
                f"Jamendo returned {len(results)} results for "
                f"{query!r}, but none contained an audio URL."
            )

        return tracks
