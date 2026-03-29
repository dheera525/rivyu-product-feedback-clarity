import json
from collections import Counter
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

    # Step 1: Classify (includes dynamic bucket assignment)
    processed_items = classify_items(raw_items)
    print(f"📋 Classification done: {len(processed_items)} items processed")

    # Step 2: Group into themes (uses core_bucket + dynamic_bucket)
    try:
        themes = group_into_themes(processed_items)
        print(f"📦 Grouping done: {len(themes)} themes found")
    except Exception as e:
        print(f"❌ Grouping failed: {e}")
        themes = []

    # Step 3: Detect trends
    try:
        themes = detect_trends(themes)
        print(f"📈 Trend detection done")
    except Exception as e:
        print(f"❌ Trend detection failed: {e}")

    # Step 4: Generate alerts (uses core_bucket + risk_tag)
    try:
        alerts = generate_alerts(themes)
        print(f"🔔 Alert generation done: {len(alerts)} alerts raised")
    except Exception as e:
        print(f"❌ Alert generation failed: {e}")
        alerts = []

    # Compute stats
    sources = list({item.get("source", "unknown") for item in raw_items})
    bucket_dist = Counter(i.get("core_bucket", "Other") for i in processed_items)
    risk_dist = Counter(i.get("risk_tag", "none") for i in processed_items)

    stats = {
        "total_items": len(processed_items),
        "total_themes": len(themes),
        "total_alerts": len(alerts),
        "sources": sources,
        "bucket_distribution": dict(bucket_dist.most_common()),
        "risk_distribution": dict(risk_dist.most_common()),
    }

    # Debug: print top themes
    primary_themes = [t for t in themes if not t.get("parent_theme_id")]
    if primary_themes:
        print("\n🏷️  Top Themes:")
        for t in primary_themes[:8]:
            print(f"   [{t.get('core_bucket', '?')}] {t.get('label', '?')} — "
                  f"{t.get('count', 0)} items, risk: {t.get('risk_tag', 'none')}, "
                  f"trend: {t.get('trend', 'stable')}")

    print(f"\n✅ Pipeline complete — {stats['total_items']} items, "
          f"{stats['total_themes']} themes, {stats['total_alerts']} alerts")

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
