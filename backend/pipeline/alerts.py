import json
import uuid
from datetime import datetime, timezone


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


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
    for item in items:
        sentiment = _safe_num(item.get("sentiment", 0), 0)
        urgency = int(_safe_num(item.get("urgency", 3), 3))
        if sentiment <= -0.2:
            neg_count += 1
        if urgency >= 4:
            high_urgency_count += 1
        sources.add(item.get("source", "unknown"))

    negative_ratio = neg_count / max(count, 1)
    avg_urgency = _safe_num(theme.get("avg_urgency", 3), 3)
    avg_sentiment = _safe_num(theme.get("avg_sentiment", 0), 0)
    trend = theme.get("trend", "stable")
    category = theme.get("category", "other")

    trend_bonus = {
        "spiking": 25,
        "rising": 15,
        "new": 8,
        "stable": 0,
        "declining": -8
    }.get(trend, 0)

    category_bonus = 0
    if category in {"crash", "billing", "login"}:
        category_bonus = 12
    elif category == "performance":
        category_bonus = 6

    risk_score = (
        (avg_urgency * 12)
        + (max(0, -avg_sentiment) * 25)
        + (min(count, 20) * 2)
        + (high_urgency_count * 4)
        + (negative_ratio * 20)
        + trend_bonus
        + category_bonus
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

    for theme in themes:
        trend = theme.get("trend", "stable")
        count = theme.get("count", 0)
        avg_urgency = theme.get("avg_urgency", 3)
        avg_sentiment = theme.get("avg_sentiment", 0)
        category = theme.get("category", "other")
        signals = compute_signals(theme)
        risk_score = signals["risk_score"]
        negative_ratio = signals["negative_ratio"]
        high_urgency_count = signals["high_urgency_count"]

        alert_type = None
        severity = None

        # Suppress healthy praise themes from alerting.
        if category == "praise" and negative_ratio < 0.2 and high_urgency_count == 0:
            continue

        # Priority logic using risk score + critical triggers.
        if (
            (trend == "spiking" and avg_urgency >= 4 and high_urgency_count >= 3 and count >= 3)
            or (category in {"crash", "billing", "login"} and high_urgency_count >= 4 and count >= 4)
        ):
            alert_type = "critical"
            severity = "critical"
        elif risk_score >= 75:
            alert_type = "rising"
            severity = "high"
        elif category == "feature_request" and count >= 6 and trend in {"rising", "spiking"}:
            alert_type = "feature_demand"
            severity = "medium"
        elif risk_score >= 52:
            alert_type = "recurring"
            severity = "medium"
        elif risk_score >= 40 and high_urgency_count >= 2:
            alert_type = "watch"
            severity = "low"

        if alert_type and severity:
            theme_id = theme.get("theme_id", "unknown")
            items = theme.get("items", [])
            alert = {
                "alert_id": f"alert_{uuid.uuid4().hex[:8]}",
                "type": alert_type,
                "title": build_title(theme, alert_type),
                "description": build_description(theme, alert_type),
                "theme_id": theme_id,
                "severity": severity,
                "evidence_count": count,
                "risk_score": risk_score,
                "negative_ratio": negative_ratio,
                "high_urgency_count": high_urgency_count,
                "sources": list({item.get("source", "unknown") for item in items}),
                "suggested_action": build_action(theme, alert_type),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            alerts.append(alert)
            print(f"  🔔 Alert [{severity}] ({risk_score}) {alert['title']}")

    # Sort by severity first, then risk score and evidence.
    alerts.sort(
        key=lambda a: (
            SEVERITY_ORDER.get(a["severity"], 99),
            -int(a.get("risk_score", 0)),
            -int(a.get("evidence_count", 0))
        )
    )
    alerts = alerts[:5]

    return alerts


def build_title(theme, alert_type):
    label = theme.get("label", "Unknown")
    trend_pct = theme.get("trend_pct", 0)

    if alert_type == "critical":
        return f"{label} complaints spiked {trend_pct}%"
    elif alert_type == "rising":
        return f"{label} complaints are rising"
    elif alert_type == "feature_demand":
        return f"Demand growing for {label}"
    elif alert_type == "recurring":
        return f"{label} remains a recurring issue"
    elif alert_type == "watch":
        return f"Watch {label} closely"
    else:
        return f"Alert for {label}"


def build_description(theme, alert_type):
    label = theme.get("label", "Unknown")
    count = theme.get("count", 0)
    trend = theme.get("trend", "stable")
    avg_urgency = theme.get("avg_urgency", 0)
    top_entities = theme.get("top_entities", [])

    signals = compute_signals(theme)
    desc = (
        f"{label}: {count} items, trend {trend}, avg urgency {avg_urgency}/5, "
        f"high-urgency {signals['high_urgency_count']}, negative ratio {signals['negative_ratio']}."
    )
    if top_entities:
        desc += f" Top mentions: {', '.join(top_entities[:4])}."
    return desc


def build_action(theme, alert_type):
    if alert_type == "critical":
        return "Investigate immediately and prioritize fix in current sprint."
    elif alert_type == "rising":
        return "Monitor closely and assign owner for root cause analysis."
    elif alert_type == "feature_demand":
        return "Consider adding to roadmap or validating demand with PM team."
    elif alert_type == "recurring":
        return "Review repeated complaints and evaluate long-term fix."
    elif alert_type == "watch":
        return "Track this issue for 24–48h and assign an owner if volume rises."
    else:
        return "Monitor this theme."


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
