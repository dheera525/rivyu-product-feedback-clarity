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
        "alerts": alerts[:10],
        "top_themes": [
            {
                "theme_id": t.get("theme_id", ""),
                "label": t.get("label", ""),
                "category": t.get("category", "other"),
                "count": t.get("count", 0),
                "avg_sentiment": t.get("avg_sentiment", 0),
                "avg_urgency": t.get("avg_urgency", 0),
                "trend": t.get("trend", "stable"),
                "trend_pct": t.get("trend_pct", 0)
            }
            for t in top_themes
        ],
        "urgent_samples": [
            {
                "summary": item.get("summary", ""),
                "category": item.get("category", ["other"]),
                "urgency": item.get("urgency", 3),
                "sentiment": item.get("sentiment", 0),
                "text": item.get("text", "")
            }
            for item in urgent_items
        ]
    }

    prompt = f"""
You are Rivyu, an AI product analyst.

Answer the PM's question based ONLY on the feedback data provided below.

Rules:
- Be specific
- Use evidence from themes/alerts
- Recommend actions
- Do NOT hallucinate
- Keep answer under 250 words

CONTEXT:
{json.dumps(context, indent=2)}

USER QUESTION:
{question}
"""

    def deterministic_answer():
        q = question.lower()
        top = top_themes[:5]
        rising = [t for t in top_themes if t.get("trend") in {"new", "rising", "spiking"}]
        critical = [a for a in alerts if a.get("severity") in {"critical", "high"}]
        urgent = [i for i in processed_items if int(i.get("urgency", 3) or 3) >= 4]

        if "new" in q or "recent" in q or "last" in q:
            focus = rising[:3] if rising else top[:3]
            lines = [f"- {t.get('label','Theme')}: {t.get('count',0)} mentions, trend {t.get('trend','stable')} ({t.get('trend_pct',0)}%)" for t in focus]
            return (
                "Newest issue signals from current run:\n"
                + ("\n".join(lines) if lines else "- No clear new/rising issue signal yet.")
                + f"\n\nPriority actions:\n- Review {len(critical)} high/critical alerts first.\n- Triage {len(urgent)} high-urgency items for immediate fixes."
            )

        lines = [f"- {t.get('label','Theme')}: {t.get('count',0)} mentions, urgency {t.get('avg_urgency',0)}/5, trend {t.get('trend','stable')}" for t in top[:3]]
        return (
            "Current top issues from this dataset:\n"
            + ("\n".join(lines) if lines else "- No strong issue clusters detected.")
            + f"\n\nWhat to do next:\n- Fix themes behind {len(critical)} high/critical alerts first.\n- Review top 10 urgent comments and assign owners."
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
            note = "\n\nNote: OpenAI quota is exhausted for this key. Add billing/credits in your OpenAI account or use another key."
        elif "quota" in error_str or "resource_exhausted" in error_str:
            note = "\n\nNote: Gemini quota is currently exhausted. Add OPENAI_API_KEY in `.env` (with active credits) for automatic fallback."
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
