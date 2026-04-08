"""X (Twitter) feedback fetcher via X API v2."""

import hashlib
import os

import requests


API_BASES = ("https://api.x.com/2", "https://api.twitter.com/2")


def fetch_x_posts(username="", query="", count=80, bearer_token=None):
    """Fetch recent X posts either by username or search query."""
    token = (
        (bearer_token or "").strip()
        or os.getenv("X_BEARER_TOKEN", "").strip()
        or os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    )
    if not token:
        print("X bearer token missing. Set X_BEARER_TOKEN or pass bearer_token in request.")
        return []

    target_count = max(1, int(count or 80))
    username = (username or "").strip().lstrip("@")
    query = (query or "").strip()
    if not username and not query:
        print("Either username or query is required for X ingestion.")
        return []

    print(
        f"Fetching up to {target_count} X posts "
        + (f"for @{username}" if username else f"for query '{query}'")
        + "..."
    )

    headers = {"Authorization": f"Bearer {token}"}
    seen = set()
    items = []

    try:
        if query:
            items.extend(_fetch_search(query, target_count, headers, seen))
        else:
            items.extend(_fetch_user_tweets(username, target_count, headers, seen))
    except Exception as e:
        print(f"X fetch failed: {e}")
        return []

    items = [i for i in items if i.get("text") and len(i["text"]) > 4]
    print(f"Fetched {len(items)} X posts")
    return items[:target_count]


def _fetch_user_tweets(username, target_count, headers, seen):
    user_data = _request_json(
        f"/users/by/username/{username}",
        headers=headers,
        params={"user.fields": "id,name,username"}
    )
    user = user_data.get("data", {})
    user_id = user.get("id", "")
    if not user_id:
        return []

    pagination_token = None
    pages = 0
    max_pages = 8
    out = []

    while len(out) < target_count and pages < max_pages:
        params = {
            "max_results": min(100, target_count - len(out)),
            "tweet.fields": "created_at,lang,public_metrics",
            "exclude": "retweets,replies"
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        data = _request_json(f"/users/{user_id}/tweets", headers=headers, params=params)
        tweets = data.get("data", [])
        pagination_token = data.get("meta", {}).get("next_token")
        pages += 1

        if not tweets:
            break

        for tweet in tweets:
            item = _normalize_tweet(
                tweet=tweet,
                source_hint=f"@{username}",
                author=f"@{username}"
            )
            if not item:
                continue
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            out.append(item)
            if len(out) >= target_count:
                break

        if not pagination_token:
            break

    return out


def _fetch_search(query, target_count, headers, seen):
    out = []
    pagination_token = None
    pages = 0
    max_pages = 8

    effective_query = query
    if "-is:retweet" not in effective_query and "is:retweet" not in effective_query:
        effective_query = f"({effective_query}) -is:retweet"

    while len(out) < target_count and pages < max_pages:
        params = {
            "query": effective_query,
            "max_results": min(100, target_count - len(out)),
            "tweet.fields": "created_at,lang,public_metrics,author_id",
            "expansions": "author_id",
            "user.fields": "id,name,username"
        }
        if pagination_token:
            params["next_token"] = pagination_token

        data = _request_json("/tweets/search/recent", headers=headers, params=params)
        tweets = data.get("data", [])
        includes = data.get("includes", {})
        users = {u.get("id"): u for u in includes.get("users", []) if isinstance(u, dict)}
        pagination_token = data.get("meta", {}).get("next_token")
        pages += 1

        if not tweets:
            break

        for tweet in tweets:
            author_info = users.get(tweet.get("author_id"), {})
            author = author_info.get("username") or author_info.get("name") or "unknown"
            author = author if author.startswith("@") else f"@{author}"
            item = _normalize_tweet(
                tweet=tweet,
                source_hint=query[:64],
                author=author
            )
            if not item:
                continue
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            out.append(item)
            if len(out) >= target_count:
                break

        if not pagination_token:
            break

    return out


def _normalize_tweet(tweet, source_hint, author):
    text = (tweet.get("text") or "").strip()
    if not text:
        return None

    tweet_id = tweet.get("id") or hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
    metrics = tweet.get("public_metrics", {}) or {}

    return {
        "id": f"x_{tweet_id[:20]}",
        "source": "x",
        "text": text,
        "author": author or "anonymous",
        "date": tweet.get("created_at", ""),
        "rating": None,
        "metadata": {
            "tweet_id": tweet_id,
            "source_hint": source_hint,
            "lang": tweet.get("lang", ""),
            "likes": metrics.get("like_count", 0),
            "replies": metrics.get("reply_count", 0),
            "retweets": metrics.get("retweet_count", 0),
            "quotes": metrics.get("quote_count", 0)
        }
    }


def _request_json(path, headers, params=None):
    last_error = None
    for base in API_BASES:
        url = f"{base}{path}"
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 404 and "api.x.com" in base:
                # Fallback to legacy host if needed.
                continue
            payload = resp.json()
            if resp.status_code >= 400:
                msg = _extract_api_error(payload) or f"HTTP {resp.status_code}"
                raise RuntimeError(msg)
            return payload
        except Exception as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    raise RuntimeError("X API request failed.")


def _extract_api_error(payload):
    if not isinstance(payload, dict):
        return ""
    if "title" in payload and "detail" in payload:
        return f"{payload.get('title')}: {payload.get('detail')}"
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("detail") or "")
    return ""
