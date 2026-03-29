import json
from collections import defaultdict
import re


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


# Labels for core_buckets (used as theme labels)
BUCKET_LABELS = {
    "App Bugs & Glitches": "App Bugs & Glitches",
    "Crashes & App Stability": "Crashes & App Stability",
    "Performance & Slowness": "Performance & Slowness",
    "Payments, Refunds & Billing": "Payments, Refunds & Billing",
    "Offers, Coupons & Promotions": "Offers, Coupons & Promotions",
    "Delivery Delays & Logistics": "Delivery Delays & Logistics",
    "Order Accuracy & Wrong Items": "Order Accuracy & Wrong Items",
    "Food Quality & Safety": "Food Quality & Safety",
    "Customer Support Problems": "Customer Support Problems",
    "Login & Account Access": "Login & Account Access",
    "UI / UX Friction": "UI / UX Friction",
    "Feature Requests": "Feature Requests",
    "Pricing & Hidden Fees": "Pricing & Hidden Fees",
    "Trust, Fraud & Policy Complaints": "Trust, Fraud & Policy Complaints",
    "Positive Feedback / Praise": "Positive Feedback",
    "Other": "Other Feedback"
}

# Backward compat: old category labels
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

PHRASE_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "have", "has", "had",
    "was", "were", "are", "is", "its", "you", "your", "our", "they", "them",
    "their", "but", "very", "just", "then", "than", "also", "too", "into",
    "onto", "after", "before", "when", "what", "why", "how", "can", "cant",
    "cannot", "could", "would", "should", "please", "really", "my", "me",
    "i", "im", "we", "us"
}

PHRASE_KEYWORDS = {
    "payment", "paying", "refund", "order", "delivery", "support", "login",
    "otp", "crash", "cancelled", "canceled", "missing", "late", "delay",
    "restaurant", "food", "wallet", "coupon", "subscription", "billing",
    "driver", "tracking", "promo", "upi", "update", "version"
}


def _normalize_text(text):
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _slug(text):
    out = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return out[:40] or "phrase"


def _phrase_tokens(text):
    tokens = re.findall(r"[a-z0-9']+", _normalize_text(text))
    cleaned = [t for t in tokens if t not in PHRASE_STOPWORDS and len(t) >= 3]
    return cleaned


def _phrase_label(phrase):
    tokens = _phrase_tokens(phrase)[:4]
    if len(tokens) < 2:
        return ""
    return " ".join(tokens).title()


def _build_theme(core_bucket, label, group_items, theme_id, parent_theme_id=None,
                 phrase=None, category=None, dynamic_bucket=None):
    count = len(group_items)
    if count <= 0:
        return None

    avg_sentiment = sum(safe_float(i.get("sentiment", 0)) for i in group_items) / count
    avg_urgency = sum(safe_int(i.get("urgency", 3)) for i in group_items) / count

    entity_counts = defaultdict(int)
    for item in group_items:
        for entity in item.get("entities", []):
            entity_counts[str(entity).lower()] += 1
    top_entities = sorted(entity_counts, key=entity_counts.get, reverse=True)[:8]

    # Collect risk tags
    risk_counts = defaultdict(int)
    for item in group_items:
        risk_counts[item.get("risk_tag", "none")] += 1
    dominant_risk = max(risk_counts, key=risk_counts.get) if risk_counts else "none"

    # Backward compat category
    if not category:
        cats = [i.get("category", ["other"]) for i in group_items]
        flat_cats = [c[0] if isinstance(c, list) and c else c for c in cats]
        cat_counts = defaultdict(int)
        for c in flat_cats:
            cat_counts[c] += 1
        category = max(cat_counts, key=cat_counts.get) if cat_counts else "other"

    return {
        "theme_id": theme_id,
        "label": label,
        "core_bucket": core_bucket,
        "category": category,
        "risk_tag": dominant_risk,
        "count": count,
        "avg_sentiment": round(avg_sentiment, 2),
        "avg_urgency": round(avg_urgency, 2),
        "top_entities": top_entities,
        "items": group_items,
        "parent_theme_id": parent_theme_id,
        "phrase": phrase or "",
        "dynamic_bucket": dynamic_bucket
    }


def _extract_repeated_phrases(items, min_count=3, max_phrases=4):
    """Find repeated 2-3 word phrases across items using document-frequency counts."""
    phrase_items = defaultdict(set)

    for item in items:
        item_id = str(item.get("id", ""))
        text = _normalize_text(f"{item.get('summary', '')} {item.get('text', '')}")
        if not text:
            continue

        tokens = re.findall(r"[a-z0-9']+", text)
        if len(tokens) < 2:
            continue

        grams = set()
        for n in (2, 3):
            for i in range(len(tokens) - n + 1):
                chunk = tokens[i:i+n]
                if all(tok in PHRASE_STOPWORDS for tok in chunk):
                    continue
                phrase = " ".join(chunk).strip()
                cleaned_tokens = _phrase_tokens(phrase)
                if len(cleaned_tokens) < 2:
                    continue
                if len(phrase) < 6:
                    continue
                grams.add(" ".join(cleaned_tokens))

        for g in grams:
            phrase_items[g].add(item_id)

    candidates = []
    for phrase, ids in phrase_items.items():
        count = len(ids)
        if count < min_count:
            continue

        keyword_boost = 2 if any(k in phrase for k in PHRASE_KEYWORDS) else 0
        score = (count * 3) + keyword_boost
        candidates.append((phrase, count, score))

    candidates.sort(key=lambda x: (-x[2], -x[1], x[0]))
    return [p for p, _, _ in candidates[:max_phrases]]


