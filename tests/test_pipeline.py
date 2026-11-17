"""Theme grouping, trend detection and alert generation."""

from alerts import SEVERITY_ORDER, generate_alerts
from grouping import group_into_themes
from run_pipeline import run_pipeline
from trend import detect_trends, get_week_key

from conftest import make_item, make_processed


# --- Grouping -------------------------------------------------------------

def test_items_grouped_by_core_bucket():
    items = (
        [make_processed(f"c{i}", "Crashes & App Stability") for i in range(4)]
        + [make_processed(f"l{i}", "Login & Account Access", risk_tag="churn_risk") for i in range(2)]
    )

    themes = group_into_themes(items)
    primary = {t["core_bucket"]: t for t in themes if not t.get("parent_theme_id")}

    assert primary["Crashes & App Stability"]["count"] == 4
    assert primary["Login & Account Access"]["count"] == 2
    assert all(t["theme_id"] for t in themes)
    assert len({t["theme_id"] for t in themes}) == len(themes)


def test_theme_averages_computed():
    items = [
        make_processed("a", "Performance & Slowness", sentiment=-1.0, urgency=5),
        make_processed("b", "Performance & Slowness", sentiment=0.0, urgency=3),
    ]

    [theme] = [t for t in group_into_themes(items) if not t.get("parent_theme_id")]

    assert theme["avg_sentiment"] == -0.5
    assert theme["avg_urgency"] == 4.0


def test_grouping_empty():
    assert group_into_themes([]) == []


# --- Trends ---------------------------------------------------------------

def _theme_with_dates(dates):
    return {"theme_id": "t", "label": "T", "items": [{"date": d} for d in dates]}


def test_week_key_parsing():
    assert get_week_key("2026-03-10T10:00:00Z") == "2026-W11"
    assert get_week_key("not a date") is None
    assert get_week_key("") is None


def test_spiking_trend_detected():
    # 1 per week for three weeks, then 6 in the latest week.
    dates = ["2026-03-02T10:00:00Z", "2026-03-09T10:00:00Z", "2026-03-16T10:00:00Z"]
    dates += ["2026-03-23T10:00:00Z"] * 6

    [theme] = detect_trends([_theme_with_dates(dates)])

    assert theme["trend"] == "spiking"
    assert theme["trend_pct"] == 500.0


def test_declining_trend_detected():
    dates = ["2026-03-02T10:00:00Z"] * 5 + ["2026-03-09T10:00:00Z"]

    [theme] = detect_trends([_theme_with_dates(dates)])

    assert theme["trend"] == "declining"


def test_single_week_is_new():
    [theme] = detect_trends([_theme_with_dates(["2026-03-02T10:00:00Z"])])
    assert theme["trend"] == "new"


def test_no_valid_dates_is_stable():
    [theme] = detect_trends([_theme_with_dates(["", "garbage"])])
    assert theme["trend"] == "stable"
    assert theme["time_buckets"] == {}


# --- Alerts ---------------------------------------------------------------

def _themes_for_alerts():
    crash = [make_processed(f"c{i}", "Crashes & App Stability", sentiment=-0.9, urgency=5) for i in range(6)]
    billing = [make_processed(f"b{i}", "Payments, Refunds & Billing", sentiment=-0.7, urgency=4,
                              risk_tag="revenue_risk") for i in range(2)]
    ux = [make_processed(f"u{i}", "UI / UX Friction", sentiment=-0.3, urgency=3, risk_tag="ux_risk") for i in range(2)]
    praise = [make_processed(f"p{i}", "Positive Feedback / Praise", sentiment=0.9, urgency=1,
                             risk_tag="none") for i in range(5)]
    themes = group_into_themes(crash + billing + ux + praise)
    return detect_trends(themes)


def test_alerts_sorted_by_severity_then_risk():
    alerts = generate_alerts(_themes_for_alerts())

    assert alerts, "expected at least one alert"
    keys = [(SEVERITY_ORDER[a["severity"]], -a["risk_score"]) for a in alerts]
    assert keys == sorted(keys)
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["core_bucket"] == "Crashes & App Stability"


def test_healthy_praise_never_alerts():
    alerts = generate_alerts(_themes_for_alerts())
    assert all(a["core_bucket"] != "Positive Feedback / Praise" for a in alerts)


def test_alert_titles_have_no_malformed_percentages():
    for alert in generate_alerts(_themes_for_alerts()):
        assert "+-" not in alert["title"]
        assert alert["suggested_action"]


def test_alerts_capped_at_six():
    buckets = [
        "Crashes & App Stability", "Payments, Refunds & Billing", "Login & Account Access",
        "Trust, Fraud & Policy Complaints", "App Bugs & Glitches", "Performance & Slowness",
        "Customer Support Issues", "Delivery / Service Failure",
    ]
    items = [make_processed(f"{b}{i}", b, sentiment=-0.9, urgency=5) for b in buckets for i in range(5)]
    alerts = generate_alerts(detect_trends(group_into_themes(items)))
    assert len(alerts) <= 6


def test_no_alerts_for_no_themes():
    assert generate_alerts([]) == []


# --- End to end -----------------------------------------------------------

def test_run_pipeline_end_to_end_offline():
    items = [
        make_item("1", "App crashes on launch", "2026-03-02T10:00:00Z"),
        make_item("2", "App crashes after update", "2026-03-09T10:00:00Z"),
        make_item("3", "Crash every time I open the app", "2026-03-16T10:00:00Z"),
        make_item("4", "Please add dark mode", "2026-03-16T10:00:00Z", source="reddit"),
    ]

    result = run_pipeline(items)

    assert result["stats"]["total_items"] == 4
    assert set(result["stats"]["sources"]) == {"google_play", "reddit"}
    assert result["themes"]
    assert len(result["processed_items"]) == 4


def test_run_pipeline_empty():
    result = run_pipeline([])
    assert result["stats"]["total_items"] == 0
    assert result["alerts"] == []
