import os
import json
from dotenv import load_dotenv
from llm_client import call_llm

load_dotenv()


def ask_rivyu(question, themes, alerts, processed_items):
    if not question or not question.strip():
        return "Please provide a question."

    top_themes = sorted(themes, key=lambda x: x.get("count", 0), reverse=True)[:10]
    urgent_items = sorted(processed_items, key=lambda x: x.get("urgency", 0), reverse=True)[:15]

    context = {
        "total_feedback_items": len(processed_items),
        "alerts": [
            {
                "title": a.get("title", ""),
                "severity": a.get("severity", ""),
                "core_bucket": a.get("core_bucket", ""),
                "risk_tag": a.get("risk_tag", ""),
                "risk_score": a.get("risk_score", 0),
                "evidence_count": a.get("evidence_count", 0),
                "suggested_action": a.get("suggested_action", "")
            }
            for a in alerts[:8]
        ],
        "top_themes": [
            {
                "label": t.get("label", ""),
                "core_bucket": t.get("core_bucket", ""),
                "risk_tag": t.get("risk_tag", "none"),
                "count": t.get("count", 0),
                "avg_sentiment": t.get("avg_sentiment", 0),
                "avg_urgency": t.get("avg_urgency", 0),
                "trend": t.get("trend", "stable"),
                "trend_pct": t.get("trend_pct", 0),
                "top_entities": t.get("top_entities", [])[:5]
            }
            for t in top_themes
        ],
        "urgent_samples": [
            {
                "summary": item.get("summary", ""),
                "core_bucket": item.get("core_bucket", "Other"),
                "risk_tag": item.get("risk_tag", "none"),
                "urgency": item.get("urgency", 3),
                "sentiment": item.get("sentiment", 0),
            }
            for item in urgent_items
        ]
    }

    prompt = f"""You are Rivyu, an AI product analyst assistant.

Answer the PM's question based ONLY on the feedback data provided below.

FORMAT YOUR RESPONSE WITH CLEAR SECTIONS:
- Use **bold** for key terms
- Use bullet points (- ) for lists
- Structure your answer with these sections when relevant:
  ## Summary
  ## Key Risks
  ## Recommended Actions

Rules:
- Be specific and data-driven
- Reference actual theme names, counts, and risk tags
- Recommend concrete actions
- Do NOT hallucinate or make up data
- Keep answer under 300 words
- Make the answer scannable — avoid long paragraphs

CONTEXT:
{json.dumps(context, indent=2)}

USER QUESTION:
{question}"""

    def deterministic_answer():
        return build_fallback_answer(question, themes, alerts, processed_items)

    try:
        answer = call_llm(prompt)
        if not answer or not answer.strip():
            return "I received an empty response. Please try rephrasing your question."
        return answer.strip()
    except Exception as e:
        print(f"❌ ask_rivyu failed: {e}")
        # Keep demo UX stable: always provide a useful fallback.
        return deterministic_answer()


RISK_LABELS = {
    "revenue_risk": "revenue risk",
    "churn_risk": "churn risk",
    "stability_risk": "stability risk",
    "trust_risk": "trust risk",
    "ux_risk": "UX risk",
    "support_risk": "support risk",
    "retention_risk": "retention risk",
}

REVENUE_BUCKETS = {"Payments, Refunds & Billing", "Trust, Fraud & Policy Complaints"}


def _risk_note(tag):
    label = RISK_LABELS.get(tag)
    return f" ({label})" if label else ""


def _theme_line(t, detail="urgency"):
    n = t.get("count", 0)
    base = f"- **{t.get('label', 'Theme')}**: {n} mention{'' if n == 1 else 's'}"
    if detail == "trend":
        base += f", trend {t.get('trend', 'stable')} ({t.get('trend_pct', 0):+g}%)"
    elif detail == "sentiment":
        base += f", avg sentiment {t.get('avg_sentiment', 0):+.2f}"
    else:
        base += f", urgency {t.get('avg_urgency', 0)}/5, trend {t.get('trend', 'stable')}"
    return base + _risk_note(t.get("risk_tag"))


def _quote(item, max_len=140):
    text = (item.get("text") or item.get("summary") or "").strip().replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return f'- "{text}"'


