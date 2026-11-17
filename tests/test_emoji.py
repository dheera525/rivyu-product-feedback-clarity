import pytest

import classify
from emoji_signals import describe_emojis, emoji_signals


@pytest.mark.parametrize("text, tone", [
    ("👍", "positive"),
    ("👍🏽", "positive"),          # skin tone modifier
    ("❤️❤️", "positive"),          # variation selector
    ("🔥🔥🔥", "positive"),
    ("👎", "negative"),
    ("😡😡", "negative"),
    ("💩", "negative"),
])
def test_emoji_sentiment(text, tone):
    sig = emoji_signals(text)
    assert sig["emoji_only"]
    assert (sig["sentiment"] > 0) if tone == "positive" else (sig["sentiment"] < 0)


def test_mixed_text_is_not_emoji_only():
    sig = emoji_signals("Love it 😍")
    assert not sig["emoji_only"]
    assert sig["names"] == ["heart eyes"]


def test_plain_text_has_no_emoji_signal():
    sig = emoji_signals("The app is fine")
    assert sig["count"] == 0
    assert not sig["has_emoji"]
    assert sig["sentiment"] == 0.0


def test_describe_emojis():
    assert describe_emojis("👍👍") == "Emoji reaction (positive): 👍 thumbs up"
    assert "negative" in describe_emojis("😡")


def _classify(text):
    return classify.heuristic_classify_item({"id": "1", "text": text})


def test_thumbs_up_review_is_positive_praise():
    r = _classify("👍")
    assert r["core_bucket"] == "Positive Feedback / Praise"
    assert r["sentiment"] > 0.5
    assert r["summary"].startswith("Emoji reaction (positive)")


def test_angry_emoji_review_is_negative():
    r = _classify("😡😡😡")
    assert r["sentiment"] < -0.5
    assert r["core_bucket"] != "Positive Feedback / Praise"


def test_emoji_topics_feed_bucket_matching():
    assert _classify("🐛🐛 after the update")["core_bucket"] == "App Bugs & Glitches"


def test_emoji_shifts_sentiment_of_text():
    plain = _classify("checkout keeps failing")["sentiment"]
    angry = _classify("checkout keeps failing 😡😡")["sentiment"]
    assert angry <= plain


def test_emoji_only_csv_flows_through_analysis(client):
    csv = "text,rating\n👍,5\n🔥🔥🔥,5\n😡😡,1\nApp keeps crashing 👎,1\n".encode("utf-8")
    assert client.post("/api/ingest/csv", files={"file": ("e.csv", csv)}).json()["count"] == 4
    client.post("/api/analyze", json={})

    items = {i["text"]: i for i in client.get("/api/dashboard").json()["recent_items"]}

    assert items["👍"]["core_bucket"] == "Positive Feedback / Praise"
    assert items["👍"]["sentiment"] > 0
    assert items["😡😡"]["sentiment"] < 0
    assert items["App keeps crashing 👎"]["core_bucket"] == "Crashes & App Stability"
