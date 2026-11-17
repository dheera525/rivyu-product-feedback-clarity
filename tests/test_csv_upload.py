import pytest

from backend.ingest.csv_upload import CSVFormatError, parse_csv_feedback


def test_valid_csv_parsed():
    content = (
        b"text,date,author,rating,source\n"
        b'"Payment failed on checkout",2026-04-08,Customer 102,1,call_center\n'
        b'"Love the new design",2026-04-09,Customer 7,5,email\n'
    )

    items = parse_csv_feedback(content)

    assert len(items) == 2
    first = items[0]
    assert first["text"] == "Payment failed on checkout"
    assert first["date"] == "2026-04-08"
    assert first["author"] == "Customer 102"
    assert first["rating"] == 1
    assert first["source"] == "csv"
    assert first["metadata"]["original_source"] == "call_center"
    assert first["id"].startswith("csv_")
    assert items[0]["id"] != items[1]["id"]


def test_alternative_text_column_and_case_insensitive_headers():
    items = parse_csv_feedback(b"Feedback,Score\nToo slow,2.0\n")
    assert items[0]["text"] == "Too slow"
    assert items[0]["rating"] == 2


def test_excel_bom_is_handled():
    items = parse_csv_feedback("﻿text\nhello there\n".encode("utf-8"))
    assert items[0]["text"] == "hello there"


def test_blank_rows_skipped():
    items = parse_csv_feedback(b"text,rating\n,5\nreal feedback,\n")
    assert len(items) == 1
    assert items[0]["rating"] is None


@pytest.mark.parametrize("content, message", [
    (b"", "empty"),
    (b"name,score\nbob,3\n", "No text column found"),
    (b"text,rating\n,1\n,2\n", "no non-empty rows"),
    ("text\ncafé\n".encode("latin-1"), "UTF-8"),
])
def test_invalid_csv_raises_specific_error(content, message):
    with pytest.raises(CSVFormatError, match=message):
        parse_csv_feedback(content)


def test_missing_column_error_lists_found_columns():
    with pytest.raises(CSVFormatError) as exc:
        parse_csv_feedback(b"name,score\nbob,3\n")
    assert "name, score" in str(exc.value)


def test_oversized_file_rejected():
    big = b"text\n" + b"x" * (5 * 1024 * 1024 + 1)
    with pytest.raises(CSVFormatError, match="5 MB"):
        parse_csv_feedback(big)
