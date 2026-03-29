"""Google Play Store review scraper using google-play-scraper."""

import hashlib
from datetime import datetime


def fetch_playstore_reviews(app_id, count=100):
    """Fetch reviews from Google Play Store and normalize to raw schema."""
    from google_play_scraper import Sort, reviews

    print(f"📱 Fetching up to {count} reviews for '{app_id}' from Google Play...")

    try:
        result, _ = reviews(
            app_id,
            lang="en",
            country="us",
            sort=Sort.NEWEST,
            count=count
        )
    except Exception as e:
        print(f"❌ Google Play scrape failed: {e}")
        return []

    items = []
    for r in result:
        review_id = r.get("reviewId", hashlib.md5(r.get("content", "").encode()).hexdigest()[:12])
        date = r.get("at")
        if isinstance(date, datetime):
            date_str = date.isoformat()
        else:
            date_str = str(date) if date else ""

        items.append({
            "id": f"gp_{review_id[:16]}",
            "source": "google_play",
            "text": r.get("content", ""),
            "author": r.get("userName", "anonymous"),
            "date": date_str,
            "rating": r.get("score", None),
            "metadata": {
                "app_id": app_id,
                "app_version": r.get("reviewCreatedVersion", ""),
                "thumbs_up": r.get("thumbsUpCount", 0)
            }
        })

    items = [i for i in items if i["text"] and i["text"].strip()]
    print(f"✅ Fetched {len(items)} Play Store reviews")
    return items
