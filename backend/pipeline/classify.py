import os
import re
import json
import time
from dotenv import load_dotenv
from llm_client import call_llm

load_dotenv()


ALLOWED_CATEGORIES = [
    "bug",
    "crash",
    "feature_request",
    "ux_issue",
    "performance",
    "billing",
    "login",
    "onboarding",
    "praise",
    "other"
]

ALLOWED_CATEGORIES_SET = set(ALLOWED_CATEGORIES)

STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "have", "has", "had",
    "was", "were", "are", "is", "its", "you", "your", "our", "they", "them",
    "their", "but", "not", "very", "just", "after", "before", "when", "what",
    "why", "how", "can", "cant", "cannot", "could", "would", "should", "please",
    "app", "apps"
}

CATEGORY_KEYWORDS = {
    "crash": [
        "crash", "crashes", "crashed", "freeze", "stuck", "force close",
        "won't open", "cant open", "cannot open", "startup", "launch"
    ],
    "login": [
        "login", "log in", "sign in", "signin", "otp", "password", "verification",
        "verify", "authenticate", "authentication", "cannot access", "can't access"
    ],
    "billing": [
        "charged", "charge", "billing", "payment", "refund", "subscription",
        "invoice", "credit card", "debit card", "money"
    ],
    "performance": [
        "slow", "lag", "laggy", "sluggish", "loading", "takes forever",
        "performance", "battery drain", "overheat", "choppy"
    ],
    "onboarding": [
        "onboarding", "setup", "tutorial", "getting started", "first time",
        "new user", "confusing to start"
    ],
    "feature_request": [
        "feature request", "please add", "can you add", "need feature",
        "would love", "wishlist", "dark mode", "widget", "support for"
    ],
    "ux_issue": [
        "confusing", "hard to use", "difficult", "not intuitive", "ui",
        "ux", "navigation", "cant find", "can't find", "search is useless"
    ],
    "praise": [
        "love", "great", "awesome", "excellent", "amazing", "fantastic",
        "good app", "best app", "works well", "thank you", "super"
    ],
}

POSITIVE_HINTS = ["love", "great", "awesome", "excellent", "amazing", "fantastic", "good", "best", "helpful", "smooth"]
NEGATIVE_HINTS = ["bad", "worst", "broken", "error", "issue", "problem", "fail", "failed", "unusable", "frustrating", "terrible", "awful"]
HIGH_URGENCY_HINTS = ["asap", "urgent", "immediately", "can't use", "cannot use", "unusable", "every time", "all users", "lost data"]
LOW_URGENCY_HINTS = ["would love", "nice to have", "feature request", "please add"]
ENTITY_HINTS = [
    "otp", "dark mode", "notification", "notifications", "search", "widget", "gallery",
    "login", "payment", "subscription", "onboarding", "tutorial"
]


def _has_llm_keys():
    return bool((os.getenv("GEMINI_API_KEY", "").strip()) or (os.getenv("OPENAI_API_KEY", "").strip()))


def _keyword_hits(text, keywords):
    hits = 0
    for kw in keywords:
        if " " in kw:
            if kw in text:
                hits += 2
        elif re.search(rf"\b{re.escape(kw)}\b", text):
            hits += 1
    return hits


def _build_summary(text, max_words=15):
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    if not words:
        return ""
    return " ".join(words[:max_words])


def _extract_entities(text):
    lower = (text or "").lower()
    entities = []

    for version in re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", text or ""):
        if version not in entities:
            entities.append(version)

    for hint in ENTITY_HINTS:
        if hint in lower and hint not in entities:
            entities.append(hint)

    tokens = re.findall(r"[a-z][a-z0-9_+-]{2,}", lower)
    freq = {}
    for tok in tokens:
        if tok in STOPWORDS:
            continue
        freq[tok] = freq.get(tok, 0) + 1

    for tok, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
        if tok not in entities:
            entities.append(tok)
        if len(entities) >= 8:
            break

    return entities[:8]


