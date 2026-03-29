import os
import re
import json
import time
from dotenv import load_dotenv
from llm_client import call_llm

load_dotenv()

# ── Core Buckets (fixed, always available) ─────────────────────────

CORE_BUCKETS = [
    "App Bugs & Glitches",
    "Crashes & App Stability",
    "Performance & Slowness",
    "Payments, Refunds & Billing",
    "Offers, Coupons & Promotions",
    "Delivery Delays & Logistics",
    "Order Accuracy & Wrong Items",
    "Food Quality & Safety",
    "Customer Support Problems",
    "Login & Account Access",
    "UI / UX Friction",
    "Feature Requests",
    "Pricing & Hidden Fees",
    "Trust, Fraud & Policy Complaints",
    "Positive Feedback / Praise",
    "Other"
]

CORE_BUCKETS_SET = set(CORE_BUCKETS)

# Backward compat — old categories still used in some rendering paths
ALLOWED_CATEGORIES = [
    "bug", "crash", "feature_request", "ux_issue", "performance",
    "billing", "login", "onboarding", "praise", "other"
]
ALLOWED_CATEGORIES_SET = set(ALLOWED_CATEGORIES)

# ── Bucket → derived fields ────────────────────────────────────────

BUCKET_TO_CATEGORY = {
    "App Bugs & Glitches": "bug",
    "Crashes & App Stability": "crash",
    "Performance & Slowness": "performance",
    "Payments, Refunds & Billing": "billing",
    "Offers, Coupons & Promotions": "billing",
    "Delivery Delays & Logistics": "performance",
    "Order Accuracy & Wrong Items": "bug",
    "Food Quality & Safety": "other",
    "Customer Support Problems": "ux_issue",
    "Login & Account Access": "login",
    "UI / UX Friction": "ux_issue",
    "Feature Requests": "feature_request",
    "Pricing & Hidden Fees": "billing",
    "Trust, Fraud & Policy Complaints": "other",
    "Positive Feedback / Praise": "praise",
    "Other": "other"
}

BUCKET_TO_ISSUE_TYPE = {
    "App Bugs & Glitches": "app_bugs",
    "Crashes & App Stability": "crashes_stability",
    "Performance & Slowness": "performance_slowness",
    "Payments, Refunds & Billing": "billing_payments",
    "Offers, Coupons & Promotions": "offers_promotions",
    "Delivery Delays & Logistics": "delivery_logistics",
    "Order Accuracy & Wrong Items": "order_accuracy",
    "Food Quality & Safety": "food_quality_safety",
    "Customer Support Problems": "customer_support",
    "Login & Account Access": "login_account",
    "UI / UX Friction": "ui_ux_friction",
    "Feature Requests": "feature_requests",
    "Pricing & Hidden Fees": "pricing_fees",
    "Trust, Fraud & Policy Complaints": "trust_fraud_policy",
    "Positive Feedback / Praise": "positive_feedback",
    "Other": "other"
}

BUCKET_TO_DEFAULT_RISK = {
    "App Bugs & Glitches": "churn_risk",
    "Crashes & App Stability": "stability_risk",
    "Performance & Slowness": "ux_risk",
    "Payments, Refunds & Billing": "revenue_risk",
    "Offers, Coupons & Promotions": "revenue_risk",
    "Delivery Delays & Logistics": "churn_risk",
    "Order Accuracy & Wrong Items": "trust_risk",
    "Food Quality & Safety": "trust_risk",
    "Customer Support Problems": "support_risk",
    "Login & Account Access": "churn_risk",
    "UI / UX Friction": "ux_risk",
    "Feature Requests": "retention_risk",
    "Pricing & Hidden Fees": "revenue_risk",
    "Trust, Fraud & Policy Complaints": "trust_risk",
    "Positive Feedback / Praise": "none",
    "Other": "none"
}

RISK_TAGS = {"revenue_risk", "churn_risk", "trust_risk", "ux_risk",
             "stability_risk", "support_risk", "retention_risk", "none"}

# ── Keyword detection for heuristic classification ─────────────────

