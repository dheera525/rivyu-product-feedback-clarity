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
        return f"🚨 {label} — {risk_label or 'critical spike'} (+{trend_pct}%)"
    elif alert_type == "rising":
        return f"⚠️ {label} — {risk_label or 'rising complaints'}"
    elif alert_type == "feature_demand":
        return f"📢 Growing demand: {label}"
    elif alert_type == "recurring":
        return f"🔁 {label} — recurring {risk_label or 'issue'}"
    elif alert_type == "watch":
        return f"👁️ Watch: {label}"
    else:
        return f"Alert: {label}"


def build_description(theme, alert_type):
    label = theme.get("label", "Unknown")
    count = theme.get("count", 0)
    trend = theme.get("trend", "stable")
    avg_urgency = theme.get("avg_urgency", 0)
    core_bucket = theme.get("core_bucket", "Other")
    risk_tag = theme.get("risk_tag", "none")
    top_entities = theme.get("top_entities", [])

    signals = compute_signals(theme)
    desc = (
        f"{count} reports in \"{core_bucket}\" bucket. "
        f"Trend: {trend}, avg urgency {avg_urgency:.1f}/5, "
        f"{signals['high_urgency_count']} high-urgency, "
        f"{int(signals['negative_ratio'] * 100)}% negative."
    )
    if top_entities:
        desc += f" Key mentions: {', '.join(top_entities[:4])}."
    return desc


def build_action(theme, alert_type):
    risk_tag = theme.get("risk_tag", "none")

    risk_actions = {
        "revenue_risk": "Review payment/billing flows and escalate to finance team.",
        "stability_risk": "Investigate crash logs and prioritize hotfix in current sprint.",
        "trust_risk": "Audit affected processes and prepare customer communication.",
        "churn_risk": "Identify blocking issues and fast-track resolution.",
        "support_risk": "Review support queue and consider scaling capacity.",
        "ux_risk": "Conduct UX review of affected flows with design team.",
        "retention_risk": "Evaluate feature demand and consider roadmap inclusion.",
    }

    if alert_type == "critical":
        base = "Investigate immediately and prioritize fix in current sprint."
        if risk_tag in risk_actions:
            base += f" {risk_actions[risk_tag]}"
        return base
    elif alert_type == "rising":
        return risk_actions.get(risk_tag, "Monitor closely and assign owner for root cause analysis.")
    elif alert_type == "feature_demand":
        return "Consider adding to roadmap or validating demand with PM team."
    elif alert_type == "recurring":
        return risk_actions.get(risk_tag, "Review repeated complaints and evaluate long-term fix.")
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