def group_into_themes(items):
    if not items:
        return []

    # Primary grouping: by core_bucket
    bucket_groups = defaultdict(list)
    for item in items:
        bucket = item.get("core_bucket", "Other")
        bucket_groups[bucket].append(item)

    theme_objects = []

    for bucket, group_items in bucket_groups.items():
        label = BUCKET_LABELS.get(bucket, bucket)
        count = len(group_items)

        # Derive backward-compat category from the bucket
        cats = [i.get("category", ["other"]) for i in group_items]
        flat_cats = [c[0] if isinstance(c, list) and c else "other" for c in cats]
        cat_counts = defaultdict(int)
        for c in flat_cats:
            cat_counts[c] += 1
        primary_category = max(cat_counts, key=cat_counts.get) if cat_counts else "other"

        theme_id = _slug(bucket)

        base_theme = _build_theme(
            core_bucket=bucket,
            label=label,
            group_items=group_items,
            theme_id=theme_id,
            category=primary_category
        )
        if base_theme:
            theme_objects.append(base_theme)

        # Dynamic bucket subthemes: if items have dynamic_bucket assigned, create subthemes
        dynamic_groups = defaultdict(list)
        for item in group_items:
            db = item.get("dynamic_bucket")
            if db:
                dynamic_groups[db].append(item)

        for dyn_label, dyn_items in dynamic_groups.items():
            if len(dyn_items) < 3:
                continue
            sub_theme_id = f"{theme_id}__{_slug(dyn_label)}"
            subtheme = _build_theme(
                core_bucket=bucket,
                label=f"{label}: {dyn_label}",
                group_items=dyn_items,
                theme_id=sub_theme_id,
                parent_theme_id=theme_id,
                dynamic_bucket=dyn_label,
                category=primary_category
            )
            if subtheme:
                theme_objects.append(subtheme)

        # Also create phrase-based subthemes for large actionable buckets
        skip_buckets = {"Other", "Positive Feedback / Praise"}
        if bucket not in skip_buckets and count >= 10:
            if count >= 80:
                min_phrase_count = 8
            elif count >= 40:
                min_phrase_count = 6
            elif count >= 20:
                min_phrase_count = 4
            else:
                min_phrase_count = 3

            phrase_candidates = _extract_repeated_phrases(
                group_items, min_count=min_phrase_count, max_phrases=4
            )

            parent_tokens = set(_phrase_tokens(label))
            kept_phrase_tokens = []
            covered_item_ids = set()

            # Also skip phrases that overlap with existing dynamic bucket subthemes
            existing_dynamic_slugs = {_slug(dl) for dl in dynamic_groups.keys()}

            for phrase in phrase_candidates:
                phrase_norm = _normalize_text(phrase)
                phrase_token_set = set(_phrase_tokens(phrase_norm))
                if len(phrase_token_set) < 2:
                    continue

                if phrase_token_set.issubset(parent_tokens):
                    continue

                # Skip if overlaps with a dynamic bucket subtheme
                if _slug(phrase) in existing_dynamic_slugs:
                    continue

                duplicate = False
                for prev in kept_phrase_tokens:
                    if phrase_token_set.issubset(prev) or prev.issubset(phrase_token_set):
                        duplicate = True
                        break
                if duplicate:
                    continue

                matched = []
                for item in group_items:
                    text = _normalize_text(f"{item.get('summary', '')} {item.get('text', '')}")
                    if phrase_norm and phrase_norm in text:
                        matched.append(item)

                matched_count = len(matched)
                min_required = max(min_phrase_count, int(round(count * 0.12)))
                max_allowed = int(round(count * 0.72))

                if matched_count < min_required or matched_count > max_allowed:
                    continue

                matched_ids = {str(i.get("id", "")) for i in matched}
                overlap = len(matched_ids & covered_item_ids)
                if matched_ids and overlap / len(matched_ids) > 0.75:
                    continue

                pretty_phrase = _phrase_label(phrase)
                if not pretty_phrase:
                    continue

                kept_phrase_tokens.append(phrase_token_set)
                covered_item_ids |= matched_ids
                sub_id = f"{theme_id}__{_slug(phrase)}"
                subtheme = _build_theme(
                    core_bucket=bucket,
                    label=f"{label}: {pretty_phrase}",
                    group_items=matched,
                    theme_id=sub_id,
                    parent_theme_id=theme_id,
                    phrase=phrase,
                    category=primary_category
                )
                if subtheme:
                    theme_objects.append(subtheme)

    # Sort by count descending
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