BUCKET_KEYWORDS = {
    "Crashes & App Stability": [
        "crash", "crashes", "crashed", "freeze", "frozen", "stuck", "force close",
        "won't open", "cant open", "cannot open", "startup", "launch",
        "app not opening", "stopped working", "keeps closing", "black screen"
    ],
    "App Bugs & Glitches": [
        "bug", "error", "not working", "doesn't work", "doesnt work", "broken",
        "glitch", "malfunction", "not responding", "blank screen",
        "notification", "notifications"
    ],
    "Login & Account Access": [
        "login", "log in", "sign in", "signin", "otp", "password", "verification",
        "verify", "authenticate", "authentication", "cannot access", "can't access",
        "account blocked", "account locked", "forgot password", "two factor"
    ],
    "Payments, Refunds & Billing": [
        "charged", "charge", "billing", "payment", "refund", "subscription",
        "invoice", "credit card", "debit card", "money deducted",
        "wallet", "extra charge", "overcharged", "double charged",
        "payment failed", "transaction failed", "upi"
    ],
    "Offers, Coupons & Promotions": [
        "coupon", "promo", "promotion", "offer", "discount", "deal", "reward",
        "cashback", "code not working", "coupon not applied", "promo code",
        "voucher", "referral bonus", "offer not applied"
    ],
    "Delivery Delays & Logistics": [
        "late delivery", "delivery delay", "delayed delivery", "shipping",
        "driver", "estimated time", "tracking", "not delivered",
        "delivery issue", "delivery partner", "waiting for delivery",
        "out for delivery", "delivery boy", "rider"
    ],
    "Order Accuracy & Wrong Items": [
        "wrong order", "missing item", "incorrect order", "wrong item",
        "incomplete order", "order cancelled", "order canceled",
        "unable to place order", "cannot place order", "failed order",
        "wrong product", "item missing", "wrong quantity"
    ],
    "Food Quality & Safety": [
        "food quality", "stale", "cold food", "taste", "hygiene", "expired",
        "contaminated", "food poisoning", "not fresh", "bad quality",
        "undercooked", "overcooked", "spoiled", "raw food"
    ],
    "Performance & Slowness": [
        "slow", "lag", "laggy", "sluggish", "loading", "takes forever",
        "performance", "battery drain", "overheat", "choppy",
        "takes too long", "buffering"
    ],
    "Customer Support Problems": [
        "customer support", "support not responding", "no response",
        "poor support", "rude support", "bad service", "support team",
        "helpline", "complaint not resolved", "no help", "customer care"
    ],
    "UI / UX Friction": [
        "confusing", "hard to use", "difficult", "not intuitive", "ui",
        "ux", "navigation", "cant find", "can't find", "search is useless",
        "complicated", "cluttered", "design", "onboarding", "tutorial",
        "first time", "getting started", "new user", "confusing to start"
    ],
    "Feature Requests": [
        "feature request", "please add", "can you add", "need feature",
        "would love", "wishlist", "dark mode", "widget", "support for",
        "add feature", "suggestion"
    ],
    "Pricing & Hidden Fees": [
        "expensive", "overpriced", "hidden fee", "price hike", "too costly",
        "pricing", "price increase", "surge pricing", "unfair pricing",
        "value for money", "too expensive"
    ],
    "Trust, Fraud & Policy Complaints": [
        "scam", "fraud", "fake", "privacy", "data leak", "unfair",
        "misleading", "cheating", "trust", "policy violation",
        "unauthorized", "suspicious", "fake reviews"
    ],
    "Positive Feedback / Praise": [
        "love", "great", "awesome", "excellent", "amazing", "fantastic",
        "good app", "best app", "works well", "thank you", "super",
        "fast delivery", "on time", "good service", "delicious",
        "helpful", "smooth", "wonderful", "perfect"
    ],
}

STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "have", "has", "had",
    "was", "were", "are", "is", "its", "you", "your", "our", "they", "them",
    "their", "but", "not", "very", "just", "after", "before", "when", "what",
    "why", "how", "can", "cant", "cannot", "could", "would", "should", "please",
    "app", "apps"
}

POSITIVE_HINTS = ["love", "great", "awesome", "excellent", "amazing", "fantastic",
                  "good", "best", "helpful", "smooth", "on time", "fast"]
NEGATIVE_HINTS = ["bad", "worst", "broken", "error", "issue", "problem", "fail",
                  "failed", "unusable", "frustrating", "terrible", "awful",
                  "cancelled", "canceled", "missing", "late", "delay", "scam"]