def heuristic_classify_item(original):
    text = str(original.get("text", "") or "")
    lower = text.lower()

    scores = {cat: _keyword_hits(lower, kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    best_cat = max(scores, key=scores.get) if scores else "other"
    best_score = scores.get(best_cat, 0)
    category = [best_cat] if best_score > 0 else ["other"]

    pos_hits = _keyword_hits(lower, POSITIVE_HINTS)
    neg_hits = _keyword_hits(lower, NEGATIVE_HINTS)
    raw_sent = pos_hits - neg_hits
    sentiment = 0.0 if raw_sent == 0 else max(-1.0, min(1.0, raw_sent / 4.0))

    if category[0] == "praise" and sentiment < 0.3:
        sentiment = 0.6
    if category[0] in {"crash", "login", "billing", "performance"} and sentiment > -0.2:
        sentiment = -0.5

    urgency = 3
    if category[0] in {"crash", "login", "billing"}:
        urgency = 4
    elif category[0] in {"feature_request", "praise"}:
        urgency = 2

    if _keyword_hits(lower, HIGH_URGENCY_HINTS) > 0:
        urgency = 5
    elif _keyword_hits(lower, LOW_URGENCY_HINTS) > 0 and urgency > 3:
        urgency = 3

    confidence = 0.25
    if category[0] != "other":
        confidence = min(0.9, 0.65 + (best_score * 0.08))
    elif abs(sentiment) >= 0.5:
        confidence = 0.45

    return {
        "id": str(original.get("id", "unknown")),
        "category": category,
        "sentiment": round(sentiment, 2),
        "urgency": int(max(1, min(5, urgency))),
        "summary": _build_summary(text, max_words=15),
        "entities": _extract_entities(text),
        "_confidence": round(confidence, 2)
    }


def chunk_list(items, size=15):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def build_prompt(batch):
    minimal_batch = [{"id": item.get("id", ""), "text": item.get("text", "")} for item in batch]

    return f"""
You are a product feedback analyst.

Return ONLY valid JSON array.

For each feedback item, return:
- id
- category (array, choose ONLY from: {ALLOWED_CATEGORIES})
- sentiment (float from -1.0 to 1.0)
- urgency (integer 1 to 5)
- summary (max 15 words)
- entities (array of features, screens, versions, devices, keywords)

Rules:
- Be strict and concise.
- The FIRST category should be the main category.
- If unclear, use "other".
- Do not include any explanation outside JSON.

Input:
{json.dumps(minimal_batch, indent=2)}
"""


def classify_batch(batch, max_retries=2):
    if not _has_llm_keys():
        # Fast deterministic path for local/demo environments without API keys.
        return [heuristic_classify_item(item) for item in batch]

    prompt = build_prompt(batch)
    last_error = None

    for attempt in range(max_retries):
        try:
            output = call_llm(prompt, expect_json=True)
            parsed = json.loads(output)

            if not isinstance(parsed, list):
                raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

            return parsed

        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            if any(k in error_str for k in [
                "gemini quota exceeded",
                "quota exceeded",
                "resource_exhausted",
                "openai_api_key is not configured",
                "temporarily blocked due to quota"
            ]):
                print(f"⚠️  LLM quota/config issue, switching to heuristic classification for this batch: {e}")
                return [heuristic_classify_item(item) for item in batch]
            if any(k in error_str for k in [
                "nodename nor servname provided",
                "name or service not known",
                "temporary failure in name resolution",
                "connection error",
                "failed to establish a new connection"
            ]):
                print(f"⚠️  LLM network unavailable, switching to heuristic classification for this batch: {e}")
                return [heuristic_classify_item(item) for item in batch]
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"⚠️  Classify attempt {attempt + 1}/{max_retries} failed: {e} — retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"❌ Classify attempt {attempt + 1}/{max_retries} failed: {e} — no retries left")

    raise last_error


def normalize_item(item):
    # Validate category: must be a list of allowed values
    raw_cats = item.get("category", [])
    if not isinstance(raw_cats, list):
        raw_cats = [raw_cats] if isinstance(raw_cats, str) else []

    validated_cats = [c for c in raw_cats if c in ALLOWED_CATEGORIES_SET]
    item["category"] = validated_cats[:2] if validated_cats else ["other"]

    # Clamp sentiment and urgency
    try:
        item["sentiment"] = max(-1.0, min(1.0, float(item.get("sentiment", 0))))
    except (TypeError, ValueError):
        item["sentiment"] = 0.0

    try:
        item["urgency"] = max(1, min(5, int(item.get("urgency", 3))))
    except (TypeError, ValueError):
        item["urgency"] = 3

    item["summary"] = str(item.get("summary", ""))[:80]

    if not isinstance(item.get("entities"), list):
        item["entities"] = []
    else:
        # Ensure all entities are strings
        item["entities"] = [str(e) for e in item["entities"] if e is not None]

    return item


def make_fallback_item(original):
    """Create a fully-shaped classified item when LLM fails to return one."""
    heuristic = heuristic_classify_item(original)
    return {
        "id": original.get("id", "unknown"),
        "text": original.get("text", ""),
        "author": original.get("author", "anonymous"),
        "date": original.get("date", ""),
        "source": original.get("source", "unknown"),
        "rating": original.get("rating", None),
        "metadata": original.get("metadata", {}),
        "category": heuristic["category"],
        "sentiment": heuristic["sentiment"],
        "urgency": heuristic["urgency"],
        "summary": heuristic["summary"][:80],
        "entities": heuristic["entities"]
    }


def merge_with_original(original_batch, classified_batch):
    # Guard: skip non-dict entries and normalize id to string for reliable lookup
    classified_map = {}
    for item in classified_batch:
        if not isinstance(item, dict) or "id" not in item:
            continue
        classified_map[str(item["id"])] = item

    if len(classified_map) != len(classified_batch):
        print(f"⚠️  LLM returned {len(classified_batch)} items, {len(classified_map)} usable (expected {len(original_batch)})")

    merged = []

    # Process all original items — use classified data if available, fallback otherwise
    for original in original_batch:
        item_id = str(original.get("id", "unknown"))
        classified = classified_map.get(item_id)
        heuristic = heuristic_classify_item(original)

        if classified is None:
            print(f"⚠️  Item '{item_id}' missing from LLM response, using fallback")
            classified = make_fallback_item(original)

        classified = normalize_item(classified)

        # Heuristic rescue: avoid collapsing too many rows into "other".
        if (
            classified["category"] == ["other"]
            and heuristic["category"] != ["other"]
            and heuristic["_confidence"] >= 0.65
        ):
            classified["category"] = heuristic["category"]
            classified["urgency"] = heuristic["urgency"]
            classified["sentiment"] = heuristic["sentiment"]

        if not classified.get("summary", "").strip():
            classified["summary"] = heuristic["summary"][:80]
        if not classified.get("entities"):
            classified["entities"] = heuristic["entities"]
        if classified["urgency"] == 3 and heuristic["urgency"] != 3:
            classified["urgency"] = heuristic["urgency"]

        merged_item = {
            "id": item_id,
            "text": original.get("text", ""),
            "author": original.get("author", "anonymous"),
            "date": original.get("date", ""),
            "source": original.get("source", "unknown"),
            "rating": original.get("rating", None),
            "metadata": original.get("metadata", {}),
            "category": classified["category"],
            "sentiment": classified["sentiment"],
            "urgency": classified["urgency"],
            "summary": classified["summary"],
            "entities": classified["entities"]
        }

        merged.append(merged_item)

    return merged


def classify_items(items):
    if not items:
        return []

    all_results = []

    for idx, batch in enumerate(chunk_list(items, size=15), start=1):
        print(f"Classifying batch {idx} ({len(batch)} items)...")

        try:
            classified = classify_batch(batch)
            merged = merge_with_original(batch, classified)
            all_results.extend(merged)
        except Exception as e:
            print(f"❌ Batch {idx} failed after retries: {e}")
            print(f"   ↳ Generating fallback for {len(batch)} items in this batch")
            for item in batch:
                all_results.append(make_fallback_item(item))

    print(f"✅ Classified {len(all_results)}/{len(items)} items")
    return all_results


if __name__ == "__main__":
    test_items = [
        {"id": "1", "text": "App crashes every time I open it", "date": "2026-03-01T10:00:00", "source": "google_play"},
        {"id": "2", "text": "Login OTP never arrives", "date": "2026-03-08T10:00:00", "source": "google_play"},
        {"id": "3", "text": "Love the new design, looks clean", "date": "2026-03-10T10:00:00", "source": "reddit"},
        {"id": "4", "text": "Too slow after latest update", "date": "2026-03-15T10:00:00", "source": "google_play"},
        {"id": "5", "text": "Please add dark mode", "date": "2026-03-22T10:00:00", "source": "reddit"}
    ]

    results = classify_items(test_items)

    print("\n=== FINAL OUTPUT ===\n")
    print(json.dumps(results, indent=2))
