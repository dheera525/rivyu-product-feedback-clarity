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
        q = question.lower()
        top = top_themes[:5]
        rising = [t for t in top_themes if t.get("trend") in {"new", "rising", "spiking"}]
        critical = [a for a in alerts if a.get("severity") in {"critical", "high"}]
        urgent = [i for i in processed_items if int(i.get("urgency", 3) or 3) >= 4]

        if "new" in q or "recent" in q or "last" in q:
            focus = rising[:3] if rising else top[:3]
            lines = []
            for t in focus:
                risk = t.get("risk_tag", "none")
                risk_label = f" [{risk}]" if risk != "none" else ""
                lines.append(f"- **{t.get('label', 'Theme')}**: {t.get('count', 0)} mentions, "
                             f"trend {t.get('trend', 'stable')} ({t.get('trend_pct', 0)}%){risk_label}")
            return (
                "## Summary\nNewest issue signals from current analysis:\n\n"
                + ("\n".join(lines) if lines else "- No clear new/rising signal detected.\n")
                + f"\n\n## Recommended Actions\n"
                + f"- Review {len(critical)} high/critical alerts first\n"
                + f"- Triage {len(urgent)} high-urgency items for immediate fixes"
            )

        lines = []
        for t in top[:3]:
            risk = t.get("risk_tag", "none")
            risk_label = f" [{risk}]" if risk != "none" else ""
            lines.append(f"- **{t.get('label', 'Theme')}**: {t.get('count', 0)} mentions, "
                         f"urgency {t.get('avg_urgency', 0)}/5, "
                         f"trend {t.get('trend', 'stable')}{risk_label}")

        alert_lines = []
        for a in critical[:3]:
            alert_lines.append(f"- {a.get('title', 'Alert')}: risk score {a.get('risk_score', 0)}")

        return (
            "## Summary\nTop issues from current dataset:\n\n"
            + ("\n".join(lines) if lines else "- No strong issue clusters detected.\n")
            + (f"\n\n## Key Risks\n" + "\n".join(alert_lines) if alert_lines else "")
            + f"\n\n## Recommended Actions\n"
            + f"- Address themes behind {len(critical)} high/critical alerts first\n"
            + f"- Review top {min(10, len(urgent))} urgent comments and assign owners"
        )

    try:
        answer = call_llm(prompt)
        if not answer or not answer.strip():
            return "I received an empty response. Please try rephrasing your question."
        return answer.strip()
    except Exception as e:
        print(f"❌ ask_rivyu failed: {e}")
        note = ""
        error_str = str(e).lower()
        if "insufficient_quota" in error_str and "openai" in error_str:
            note = "\n\n*Note: OpenAI quota exhausted. Add billing/credits or use another key.*"
        elif "quota" in error_str or "resource_exhausted" in error_str:
            note = "\n\n*Note: Gemini quota exhausted. Add OPENAI_API_KEY for fallback.*"
        return deterministic_answer() + note


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