HIGH_URGENCY_HINTS = ["asap", "urgent", "immediately", "can't use", "cannot use",
                      "unusable", "every time", "all users", "lost data",
                      "money deducted", "order not delivered", "account blocked"]
LOW_URGENCY_HINTS = ["would love", "nice to have", "feature request", "please add"]

ENTITY_HINTS = [
    "otp", "dark mode", "notification", "notifications", "search", "widget",
    "gallery", "login", "payment", "subscription", "onboarding", "tutorial",
    "order", "delivery", "restaurant", "support", "refund", "coupon", "wallet",
    "upi", "driver", "tracking"
]

LOW_SIGNAL_PRAISE_TOKENS = {
    "good", "great", "nice", "best", "super", "awesome", "amazing", "excellent",
    "love", "cool", "ok", "okay", "app", "very", "so", "really"
}

MEANINGFUL_PRAISE_HINTS = {
    "feature", "support", "delivery", "refund", "payment", "search", "login",
    "notification", "interface", "ui", "ux", "speed", "performance", "dark mode",
    "onboarding", "response", "service", "order"
}


# ── Helpers ────────────────────────────────────────────────────────

def _has_llm_keys():
    return bool((os.getenv("GEMINI_API_KEY", "").strip()) or
                (os.getenv("OPENAI_API_KEY", "").strip()))


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


def _is_low_signal_praise(text):
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower())
    tokens = [t for t in re.split(r"\s+", cleaned) if t]
    if not tokens:
        return False

    informative = [t for t in tokens if t not in LOW_SIGNAL_PRAISE_TOKENS]
    if not informative and len(tokens) <= 8:
        return True

    unique_tokens = set(tokens)
    if len(unique_tokens) == 1 and list(unique_tokens)[0] in LOW_SIGNAL_PRAISE_TOKENS:
        return True

    repeated_short = len(tokens) <= 6 and all(t in LOW_SIGNAL_PRAISE_TOKENS for t in tokens)
    if repeated_short:
        return True

    if any(h in cleaned for h in MEANINGFUL_PRAISE_HINTS):
        return False

    if len(tokens) <= 5 and sum(1 for t in tokens if t in LOW_SIGNAL_PRAISE_TOKENS) >= max(2, len(tokens) - 1):
        return True

    return False


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


# ── Heuristic classification (no LLM) ─────────────────────────────

def heuristic_classify_item(original):
    text = str(original.get("text", "") or "")
    lower = text.lower()

    # Score each bucket by keyword hits
    scores = {bucket: _keyword_hits(lower, kws) for bucket, kws in BUCKET_KEYWORDS.items()}
    best_bucket = max(scores, key=scores.get) if scores else "Other"
    best_score = scores.get(best_bucket, 0)
    core_bucket = best_bucket if best_score > 0 else "Other"

    # Sentiment
    pos_hits = _keyword_hits(lower, POSITIVE_HINTS)
    neg_hits = _keyword_hits(lower, NEGATIVE_HINTS)
    raw_sent = pos_hits - neg_hits
    sentiment = 0.0 if raw_sent == 0 else max(-1.0, min(1.0, raw_sent / 4.0))

    if core_bucket == "Positive Feedback / Praise" and sentiment < 0.3:
        sentiment = 0.6
    critical_buckets = {"App Bugs & Glitches", "Crashes & App Stability",
                        "Login & Account Access", "Payments, Refunds & Billing",
                        "Order Accuracy & Wrong Items"}
    if core_bucket in critical_buckets and sentiment > -0.2:
        sentiment = -0.5

    # Low-signal praise demotion
    if core_bucket == "Positive Feedback / Praise" and _is_low_signal_praise(text):
        core_bucket = "Other"
        sentiment = 0.1

    # Urgency
    urgency = 3
    high_urgency_buckets = {"Crashes & App Stability", "Login & Account Access",
                            "Payments, Refunds & Billing", "App Bugs & Glitches",
                            "Order Accuracy & Wrong Items", "Trust, Fraud & Policy Complaints"}
    low_urgency_buckets = {"Feature Requests", "Positive Feedback / Praise"}
    if core_bucket in high_urgency_buckets:
        urgency = 4
    elif core_bucket in low_urgency_buckets:
        urgency = 2

    if _keyword_hits(lower, HIGH_URGENCY_HINTS) > 0:
        urgency = 5
    elif _keyword_hits(lower, LOW_URGENCY_HINTS) > 0 and urgency > 3:
        urgency = 3

    # Confidence
    confidence = 0.25
    if core_bucket != "Other":
        confidence = min(0.9, 0.6 + (best_score * 0.08))
    elif abs(sentiment) >= 0.5:
        confidence = 0.45

    # Derived fields
    category = [BUCKET_TO_CATEGORY.get(core_bucket, "other")]
    issue_type = BUCKET_TO_ISSUE_TYPE.get(core_bucket, "other")
    risk_tag = BUCKET_TO_DEFAULT_RISK.get(core_bucket, "none")

    return {
        "id": str(original.get("id", "unknown")),
        "core_bucket": core_bucket,
        "dynamic_bucket": None,
        "issue_type": issue_type,
        "risk_tag": risk_tag,
        "category": category,
        "sentiment": round(sentiment, 2),
        "urgency": int(max(1, min(5, urgency))),
        "summary": _build_summary(text, max_words=15),
        "entities": _extract_entities(text),
        "_confidence": round(confidence, 2)
    }