def build_fallback_answer(question, themes, alerts, processed_items):
    """Answer from the analysis results alone, without an LLM.

    Used when no LLM key is configured or every provider fails. Picks an
    answer shape from keywords in the question so common questions still get
    a specific, data-backed reply.
    """
    q = (question or "").lower()
    primary = [t for t in themes if not t.get("parent_theme_id")] or list(themes)
    by_count = sorted(primary, key=lambda t: t.get("count", 0), reverse=True)
    critical = [a for a in alerts if a.get("severity") in {"critical", "high"}]
    urgent = [i for i in processed_items if int(i.get("urgency", 3) or 3) >= 4]
    note = "\n\n*Generated from the analysis results without an LLM.*"

    def has(*words):
        return any(w in q for w in words)

    if has("revenue", "billing", "payment", "refund", "money", "charge", "pricing", "subscription"):
        money_themes = [t for t in primary if t.get("risk_tag") == "revenue_risk" or t.get("core_bucket") in REVENUE_BUCKETS]
        money_alerts = [a for a in alerts if a.get("risk_tag") == "revenue_risk" or a.get("core_bucket") in REVENUE_BUCKETS]
        if not money_themes:
            return "## Summary\nNo billing, payment or other revenue-risk feedback was found in this dataset." + note
        samples = [i for i in processed_items if i.get("risk_tag") == "revenue_risk"][:3]
        out = "## Summary\nRevenue-related feedback found in this dataset:\n\n" + "\n".join(_theme_line(t) for t in money_themes)
        if money_alerts:
            out += "\n\n## Key Risks\n" + "\n".join(f"- {a.get('title')} (severity {a.get('severity')}, risk score {a.get('risk_score', 0)})" for a in money_alerts)
        if samples:
            out += "\n\n## What customers say\n" + "\n".join(_quote(i) for i in samples)
        action = money_alerts[0].get("suggested_action") if money_alerts else "Review the billing flow and respond to affected customers."
        return out + f"\n\n## Recommended Actions\n- {action}" + note

    if has("prais", "love", "like", "positive", "happy", "good", "working well"):
        positive = [i for i in processed_items if float(i.get("sentiment", 0) or 0) >= 0.3]
        pos_themes = sorted([t for t in primary if float(t.get("avg_sentiment", 0) or 0) >= 0.25], key=lambda t: t.get("count", 0), reverse=True)
        if not positive:
            return "## Summary\nThere's very little positive feedback in this dataset; it's dominated by complaints." + note
        out = f"## Summary\n{len(positive)} of {len(processed_items)} items are positive."
        if pos_themes:
            out += "\n\n" + "\n".join(_theme_line(t, "sentiment") for t in pos_themes[:3])
        out += "\n\n## What customers say\n" + "\n".join(_quote(i) for i in positive[:3])
        return out + note

    if has("new", "recent", "last", "week", "today", "trend", "rising", "emerging", "changing"):
        rising = [t for t in primary if t.get("trend") in {"new", "rising", "spiking"}]
        focus = rising[:3] or by_count[:3]
        heading = "Rising or newly appearing themes:" if rising else "Nothing is rising sharply; the largest themes are steady:"
        return (
            f"## Summary\n{heading}\n\n" + "\n".join(_theme_line(t, "trend") for t in focus)
            + "\n\n## Recommended Actions\n"
            + f"- Review the {len(critical)} high/critical alerts first\n"
            + f"- Triage the {len(urgent)} high-urgency items"
            + note
        )

    if has("priorit", "sprint", "focus", "first", "fix", "roadmap", "should we"):
        if not alerts:
            return "## Summary\nNo theme crossed the alert threshold. Start with the largest themes:\n\n" + "\n".join(_theme_line(t) for t in by_count[:3]) + note
        lines = [f"{n}. **{a.get('title')}**: {a.get('suggested_action', '')}" for n, a in enumerate(alerts[:3], start=1)]
        return (
            "## Summary\nSuggested order for this sprint, ranked by severity and risk score:\n\n" + "\n".join(lines)
            + f"\n\n## Why\n- {len(critical)} alerts are high or critical\n- {len(urgent)} items are rated urgency 4 or 5"
            + note
        )

    # Default: top issues.
    lines = [_theme_line(t) for t in by_count[:3]]
    alert_lines = [f"- {a.get('title', 'Alert')}: risk score {a.get('risk_score', 0)}" for a in critical[:3]]
    return (
        "## Summary\nTop issues in this dataset:\n\n"
        + ("\n".join(lines) if lines else "- No clear issue clusters detected.")
        + ("\n\n## Key Risks\n" + "\n".join(alert_lines) if alert_lines else "")
        + "\n\n## Recommended Actions\n"
        + f"- Address the themes behind {len(critical)} high/critical alerts first\n"
        + f"- Review the top {min(10, len(urgent))} urgent items and assign owners"
        + note
    )


if __name__ == "__main__":
    from classify import classify_items
    from grouping import group_into_themes
    from trend import detect_trends
    from alerts import generate_alerts

    test_items = [
        {"id": "1", "text": "App crashes every time I open it", "date": "2026-03-01T10:00:00", "source": "google_play"},
        {"id": "2", "text": "App crashes after update", "date": "2026-03-08T10:00:00", "source": "google_play"},
        {"id": "3", "text": "App crashes again after update", "date": "2026-03-15T10:00:00", "source": "reddit"},
        {"id": "4", "text": "Login OTP not working", "date": "2026-03-15T10:00:00", "source": "google_play"},
        {"id": "5", "text": "Please add dark mode", "date": "2026-03-22T10:00:00", "source": "reddit"},
        {"id": "6", "text": "App crashes every launch", "date": "2026-03-22T10:00:00", "source": "google_play"},
        {"id": "7", "text": "App crashes instantly", "date": "2026-03-22T10:00:00", "source": "reddit"}
    ]

    processed = classify_items(test_items)
    themes = group_into_themes(processed)
    themes = detect_trends(themes)
    alerts = generate_alerts(themes)

    question = "What should we prioritize this sprint?"
    answer = ask_rivyu(question, themes, alerts, processed)

    print("\n=== ASK RIVYU ANSWER ===\n")
    print(answer)
