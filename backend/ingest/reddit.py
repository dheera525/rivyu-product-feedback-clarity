"""Reddit feedback fetcher using public JSON API (no auth needed)."""

import hashlib
import requests
from datetime import datetime, timezone


HEADERS = {"User-Agent": "Rivyu/1.0 (feedback-analysis-tool)"}


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

    items = []
    try:
        after = None
        pages = 0
        max_pages = 8
        seen_post_ids = set()

        if query:
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            base_params = {"q": query, "restrict_sr": "on", "sort": "new"}
        else:
            url = f"https://www.reddit.com/r/{subreddit}/new.json"
            base_params = {"sort": "new"}

        while len(items) < target_count and pages < max_pages:
            remaining = target_count - len(items)
            params = dict(base_params)
            params["limit"] = min(100, remaining)
            if after:
                params["after"] = after

            params["raw_json"] = 1
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
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

    except Exception as e:
        print(f"❌ Reddit fetch failed: {e}")
        return []

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