# ── LLM batch classification ──────────────────────────────────────

def chunk_list(items, size=15):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def build_prompt(batch):
    minimal_batch = [{"id": item.get("id", ""), "text": item.get("text", "")}
                     for item in batch]

    bucket_list = ", ".join(f'"{b}"' for b in CORE_BUCKETS)

    return f"""You are a product feedback analyst.

Return ONLY a valid JSON array. No explanation.

For each feedback item, return:
- id (must match input)
- core_bucket (ONE of: [{bucket_list}])
- risk_tag (ONE of: "revenue_risk", "churn_risk", "trust_risk", "ux_risk", "stability_risk", "support_risk", "retention_risk", "none")
- sentiment (float -1.0 to 1.0)
- urgency (integer 1 to 5)
- summary (max 15 words, specific and action-oriented)
- entities (array of features, screens, versions, keywords mentioned)

Rules:
- Pick the single most specific core_bucket
- Summaries should capture the core issue, not repeat the text
- risk_tag reflects business risk: revenue_risk for money issues, churn_risk for blocking issues, stability_risk for crashes, trust_risk for fraud/quality, ux_risk for usability, support_risk for service failures, retention_risk for missing features
- Be strict and concise

Input:
{json.dumps(minimal_batch, indent=2)}"""


def classify_batch(batch, max_retries=2):
    if not _has_llm_keys():
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
                "gemini quota exceeded", "quota exceeded", "resource_exhausted",
                "openai_api_key is not configured",
                "temporarily blocked due to quota", "insufficient_quota"
            ]):
                print(f"⚠️  LLM quota/config issue, switching to heuristic: {e}")
                return [heuristic_classify_item(item) for item in batch]
            if any(k in error_str for k in [
                "nodename nor servname provided", "name or service not known",
                "temporary failure in name resolution", "connection error",
                "failed to establish a new connection"
            ]):
                print(f"⚠️  LLM network unavailable, switching to heuristic: {e}")
                return [heuristic_classify_item(item) for item in batch]
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"⚠️  Classify attempt {attempt + 1}/{max_retries} failed: {e} — retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"❌ Classify attempt {attempt + 1}/{max_retries} failed: {e}")

    raise last_error


# ── Normalization and merging ──────────────────────────────────────

def normalize_item(item):
    # Validate core_bucket
    raw_bucket = item.get("core_bucket", "Other")
    if raw_bucket not in CORE_BUCKETS_SET:
        raw_bucket = "Other"
    item["core_bucket"] = raw_bucket

    # Derive issue_type and risk_tag if missing
    if not item.get("issue_type"):
        item["issue_type"] = BUCKET_TO_ISSUE_TYPE.get(raw_bucket, "other")

    raw_risk = item.get("risk_tag", "")
    if raw_risk not in RISK_TAGS:
        item["risk_tag"] = BUCKET_TO_DEFAULT_RISK.get(raw_bucket, "none")

    # Backward-compat category
    raw_cats = item.get("category", [])
    if not isinstance(raw_cats, list):
        raw_cats = [raw_cats] if isinstance(raw_cats, str) else []
    validated_cats = [c for c in raw_cats if c in ALLOWED_CATEGORIES_SET]
    if not validated_cats:
        validated_cats = [BUCKET_TO_CATEGORY.get(raw_bucket, "other")]
    item["category"] = validated_cats[:2]

    # dynamic_bucket preserved as-is (None or string)
    if "dynamic_bucket" not in item:
        item["dynamic_bucket"] = None

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
        "core_bucket": heuristic["core_bucket"],
        "dynamic_bucket": None,
        "issue_type": heuristic["issue_type"],
        "risk_tag": heuristic["risk_tag"],
        "category": heuristic["category"],
        "sentiment": heuristic["sentiment"],
        "urgency": heuristic["urgency"],
        "summary": heuristic["summary"][:80],
        "entities": heuristic["entities"]
    }


