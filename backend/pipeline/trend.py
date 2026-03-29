import json
from collections import defaultdict
from datetime import datetime


def get_week_key(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00").replace("+00:00+00:00", "+00:00"))
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    except (ValueError, TypeError):
        return None


def detect_trends(themes):
    if not themes:
        return themes

    for theme in themes:
        buckets = defaultdict(int)

        for item in theme.get("items", []):
            date_str = item.get("date", "")
            week_key = get_week_key(date_str)
            if week_key is not None:
                buckets[week_key] += 1

        # Sort weeks (only valid week keys)
        sorted_weeks = sorted(buckets.keys())
        time_buckets = {week: buckets[week] for week in sorted_weeks}

        counts = list(time_buckets.values())

        # No valid date data — mark stable with no trend info
        if not counts:
            theme["time_buckets"] = {}
            theme["trend"] = "stable"
            theme["trend_pct"] = 0.0
            continue

        current = counts[-1] if len(counts) >= 1 else 0
        previous = counts[-2] if len(counts) >= 2 else 0
        earlier = counts[:-1] if len(counts) > 1 else []

        baseline = sum(earlier) / len(earlier) if earlier else 0

        if baseline == 0:
            if current > 0 and previous == 0:
                trend = "new"
                change_pct = 100.0
            else:
                trend = "stable"
                change_pct = 0.0
        else:
            change_pct = round(((current - baseline) / baseline) * 100, 1)

            if change_pct > 200:
                trend = "spiking"
            elif change_pct > 50:
                trend = "rising"
            elif change_pct < -30:
                trend = "declining"
            else:
                trend = "stable"

        theme["time_buckets"] = time_buckets
        theme["trend"] = trend
        theme["trend_pct"] = change_pct

        print(f"  📊 {theme.get('label', theme.get('theme_id', '?'))}: {trend} ({change_pct:+.1f}%) over {len(counts)} week(s)")

    return themes


if __name__ == "__main__":
    from grouping import group_into_themes
    from classify import classify_items

    test_items = [
        {"id": "1", "text": "App crashes every time I open it", "date": "2026-03-01T10:00:00"},
        {"id": "2", "text": "App crashes after update", "date": "2026-03-08T10:00:00"},
        {"id": "3", "text": "App crashes again after update", "date": "2026-03-15T10:00:00"},
        {"id": "4", "text": "Login OTP not working", "date": "2026-03-15T10:00:00"},
        {"id": "5", "text": "Please add dark mode", "date": "2026-03-22T10:00:00"},
        {"id": "6", "text": "App crashes every launch", "date": "2026-03-22T10:00:00"},
        {"id": "7", "text": "App crashes instantly", "date": "2026-03-22T10:00:00"}
    ]

    classified = classify_items(test_items)
    themes = group_into_themes(classified)
    themes = detect_trends(themes)

    print("\n=== THEMES WITH TRENDS ===\n")
    print(json.dumps(themes, indent=2))
