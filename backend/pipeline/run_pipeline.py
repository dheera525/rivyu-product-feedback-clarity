import json
from classify import classify_items
from grouping import group_into_themes
from trend import detect_trends
from alerts import generate_alerts


def run_pipeline(raw_items):
    if not raw_items:
        print("⚠️  run_pipeline called with empty input")
        return {
            "processed_items": [],
            "themes": [],
            "alerts": [],
            "stats": {"total_items": 0, "total_themes": 0, "total_alerts": 0, "sources": []}
        }

    print(f"🚀 Pipeline starting with {len(raw_items)} items...")

    processed_items = classify_items(raw_items)
    print(f"📋 Classification done: {len(processed_items)} items processed")

    try:
        themes = group_into_themes(processed_items)
        print(f"📦 Grouping done: {len(themes)} themes found")
    except Exception as e:
        print(f"❌ Grouping failed: {e}")
        themes = []

    try:
        themes = detect_trends(themes)
        print(f"📈 Trend detection done")
    except Exception as e:
        print(f"❌ Trend detection failed: {e}")

    try:
        alerts = generate_alerts(themes)
        print(f"🔔 Alert generation done: {len(alerts)} alerts raised")
    except Exception as e:
        print(f"❌ Alert generation failed: {e}")
        alerts = []

    stats = {
        "total_items": len(processed_items),
        "total_themes": len(themes),
        "total_alerts": len(alerts),
        "sources": list({item.get("source", "unknown") for item in raw_items})
    }

    print(f"✅ Pipeline complete — {stats['total_items']} items, {stats['total_themes']} themes, {stats['total_alerts']} alerts")

    return {
        "processed_items": processed_items,
        "themes": themes,
        "alerts": alerts,
        "stats": stats
    }


if __name__ == "__main__":
    test_items = [
        {"id": "1", "text": "App crashes every time I open it", "date": "2026-03-01T10:00:00", "source": "google_play"},
        {"id": "2", "text": "Login OTP not working", "date": "2026-03-15T10:00:00", "source": "google_play"},
        {"id": "3", "text": "Please add dark mode", "date": "2026-03-22T10:00:00", "source": "reddit"}
    ]

    result = run_pipeline(test_items)
    print(json.dumps(result, indent=2))
