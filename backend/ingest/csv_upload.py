"""CSV file parser for uploaded feedback data."""

import csv
import hashlib
import io


def parse_csv_feedback(file_content, source_name="csv"):
    """Parse CSV content into normalized raw feedback items.

    Expects columns like: text, date, author, rating, source
    At minimum needs a 'text' or 'feedback' or 'review' column.
    """
    print(f"📄 Parsing CSV upload...")

    try:
        if isinstance(file_content, bytes):
            file_content = file_content.decode("utf-8")

        reader = csv.DictReader(io.StringIO(file_content))
        fieldnames = [f.lower().strip() for f in (reader.fieldnames or [])]

        # Find the text column
        text_col = None
        for candidate in ["text", "feedback", "review", "comment", "content", "body", "message"]:
            if candidate in fieldnames:
                text_col = candidate
                break

        if text_col is None:
            print(f"❌ CSV must have a text column. Found: {fieldnames}")
            return []

        # Map columns by lowercase
        col_map = {f.lower().strip(): f for f in (reader.fieldnames or [])}

        items = []
        for idx, row in enumerate(reader):
            # Normalize row keys to lowercase
            row_lower = {k.lower().strip(): v for k, v in row.items()}

            text = row_lower.get(text_col, "").strip()
            if not text:
                continue

            row_id = hashlib.md5(f"{idx}_{text}".encode()).hexdigest()[:12]

            items.append({
                "id": f"csv_{row_id}",
                "source": source_name,
                "text": text,
                "author": row_lower.get("author", row_lower.get("user", row_lower.get("username", "anonymous"))),
                "date": row_lower.get("date", row_lower.get("timestamp", row_lower.get("created_at", ""))),
                "rating": _safe_int(row_lower.get("rating", row_lower.get("score", None))),
                "metadata": {
                    "row_index": idx,
                    "original_source": row_lower.get("source", source_name)
                }
            })

        print(f"✅ Parsed {len(items)} items from CSV")
        return items

    except Exception as e:
        print(f"❌ CSV parse failed: {e}")
        return []


def _safe_int(val):
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None