def merge_with_original(original_batch, classified_batch):
    classified_map = {}
    for item in classified_batch:
        if not isinstance(item, dict) or "id" not in item:
            continue
        classified_map[str(item["id"])] = item

    if len(classified_map) != len(classified_batch):
        print(f"⚠️  LLM returned {len(classified_batch)} items, {len(classified_map)} usable (expected {len(original_batch)})")

    merged = []

    for original in original_batch:
        item_id = str(original.get("id", "unknown"))
        classified = classified_map.get(item_id)
        heuristic = heuristic_classify_item(original)

        if classified is None:
            print(f"⚠️  Item '{item_id}' missing from LLM response, using fallback")
            classified = make_fallback_item(original)

        classified = normalize_item(classified)

        # Low-signal praise demotion
        if (
            classified.get("core_bucket") == "Positive Feedback / Praise"
            and _is_low_signal_praise(original.get("text", ""))
        ):
            classified["core_bucket"] = "Other"
            classified["category"] = ["other"]
            classified["issue_type"] = "other"
            classified["risk_tag"] = "none"
            classified["sentiment"] = min(classified.get("sentiment", 0.1), 0.2)

        # Heuristic rescue: avoid collapsing too many rows into "Other"
        if (
            classified.get("core_bucket") == "Other"
            and heuristic["core_bucket"] != "Other"
            and heuristic["_confidence"] >= 0.55
        ):
            classified["core_bucket"] = heuristic["core_bucket"]
            classified["issue_type"] = heuristic["issue_type"]
            classified["risk_tag"] = heuristic["risk_tag"]
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
            "core_bucket": classified["core_bucket"],
            "dynamic_bucket": classified.get("dynamic_bucket"),
            "issue_type": classified.get("issue_type", "other"),
            "risk_tag": classified.get("risk_tag", "none"),
            "category": classified["category"],
            "sentiment": classified["sentiment"],
            "urgency": classified["urgency"],
            "summary": classified["summary"],
            "entities": classified["entities"]
        }

        merged.append(merged_item)

    return merged


# ── Dynamic bucket assignment (heuristic, no extra LLM calls) ─────

def _extract_dynamic_phrases(items, min_count=3, max_phrases=5):
    """Find repeated actionable phrases within a core_bucket group."""
    from collections import defaultdict

    phrase_ids = defaultdict(set)

    action_keywords = {
        "payment", "refund", "order", "delivery", "support", "login",
        "otp", "crash", "cancelled", "canceled", "missing", "late", "delay",
        "restaurant", "food", "wallet", "coupon", "subscription", "billing",
        "driver", "tracking", "promo", "upi", "notification", "search",
        "update", "version", "loading", "slow", "error", "bug"
    }

    for item in items:
        item_id = str(item.get("id", ""))
        text = re.sub(r"\s+", " ", str(item.get("summary", "") + " " + item.get("text", "")).lower()).strip()
        if not text:
            continue

        tokens = re.findall(r"[a-z0-9']+", text)
        if len(tokens) < 2:
            continue

        grams = set()
        for n in (2, 3):
            for i in range(len(tokens) - n + 1):
                chunk = tokens[i:i + n]
                if all(tok in STOPWORDS for tok in chunk):
                    continue
                meaningful = [t for t in chunk if t not in STOPWORDS and len(t) >= 3]
                if len(meaningful) < 1:
                    continue
                # Boost phrases with action keywords
                if any(k in chunk for k in action_keywords):
                    phrase = " ".join(meaningful)
                    if len(phrase) >= 6:
                        grams.add(phrase)

        for g in grams:
            phrase_ids[g].add(item_id)

    candidates = []
    for phrase, ids in phrase_ids.items():
        if len(ids) >= min_count:
            candidates.append((phrase, len(ids)))

    candidates.sort(key=lambda x: -x[1])

    # Deduplicate overlapping phrases
    kept = []
    kept_tokens = []
    for phrase, count in candidates:
        phrase_set = set(phrase.split())
        duplicate = False
        for prev_set in kept_tokens:
            if phrase_set.issubset(prev_set) or prev_set.issubset(phrase_set):
                duplicate = True
                break
        if not duplicate:
            kept.append((phrase, count))
            kept_tokens.append(phrase_set)
        if len(kept) >= max_phrases:
            break

    return kept


