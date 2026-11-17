"""CSV file parser for uploaded feedback data."""

import csv
import hashlib
import io

TEXT_COLUMNS = ["text", "feedback", "review", "comment", "content", "body", "message"]
MAX_CSV_BYTES = 5 * 1024 * 1024  # 5 MB


class CSVFormatError(ValueError):
    """Raised when an uploaded CSV can't be turned into feedback items.

    The message is written for end users and is shown directly in the UI.
    """


def parse_csv_feedback(file_content, source_name="csv"):
    """Parse CSV content into normalized raw feedback items.

    Expects columns like: text, date, author, rating, source.
    At minimum needs one of TEXT_COLUMNS.

    Raises CSVFormatError with a specific, user-readable message when the
    file is empty, too large, not UTF-8, has no text column, or has no rows.
    """
    if file_content is None or len(file_content) == 0:
        raise CSVFormatError("The file is empty.")

    if len(file_content) > MAX_CSV_BYTES:
        raise CSVFormatError("The file is larger than 5 MB. Split it into smaller files.")

    if isinstance(file_content, bytes):
        try:
            # utf-8-sig strips the BOM that Excel adds to exported CSVs.
            file_content = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise CSVFormatError("The file isn't UTF-8 text. Re-export it as 'CSV UTF-8' and try again.")

    try:
        reader = csv.DictReader(io.StringIO(file_content))
        raw_fieldnames = reader.fieldnames or []
    except csv.Error as e:
        raise CSVFormatError(f"Couldn't read the file as CSV: {e}")

    fieldnames = [f.lower().strip() for f in raw_fieldnames if f]
    if not fieldnames:
        raise CSVFormatError("No header row found. The first line must name the columns, e.g. 'text,date,rating'.")

    text_col = next((c for c in TEXT_COLUMNS if c in fieldnames), None)
    if text_col is None:
        found = ", ".join(fieldnames[:8])
        raise CSVFormatError(
            f"No text column found (looked for: {', '.join(TEXT_COLUMNS)}). Columns in your file: {found}."
        )

    items = []
    try:
        for idx, row in enumerate(reader):
            row_lower = {
                (k or "").lower().strip(): (v if isinstance(v, str) else "")
                for k, v in row.items()
            }

            text = row_lower.get(text_col, "").strip()
            if not text:
                continue

            row_id = hashlib.md5(f"{idx}_{text}".encode()).hexdigest()[:12]

            items.append({
                "id": f"csv_{row_id}",
                "source": source_name,
                "text": text,
                "author": row_lower.get("author") or row_lower.get("user") or row_lower.get("username") or "anonymous",
                "date": row_lower.get("date") or row_lower.get("timestamp") or row_lower.get("created_at") or "",
                "rating": _safe_int(row_lower.get("rating") or row_lower.get("score")),
                "metadata": {
                    "row_index": idx,
                    "original_source": row_lower.get("source") or source_name
                }
            })
    except csv.Error as e:
        raise CSVFormatError(f"The CSV is malformed near row {len(items) + 2}: {e}")

    if not items:
        raise CSVFormatError(f"The '{text_col}' column has no non-empty rows.")

    print(f"✅ Parsed {len(items)} items from CSV")
    return items


def _safe_int(val):
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None
