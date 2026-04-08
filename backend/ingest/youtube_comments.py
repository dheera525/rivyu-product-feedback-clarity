"""YouTube top-level comment fetcher using YouTube Data API v3."""

import hashlib
import os
from urllib.parse import parse_qs, urlparse

import requests


def fetch_youtube_comments(video_ref, count=100, api_key=None):
    """Fetch recent top-level YouTube comments for one video."""
    key = (api_key or os.getenv("YOUTUBE_API_KEY", "")).strip()
    if not key:
        print("YOUTUBE_API_KEY missing (or pass api_key in request).")
        return []

    video_id = _extract_video_id(video_ref)
    if not video_id:
        print(f"Invalid YouTube video id/url: {video_ref}")
        return []

    target_count = max(1, int(count or 100))
    print(f"Fetching up to {target_count} YouTube comments for video '{video_id}'...")

    items = []
    page_token = None
    pages = 0
    max_pages = 10

    try:
        while len(items) < target_count and pages < max_pages:
            params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": min(100, target_count - len(items)),
                "order": "time",
                "textFormat": "plainText",
                "key": key
            }
            if page_token:
                params["pageToken"] = page_token

            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/commentThreads",
                params=params,
                timeout=20
            )
            data = resp.json()
            if resp.status_code >= 400:
                msg = _extract_api_error(data) or f"HTTP {resp.status_code}"
                print(f"YouTube API error: {msg}")
                return []

            threads = data.get("items", [])
            page_token = data.get("nextPageToken")
            pages += 1

            if not threads:
                break

            for thread in threads:
                snippet = (
                    thread.get("snippet", {})
                    .get("topLevelComment", {})
                    .get("snippet", {})
                )
                text = (snippet.get("textDisplay") or snippet.get("textOriginal") or "").strip()
                if not text:
                    continue

                comment_id = (
                    thread.get("snippet", {}).get("topLevelComment", {}).get("id")
                    or hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
                )
                author = snippet.get("authorDisplayName") or "anonymous"

                items.append({
                    "id": f"ytc_{comment_id[:20]}",
                    "source": "youtube_comments",
                    "text": text,
                    "author": author,
                    "date": snippet.get("publishedAt", ""),
                    "rating": None,
                    "metadata": {
                        "video_id": video_id,
                        "author_channel_id": snippet.get("authorChannelId", {}).get("value", ""),
                        "like_count": snippet.get("likeCount", 0),
                        "reply_count": thread.get("snippet", {}).get("totalReplyCount", 0)
                    }
                })

                if len(items) >= target_count:
                    break

            if not page_token:
                break

    except Exception as e:
        print(f"YouTube fetch failed: {e}")
        return []

    items = [i for i in items if len(i.get("text", "")) > 4]
    print(f"Fetched {len(items)} YouTube comments")
    return items


def _extract_video_id(video_ref):
    raw = (video_ref or "").strip()
    if not raw:
        return ""
    if len(raw) == 11 and all(c.isalnum() or c in "-_" for c in raw):
        return raw

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()

    if "youtu.be" in host:
        maybe = (parsed.path or "").strip("/").split("/")[0]
        return maybe if len(maybe) == 11 else ""

    if "youtube.com" in host or "m.youtube.com" in host:
        q = parse_qs(parsed.query or "")
        if "v" in q and q["v"]:
            maybe = q["v"][0]
            if len(maybe) == 11:
                return maybe

        parts = [p for p in (parsed.path or "").split("/") if p]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            maybe = parts[1]
            if len(maybe) == 11:
                return maybe

    return ""


def _extract_api_error(payload):
    if not isinstance(payload, dict):
        return ""
    err = payload.get("error", {})
    if isinstance(err, dict):
        if "message" in err:
            return str(err.get("message"))
        details = err.get("errors", [])
        if details and isinstance(details, list):
            first = details[0]
            if isinstance(first, dict):
                return str(first.get("message", ""))
    return ""
