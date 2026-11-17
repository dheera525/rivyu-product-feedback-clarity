import json
import uuid
from datetime import datetime, timezone


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Risk tags that indicate high-severity issues
HIGH_RISK_TAGS = {"revenue_risk", "stability_risk", "trust_risk"}
MEDIUM_RISK_TAGS = {"churn_risk", "support_risk", "ux_risk"}


def _safe_num(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def compute_signals(theme):
    items = theme.get("items", []) or []
    count = int(theme.get("count", 0) or 0)
    if count <= 0:
        return {
            "negative_ratio": 0.0,
            "high_urgency_count": 0,
            "source_count": 0,
            "risk_score": 0
        }

    neg_count = 0
    high_urgency_count = 0
    sources = set()
    risk_tags = {}
    for item in items:
        sentiment = _safe_num(item.get("sentiment", 0), 0)
        urgency = int(_safe_num(item.get("urgency", 3), 3))
        if sentiment <= -0.2:
            neg_count += 1
        if urgency >= 4:
            high_urgency_count += 1
        sources.add(item.get("source", "unknown"))
        rt = item.get("risk_tag", "none")
        risk_tags[rt] = risk_tags.get(rt, 0) + 1

    negative_ratio = neg_count / max(count, 1)
    avg_urgency = _safe_num(theme.get("avg_urgency", 3), 3)
    avg_sentiment = _safe_num(theme.get("avg_sentiment", 0), 0)
    trend = theme.get("trend", "stable")
    core_bucket = theme.get("core_bucket", "Other")
    risk_tag = theme.get("risk_tag", "none")

    trend_bonus = {
        "spiking": 25,
        "rising": 15,
        "new": 8,
        "stable": 0,
        "declining": -8
    }.get(trend, 0)

    # Risk-based bonus (replaces old category_bonus)
    risk_bonus = 0
    if risk_tag in HIGH_RISK_TAGS:
        risk_bonus = 14
    elif risk_tag in MEDIUM_RISK_TAGS:
        risk_bonus = 7

    # Bucket-specific boost for critical issue types
    bucket_bonus = 0
    critical_buckets = {
        "Crashes & App Stability", "Payments, Refunds & Billing",
        "Login & Account Access", "Trust, Fraud & Policy Complaints"
    }
    if core_bucket in critical_buckets:
        bucket_bonus = 10

    risk_score = (
        (avg_urgency * 12)
        + (max(0, -avg_sentiment) * 25)
        + (min(count, 20) * 2)
        + (high_urgency_count * 4)
        + (negative_ratio * 20)
        + trend_bonus
        + risk_bonus
        + bucket_bonus
    )

    return {
        "negative_ratio": round(negative_ratio, 2),
        "high_urgency_count": high_urgency_count,
        "source_count": len(sources),
        "risk_score": int(round(risk_score))
    }


def generate_alerts(themes):
    if not themes:
        return []

    alerts = []
    primary_themes = [t for t in themes if not t.get("parent_theme_id")] or themes

    for theme in primary_themes:
        trend = theme.get("trend", "stable")
        count = theme.get("count", 0)
        avg_urgency = theme.get("avg_urgency", 3)
        core_bucket = theme.get("core_bucket", "Other")
        risk_tag = theme.get("risk_tag", "none")
        signals = compute_signals(theme)
        risk_score = signals["risk_score"]
        negative_ratio = signals["negative_ratio"]
        high_urgency_count = signals["high_urgency_count"]

        alert_type = None
        severity = None

        # Suppress healthy praise themes
        if core_bucket == "Positive Feedback / Praise" and negative_ratio < 0.2 and high_urgency_count == 0:
            continue

        # Suppress noise: uncategorized feedback that isn't mostly negative,
        # and single reports outside the critical buckets.
        if core_bucket == "Other" and negative_ratio < 0.5:
            continue

        # Priority logic using risk score + critical triggers
        critical_buckets = {
            "Crashes & App Stability", "Payments, Refunds & Billing",
            "Login & Account Access", "Trust, Fraud & Policy Complaints"
        }
        if (
            (trend == "spiking" and avg_urgency >= 4 and high_urgency_count >= 3 and count >= 3)
            or (core_bucket in critical_buckets and high_urgency_count >= 4 and count >= 4)
        ):
            alert_type = "critical"
            severity = "critical"
        elif risk_score >= 75:
            alert_type = "rising"
            severity = "high"
        elif core_bucket == "Feature Requests" and count >= 6 and trend in {"rising", "spiking"}:
            alert_type = "feature_demand"
            severity = "medium"
        elif risk_score >= 52:
            alert_type = "recurring"
            severity = "medium"
        elif risk_score >= 40 and high_urgency_count >= 2:
            alert_type = "watch"
            severity = "low"

        if alert_type and count < 2 and core_bucket not in critical_buckets:
            alert_type = severity = None

        if alert_type and severity:
            theme_id = theme.get("theme_id", "unknown")
            items = theme.get("items", [])
            alert = {
                "alert_id": f"alert_{uuid.uuid4().hex[:8]}",
                "type": alert_type,
                "title": build_title(theme, alert_type),
                "description": build_description(theme, alert_type),
                "theme_id": theme_id,
                "core_bucket": core_bucket,
                "risk_tag": risk_tag,
                "severity": severity,
                "evidence_count": count,
                "risk_score": risk_score,
                "negative_ratio": negative_ratio,
                "high_urgency_count": high_urgency_count,
                "sources": list({item.get("source", "unknown") for item in items}),
                "suggested_action": build_action(theme, alert_type),
                "label": theme.get("label", core_bucket),
                "risk_label": RISK_LABELS.get(risk_tag, ""),
                "avg_urgency": theme.get("avg_urgency", 0),
                "source_count": signals["source_count"],
                "quotes": top_quotes(theme),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            alerts.append(alert)
            print(f"  🔔 Alert [{severity}] ({risk_score}) {alert['title']}")

    # Sort by severity first, then risk score and evidence
    alerts.sort(
        key=lambda a: (
            SEVERITY_ORDER.get(a["severity"], 99),
            -int(a.get("risk_score", 0)),
            -int(a.get("evidence_count", 0))
        )
    )
    alerts = alerts[:6]

    return alerts


def build_title(theme, alert_type):
    label = theme.get("label", "Unknown")
    trend_pct = theme.get("trend_pct", 0)
    risk_tag = theme.get("risk_tag", "none")

    risk_label = {
        "revenue_risk": "Revenue at risk",
        "churn_risk": "Churn risk",
        "stability_risk": "Stability concern",
        "trust_risk": "Trust issue",
        "ux_risk": "UX degradation",
        "support_risk": "Support overload",
        "retention_risk": "Retention signal",
    }.get(risk_tag, "")

    if alert_type == "critical":
        trend_note = f" (+{trend_pct:g}%)" if isinstance(trend_pct, (int, float)) and trend_pct > 0 else ""
        return f"{label} — {risk_label or 'critical spike'}{trend_note}"
    elif alert_type == "rising":
        return f"{label} — {risk_label or 'rising complaints'}"
    elif alert_type == "feature_demand":
        return f"Growing demand: {label}"
    elif alert_type == "recurring":
        return f"{label} — recurring {(risk_label or 'issue').lower().replace('ux ', 'UX ')}"
    elif alert_type == "watch":
        return f"Watch: {label}"
    else:
        return f"Alert: {label}"


SOURCE_NAMES = {
    "google_play": "Google Play",
    "reddit": "Reddit",
    "csv": "CSV",
    "gmail": "Gmail",
    "x": "X",
    "youtube_comments": "YouTube",
}

RISK_LABELS = {
    "revenue_risk": "revenue risk",
    "churn_risk": "churn risk",
    "stability_risk": "stability risk",
    "trust_risk": "trust risk",
    "ux_risk": "UX risk",
    "support_risk": "support risk",
    "retention_risk": "retention risk",
}


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def build_description(theme, alert_type):
    """One or two plain-language sentences summarizing the evidence."""
    count = int(theme.get("count", 0) or 0)
    items = theme.get("items", []) or []
    signals = compute_signals(theme)
    sources = sorted({SOURCE_NAMES.get(i.get("source"), str(i.get("source") or "unknown")) for i in items})
    neg_pct = int(round(signals["negative_ratio"] * 100))
    high = signals["high_urgency_count"]

    who = f"{count} piece{'' if count == 1 else 's'} of feedback"
    desc = f"{who} from {_join(sources)}." if sources else f"{who}."
    tone = "All negative" if neg_pct == 100 else "None negative" if neg_pct == 0 else f"{neg_pct}% negative"
    desc += f" {tone}"
    desc += f", {high} marked high urgency." if high else "."

    trend = theme.get("trend", "stable")
    pct = theme.get("trend_pct", 0) or 0
    if trend in {"rising", "spiking"} and pct > 0:
        desc += f" Up {pct:g}% vs. earlier weeks."
    elif trend == "new":
        desc += " Appeared only in the latest week."

    mentions = [m for m in (theme.get("top_entities") or [])[:3] if m]
    if mentions:
        desc += f" Common words: {', '.join(mentions)}."
    return desc


def build_action(theme, alert_type):
    risk_tag = theme.get("risk_tag", "none")

    risk_actions = {
        "revenue_risk": "Audit the payment and billing flow, refund affected customers, and loop in finance.",
        "stability_risk": "Pull crash logs for the affected versions and ship a hotfix.",
        "trust_risk": "Audit the affected process and prepare a customer communication.",
        "churn_risk": "Find what's blocking users and fast-track the fix.",
        "support_risk": "Review the support queue and add capacity or macros.",
        "ux_risk": "Run a UX review of the affected flow with design.",
        "retention_risk": "Validate demand and decide whether it belongs on the roadmap.",
    }

    if alert_type == "critical":
        return "Treat as a release blocker this sprint. " + risk_actions.get(
            risk_tag, "Assign an owner and investigate the root cause today.")
    if alert_type == "rising":
        return risk_actions.get(risk_tag, "Assign an owner and find the root cause before it grows.")
    if alert_type == "feature_demand":
        return "Validate demand with users and size it for the roadmap."
    if alert_type == "recurring":
        return risk_actions.get(risk_tag, "Review the repeated complaints and plan a long-term fix.")
    if alert_type == "watch":
        return "Track for 24–48 hours and assign an owner if volume rises."
    return "Monitor this theme."


def top_quotes(theme, limit=2, max_len=180):
    """The most urgent, most negative customer quotes for a theme."""
    items = sorted(
        theme.get("items", []) or [],
        key=lambda i: (-int(_safe_num(i.get("urgency", 3), 3)), _safe_num(i.get("sentiment", 0), 0)),
    )
    quotes = []
    for item in items:
        text = " ".join(str(item.get("text") or "").split())
        if len(text) < 12:
            continue
        if len(text) > max_len:
            text = text[: max_len - 1].rstrip() + "…"
        quotes.append({"text": text, "source": item.get("source", ""), "date": item.get("date", "")})
        if len(quotes) >= limit:
            break
    return quotes


if __name__ == "__main__":
    from trend import detect_trends
    from grouping import group_into_themes
    from classify import classify_items

    test_items = [
        {"id": "1", "text": "App crashes every time I open it", "date": "2026-03-01T10:00:00", "source": "google_play"},
        {"id": "2", "text": "App crashes after update", "date": "2026-03-08T10:00:00", "source": "google_play"},
        {"id": "3", "text": "App crashes again after update", "date": "2026-03-15T10:00:00", "source": "reddit"},
        {"id": "4", "text": "Login OTP not working", "date": "2026-03-15T10:00:00", "source": "google_play"},
        {"id": "5", "text": "Please add dark mode", "date": "2026-03-22T10:00:00", "source": "reddit"},
        {"id": "6", "text": "App crashes every launch", "date": "2026-03-22T10:00:00", "source": "google_play"},
        {"id": "7", "text": "App crashes instantly", "date": "2026-03-22T10:00:00", "source": "reddit"}
    ]

    classified = classify_items(test_items)
    themes = group_into_themes(classified)
    themes = detect_trends(themes)
    alerts = generate_alerts(themes)

    print("\n=== ALERTS ===\n")
    print(json.dumps(alerts, indent=2))