def assign_dynamic_buckets(items):
    """Post-classification step: assign dynamic_bucket labels within each core_bucket."""
    from collections import defaultdict

    bucket_groups = defaultdict(list)
    for item in items:
        bucket_groups[item.get("core_bucket", "Other")].append(item)

    dynamic_stats = {}

    for bucket, group_items in bucket_groups.items():
        if len(group_items) < 5 or bucket in ("Other", "Positive Feedback / Praise"):
            continue

        min_count = max(3, int(len(group_items) * 0.15))
        phrases = _extract_dynamic_phrases(group_items, min_count=min_count, max_phrases=5)

        if not phrases:
            continue

        # Assign dynamic_bucket to matching items
        for phrase, count in phrases:
            label = " ".join(phrase.split()).title()
            matched = 0
            for item in group_items:
                if item.get("dynamic_bucket"):
                    continue  # already assigned
                text = (item.get("summary", "") + " " + item.get("text", "")).lower()
                if phrase in text:
                    item["dynamic_bucket"] = label
                    matched += 1

            if matched > 0:
                dynamic_stats[f"{bucket} → {label}"] = matched

    if dynamic_stats:
        print(f"📌 Dynamic buckets assigned:")
        for label, count in dynamic_stats.items():
            print(f"   {label}: {count} items")

    return items


# ── Main classify entry point ──────────────────────────────────────

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

    # Assign dynamic buckets after all items are classified
    all_results = assign_dynamic_buckets(all_results)

    # Debug output: distribution
    _print_debug_stats(all_results)

    print(f"✅ Classified {len(all_results)}/{len(items)} items")
    return all_results


def _print_debug_stats(items):
    """Print distribution stats for debugging."""
    from collections import Counter

    buckets = Counter(i.get("core_bucket", "Other") for i in items)
    risks = Counter(i.get("risk_tag", "none") for i in items)
    urgencies = Counter(i.get("urgency", 3) for i in items)
    dynamics = Counter(i.get("dynamic_bucket", "—") for i in items)

    print("\n📊 Classification Debug Stats:")
    print("  Core Bucket Distribution:")
    for bucket, count in buckets.most_common():
        print(f"    {bucket}: {count}")
    print(f"  Risk Tag Distribution: {dict(risks.most_common())}")
    print(f"  Urgency Distribution: {dict(sorted(urgencies.items()))}")
    dynamic_actual = {k: v for k, v in dynamics.most_common() if k != "—" and k is not None}
    if dynamic_actual:
        print(f"  Dynamic Buckets: {dynamic_actual}")
    print()


if __name__ == "__main__":
    test_items = [
        {"id": "1", "text": "App crashes every time I open it", "date": "2026-03-01T10:00:00", "source": "google_play"},
        {"id": "2", "text": "Login OTP never arrives", "date": "2026-03-08T10:00:00", "source": "google_play"},
        {"id": "3", "text": "Love the new design, looks clean", "date": "2026-03-10T10:00:00", "source": "reddit"},
        {"id": "4", "text": "Too slow after latest update", "date": "2026-03-15T10:00:00", "source": "google_play"},
        {"id": "5", "text": "Please add dark mode", "date": "2026-03-22T10:00:00", "source": "reddit"},
        {"id": "6", "text": "Wrong order delivered, items missing", "date": "2026-03-22T10:00:00", "source": "google_play"},
        {"id": "7", "text": "Coupon code not working at checkout", "date": "2026-03-22T10:00:00", "source": "google_play"},
    ]

    results = classify_items(test_items)

    print("\n=== FINAL OUTPUT ===\n")
    print(json.dumps(results, indent=2))
