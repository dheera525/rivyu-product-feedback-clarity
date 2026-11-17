"""Reddit feedback fetcher.

Uses Reddit's official API (app-only OAuth) when REDDIT_CLIENT_ID and
REDDIT_CLIENT_SECRET are set. Otherwise falls back to the public JSON
endpoints, which work from home connections but are usually blocked from
cloud hosts such as Render.
"""

import hashlib
import os
import threading
import time
import requests
from datetime import datetime, timezone


HEADERS = {"User-Agent": "web:rivyu-feedback-analysis:v1.1 (portfolio project)"}

_token_lock = threading.Lock()
_token = {"value": "", "expires_at": 0.0}


class RedditAccessError(RuntimeError):
    """Reddit refused the request (blocked, rate-limited or bad credentials)."""


def reddit_api_configured():
    return bool(os.getenv("REDDIT_CLIENT_ID", "").strip() and os.getenv("REDDIT_CLIENT_SECRET", "").strip())


def _oauth_token():
    """App-only OAuth token (client credentials grant), cached until expiry."""
    with _token_lock:
        if _token["value"] and _token["expires_at"] - time.time() > 60:
            return _token["value"]
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(os.getenv("REDDIT_CLIENT_ID", "").strip(), os.getenv("REDDIT_CLIENT_SECRET", "").strip()),
            data={"grant_type": "client_credentials"},
            headers=HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            raise RedditAccessError(f"Reddit rejected the API credentials (HTTP {resp.status_code}).")
        data = resp.json()
        _token["value"] = data.get("access_token", "")
        _token["expires_at"] = time.time() + int(data.get("expires_in", 3600) or 3600)
        if not _token["value"]:
            raise RedditAccessError("Reddit did not return an access token.")
        return _token["value"]


def fetch_reddit_posts(subreddit, query="", count=50):
    """Fetch posts from a subreddit, optionally filtered by search query."""
    subreddit = _normalize_subreddit(subreddit)
    if not subreddit:
        print("❌ Reddit subreddit is empty after normalization.")
        return []

    target_count = max(1, int(count or 50))
    print(
        f"🔍 Fetching up to {target_count} posts from r/{subreddit}"
        + (f" with query '{query}'" if query else "")
        + "..."
    )

    use_api = reddit_api_configured()
    host = "https://oauth.reddit.com" if use_api else "https://www.reddit.com"
    suffix = "" if use_api else ".json"
    headers = dict(HEADERS)
    if use_api:
        headers["Authorization"] = f"Bearer {_oauth_token()}"

    items = []
    try:
        after = None
        pages = 0
        max_pages = 8
        seen_post_ids = set()

        if query:
            url = f"{host}/r/{subreddit}/search{suffix}"
            base_params = {"q": query, "restrict_sr": "on", "sort": "new"}
        else:
            url = f"{host}/r/{subreddit}/new{suffix}"
            base_params = {"sort": "new"}

        while len(items) < target_count and pages < max_pages:
            remaining = target_count - len(items)
            params = dict(base_params)
            params["limit"] = min(100, remaining)
            if after:
                params["after"] = after

            params["raw_json"] = 1
            resp = requests.get(url, headers=headers, params=params, timeout=15, allow_redirects=False)
            if resp.status_code in (401, 403, 429):
                if resp.status_code == 403 and _is_private_or_banned(resp):
                    print(f"❌ r/{subreddit} is private or banned")
                    return []
                raise RedditAccessError(f"Reddit refused the request (HTTP {resp.status_code}).")
            if resp.status_code in (301, 302, 404):
                # Reddit redirects or 404s for subreddits that don't exist.
                print(f"❌ r/{subreddit} not found (HTTP {resp.status_code})")
                return []
            resp.raise_for_status()
            data = resp.json()

            listing = data.get("data", {})
            posts = listing.get("children", [])
            after = listing.get("after")
            pages += 1

            if not posts:
                break

            for post in posts:
                d = post.get("data", {})
                raw_post_id = d.get("id", "")
                text = d.get("title", "")
                body = d.get("selftext", "")
                if body:
                    text = f"{text}. {body}"

                post_id = raw_post_id or hashlib.md5(text.encode()).hexdigest()[:12]
                if post_id in seen_post_ids:
                    continue
                seen_post_ids.add(post_id)

                created = d.get("created_utc", 0)
                date_str = datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else ""

                items.append({
                    "id": f"rd_{post_id}",
                    "source": "reddit",
                    "text": text.strip(),
                    "author": d.get("author", "anonymous"),
                    "date": date_str,
                    "rating": None,
                    "metadata": {
                        "subreddit": f"r/{subreddit}",
                        "upvotes": d.get("ups", 0),
                        "num_comments": d.get("num_comments", 0),
                        "url": d.get("url", "")
                    }
                })

                if len(items) >= target_count:
                    break

            if not after:
                break

    except RedditAccessError:
        raise
    except Exception as e:
        print(f"❌ Reddit fetch failed: {e}")
        if not items:
            raise RedditAccessError(f"Couldn't reach Reddit: {e}")

    items = [i for i in items if i["text"] and len(i["text"]) > 10]
    print(f"✅ Fetched {len(items)} Reddit posts")
    return items


def _normalize_subreddit(subreddit):
    """Accept values like 'whatsapp', 'r/whatsapp', '/r/whatsapp'."""
    sub = (subreddit or "").strip().lower()
    if not sub:
        return ""
    if sub.startswith("/r/"):
        sub = sub[3:]
    elif sub.startswith("r/"):
        sub = sub[2:]
    return sub.strip("/")


def _is_private_or_banned(resp):
    try:
        reason = (resp.json() or {}).get("reason", "")
    except ValueError:
        return False
    return reason in {"private", "banned", "quarantined", "gold_only"}
