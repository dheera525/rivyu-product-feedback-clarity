"""Read meaning from emojis in feedback.

Short reviews and comments are often just "👍", "🔥🔥🔥" or "😡". Keyword
matching ignores them, so this module maps common emojis to a readable name
and a sentiment score (-1..1), and a few to topic words (🐛 -> "bug").
"""

import re

# emoji -> (readable name, sentiment, optional topic words)
EMOJI_LEXICON = {
    # Positive
    "👍": ("thumbs up", 0.7, ""),
    "👌": ("OK hand", 0.6, ""),
    "👏": ("clapping", 0.7, ""),
    "🙌": ("raised hands", 0.7, ""),
    "🙏": ("thank you", 0.5, ""),
    "💪": ("strong", 0.5, ""),
    "❤": ("heart", 0.8, ""),
    "♥": ("heart", 0.8, ""),
    "🧡": ("heart", 0.8, ""),
    "💛": ("heart", 0.8, ""),
    "💚": ("heart", 0.8, ""),
    "💙": ("heart", 0.8, ""),
    "💜": ("heart", 0.8, ""),
    "🖤": ("heart", 0.6, ""),
    "🤍": ("heart", 0.7, ""),
    "💖": ("sparkling heart", 0.8, ""),
    "💕": ("hearts", 0.8, ""),
    "💗": ("heart", 0.8, ""),
    "😍": ("heart eyes", 0.9, ""),
    "🥰": ("loving face", 0.9, ""),
    "😘": ("kiss", 0.7, ""),
    "🤩": ("star struck", 0.9, ""),
    "😊": ("smiling", 0.6, ""),
    "🙂": ("slight smile", 0.3, ""),
    "😀": ("grinning", 0.6, ""),
    "😃": ("grinning", 0.6, ""),
    "😄": ("grinning", 0.6, ""),
    "😁": ("beaming", 0.6, ""),
    "😆": ("laughing", 0.5, ""),
    "😂": ("tears of joy", 0.4, ""),
    "🤣": ("rolling laughing", 0.4, ""),
    "😎": ("cool", 0.6, ""),
    "🥳": ("party", 0.8, ""),
    "🎉": ("celebration", 0.8, ""),
    "🔥": ("fire", 0.7, ""),
    "💯": ("hundred", 0.8, ""),
    "⭐": ("star", 0.6, ""),
    "🌟": ("glowing star", 0.7, ""),
    "✨": ("sparkles", 0.5, ""),
    "✅": ("check mark", 0.5, ""),
    "✔": ("check mark", 0.4, ""),
    "🚀": ("rocket", 0.7, ""),
    "🏆": ("trophy", 0.7, ""),
    "🥇": ("gold medal", 0.7, ""),
    # Negative
    "👎": ("thumbs down", -0.7, ""),
    "😡": ("angry", -0.9, ""),
    "😠": ("angry", -0.8, ""),
    "🤬": ("swearing", -1.0, ""),
    "😤": ("frustrated", -0.6, ""),
    "😞": ("disappointed", -0.6, ""),
    "😔": ("pensive", -0.4, ""),
    "😟": ("worried", -0.4, ""),
    "😕": ("confused", -0.3, "confusing"),
    "🙁": ("frowning", -0.4, ""),
    "☹": ("frowning", -0.5, ""),
    "😢": ("crying", -0.6, ""),
    "😭": ("sobbing", -0.6, ""),
    "😩": ("weary", -0.6, ""),
    "😫": ("tired", -0.6, ""),
    "😖": ("confounded", -0.6, ""),
    "😣": ("persevering", -0.5, ""),
    "😒": ("unamused", -0.5, ""),
    "🙄": ("eye roll", -0.5, ""),
    "😑": ("expressionless", -0.3, ""),
    "😐": ("neutral face", -0.1, ""),
    "😬": ("grimacing", -0.3, ""),
    "😱": ("screaming", -0.5, ""),
    "🤮": ("vomiting", -0.9, ""),
    "🤢": ("nauseated", -0.8, ""),
    "💩": ("poop", -0.8, ""),
    "💔": ("broken heart", -0.7, ""),
    "❌": ("cross mark", -0.5, ""),
    "🚫": ("prohibited", -0.5, ""),
    "⚠": ("warning", -0.4, ""),
    "🐛": ("bug", -0.5, "bug"),
    "🐌": ("snail", -0.5, "slow"),
    "🐢": ("turtle", -0.4, "slow"),
    "💸": ("money with wings", -0.4, "charged"),
    "🔋": ("battery", -0.2, "battery"),
    "🤦": ("facepalm", -0.6, ""),
    "🤡": ("clown", -0.6, ""),
    "🗑": ("trash", -0.7, ""),
    # Neutral / ambiguous
    "🤔": ("thinking", -0.1, ""),
    "😮": ("surprised", 0.0, ""),
    "😅": ("sweat smile", 0.0, ""),
}

# Variation selectors, skin tones, gender signs and joiners only change how an
# emoji looks, so they're stripped before lookup ("👍🏽" -> "👍").
_MODIFIERS = re.compile("[︎️‍\U0001F3FB-\U0001F3FF♀♂]")

# Rough emoji / pictograph ranges, used to tell "emoji-only" text apart.
_EMOJI_CHARS = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿←-⇿✀-➿]"
)


def _normalize(text):
    return _MODIFIERS.sub("", text or "")


def emoji_signals(text):
    """Return what the emojis in `text` say.

    {
      "count": number of recognised emojis,
      "names": readable names in order of first appearance,
      "sentiment": average sentiment of recognised emojis (0.0 if none),
      "topic_words": extra keywords implied by emojis (e.g. "bug"),
      "emoji_only": True when the text has no letters or digits,
      "has_emoji": True if any emoji-like character is present,
    }
    """
    cleaned = _normalize(text)
    scores, names, topics = [], [], []
    for ch in cleaned:
        entry = EMOJI_LEXICON.get(ch)
        if not entry:
            continue
        name, score, topic = entry
        scores.append(score)
        if name not in names:
            names.append(name)
        if topic and topic not in topics:
            topics.append(topic)

    has_emoji = bool(_EMOJI_CHARS.search(cleaned)) or bool(scores)
    letters = re.sub(r"[\W_]+", "", _EMOJI_CHARS.sub("", cleaned))
    return {
        "count": len(scores),
        "names": names,
        "sentiment": round(sum(scores) / len(scores), 2) if scores else 0.0,
        "topic_words": topics,
        "emoji_only": has_emoji and not letters,
        "has_emoji": has_emoji,
    }


def describe_emojis(text, signals=None):
    """Human-readable summary for emoji-only feedback, e.g. 'Emoji reaction: 👍 thumbs up'."""
    sig = signals or emoji_signals(text)
    if not sig["names"]:
        return "Emoji-only reaction"
    glyphs = []
    for ch in _normalize(text):
        if ch in EMOJI_LEXICON and ch not in glyphs:
            glyphs.append(ch)
    tone = "positive" if sig["sentiment"] >= 0.3 else "negative" if sig["sentiment"] <= -0.3 else "neutral"
    return f"Emoji reaction ({tone}): {''.join(glyphs[:4])} {', '.join(sig['names'][:3])}"
