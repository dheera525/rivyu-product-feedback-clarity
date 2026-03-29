import json
from collections import defaultdict


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_int(val, default=3):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


CATEGORY_LABELS = {
    "bug": "Bug Reports",
    "crash": "App Crashes",
    "feature_request": "Feature Requests",
    "ux_issue": "UX Issues",
    "performance": "Performance Problems",
    "billing": "Billing & Payments",
    "login": "Login & Authentication",
    "onboarding": "Onboarding Issues",
    "praise": "Positive Feedback",
    "other": "Other Feedback"
}


def group_into_themes(items):
    if not items:
        return []

    # Group by primary category only — entities become tags within theme
    themes = defaultdict(list)

    for item in items:
        categories = item.get("category", [])
        primary_category = categories[0] if categories else "other"
        themes[primary_category].append(item)

    theme_objects = []

    for category, group_items in themes.items():
        count = len(group_items)

        avg_sentiment = sum(safe_float(i.get("sentiment", 0)) for i in group_items) / count
        avg_urgency = sum(safe_int(i.get("urgency", 3)) for i in group_items) / count

        # Collect top entities across all items in this theme
        entity_counts = defaultdict(int)
        for item in group_items:
            for entity in item.get("entities", []):
                entity_counts[str(entity).lower()] += 1
        top_entities = sorted(entity_counts, key=entity_counts.get, reverse=True)[:8]

        label = CATEGORY_LABELS.get(category, category.replace("_", " ").title())
        if category == "other" and count >= 5:
            label = "Mixed Feedback"

        theme_objects.append({
            "theme_id": category,
            "label": label,
            "category": category,
            "count": count,
            "avg_sentiment": round(avg_sentiment, 2),
            "avg_urgency": round(avg_urgency, 2),
            "top_entities": top_entities,
            "items": group_items
        })

    # Sort by count descending for stable, deterministic output
    theme_objects.sort(key=lambda t: t["count"], reverse=True)

    return theme_objects


if __name__ == "__main__":
    from classify import classify_items

    test_items = [
        {"id": "1", "text": "App crashes every time I open it"},
        {"id": "2", "text": "App crashes after latest update"},
        {"id": "3", "text": "Login OTP not working"},
        {"id": "4", "text": "Login fails again and again"},
        {"id": "5", "text": "Please add dark mode"}
    ]

    classified = classify_items(test_items)
    themes = group_into_themes(classified)

    print("\n=== THEMES ===\n")
    print(json.dumps(themes, indent=2))
