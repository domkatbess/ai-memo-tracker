"""Utility for parsing natural language voice queries into search parameters."""

import calendar
import re
from datetime import date, timedelta


# Month name to number mapping (case-insensitive via lower())
_MONTH_MAP = {name.lower(): num for num, name in enumerate(calendar.month_name) if num}
_MONTH_ABBR_MAP = {name.lower(): num for num, name in enumerate(calendar.month_abbr) if num}

# Regex patterns
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONTH_YEAR = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(\d{4})\b",
    re.IGNORECASE,
)
_MEMO_TYPE = re.compile(r"\b(incoming|outgoing)\b", re.IGNORECASE)
_PERSON_NAME = re.compile(
    r"\b(?:by|brought\s+by|took\s+by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
    re.IGNORECASE,
)
_ABOUT_KEYWORD = re.compile(r"\babout\s+(.+)", re.IGNORECASE)

# Relative date keywords
_RELATIVE_DATE = re.compile(
    r"\b(today|yesterday|last\s+week|this\s+week|last\s+month|this\s+month)\b",
    re.IGNORECASE,
)

# Date range patterns: "from X to Y" or "between X and Y"
_DATE_RANGE_ISO = re.compile(
    r"\bfrom\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
_DATE_RANGE_BETWEEN_ISO = re.compile(
    r"\bbetween\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)

# Noise words to strip when extracting title keywords
_NOISE_WORDS = {
    "find", "show", "search", "get", "list", "display", "retrieve",
    "memos", "memo", "records", "record", "all", "the", "a", "an",
    "for", "with", "me", "my", "please", "can", "you",
}


def _last_day_of_month(year: int, month: int) -> int:
    """Return the last day of the given month/year."""
    return calendar.monthrange(year, month)[1]


def _resolve_relative_date(keyword: str) -> tuple[str, str]:
    """Resolve a relative date keyword to (date_from, date_to) ISO strings."""
    today = date.today()
    key = keyword.lower().strip()

    if key == "today":
        iso = today.isoformat()
        return iso, iso
    if key == "yesterday":
        yesterday = today - timedelta(days=1)
        iso = yesterday.isoformat()
        return iso, iso
    if key == "this week":
        start = today - timedelta(days=today.weekday())  # Monday
        end = start + timedelta(days=6)  # Sunday
        return start.isoformat(), end.isoformat()
    if key == "last week":
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    if key == "this month":
        start = today.replace(day=1)
        end = today.replace(day=_last_day_of_month(today.year, today.month))
        return start.isoformat(), end.isoformat()
    if key == "last month":
        first_of_current = today.replace(day=1)
        last_of_prev = first_of_current - timedelta(days=1)
        start = last_of_prev.replace(day=1)
        return start.isoformat(), last_of_prev.isoformat()

    return "", ""


def parse_voice_query(transcribed_text: str) -> dict:
    """Extract search parameters from natural language text.

    Parses the transcribed text to identify:
    - title: keywords that aren't part of other recognized patterns
    - date_from / date_to: from date patterns (month+year, ISO, relative)
    - memo_type: "incoming" or "outgoing"
    - person_name: names after "by", "brought by", "took by"

    Args:
        transcribed_text: The natural language query string.

    Returns:
        A dict with only the extracted parameters. Empty dict if nothing
        can be parsed.
    """
    if not transcribed_text or not isinstance(transcribed_text, str):
        return {}

    text = transcribed_text.strip()
    if not text:
        return {}

    result = {}
    consumed_spans = []  # Track character spans consumed by non-title patterns

    # 1. Extract date range patterns first (most specific)
    range_match = _DATE_RANGE_ISO.search(text) or _DATE_RANGE_BETWEEN_ISO.search(text)
    if range_match:
        result["date_from"] = range_match.group(1)
        result["date_to"] = range_match.group(2)
        consumed_spans.append((range_match.start(), range_match.end()))

    # 2. Extract relative dates
    if "date_from" not in result:
        rel_match = _RELATIVE_DATE.search(text)
        if rel_match:
            date_from, date_to = _resolve_relative_date(rel_match.group(1))
            if date_from:
                result["date_from"] = date_from
                result["date_to"] = date_to
                consumed_spans.append((rel_match.start(), rel_match.end()))

    # 3. Extract month+year patterns
    if "date_from" not in result:
        month_match = _MONTH_YEAR.search(text)
        if month_match:
            month_name = month_match.group(1).lower()
            year = int(month_match.group(2))
            month_num = _MONTH_MAP.get(month_name, 0)
            if month_num:
                last_day = _last_day_of_month(year, month_num)
                result["date_from"] = f"{year}-{month_num:02d}-01"
                result["date_to"] = f"{year}-{month_num:02d}-{last_day:02d}"
                consumed_spans.append((month_match.start(), month_match.end()))

    # 4. Extract single ISO dates (if no range was found)
    if "date_from" not in result:
        iso_matches = list(_ISO_DATE.finditer(text))
        if len(iso_matches) >= 2:
            result["date_from"] = iso_matches[0].group(1)
            result["date_to"] = iso_matches[1].group(1)
            for m in iso_matches[:2]:
                consumed_spans.append((m.start(), m.end()))
        elif len(iso_matches) == 1:
            result["date_from"] = iso_matches[0].group(1)
            result["date_to"] = iso_matches[0].group(1)
            consumed_spans.append((iso_matches[0].start(), iso_matches[0].end()))

    # 5. Extract memo type
    type_match = _MEMO_TYPE.search(text)
    if type_match:
        result["memo_type"] = type_match.group(1).lower()
        consumed_spans.append((type_match.start(), type_match.end()))

    # 6. Extract person name
    person_match = _PERSON_NAME.search(text)
    if person_match:
        result["person_name"] = person_match.group(1).strip()
        consumed_spans.append((person_match.start(), person_match.end()))

    # 7. Extract title keywords
    # First try the "about ..." pattern
    about_match = _ABOUT_KEYWORD.search(text)
    if about_match:
        title_text = about_match.group(1).strip()
        # Remove any consumed patterns from the title text
        # by stripping known extracted values
        for key in ("person_name", "memo_type"):
            if key in result:
                title_text = re.sub(
                    re.escape(result[key]), "", title_text, flags=re.IGNORECASE
                ).strip()
        # Remove date patterns from title
        title_text = _MONTH_YEAR.sub("", title_text).strip()
        title_text = _ISO_DATE.sub("", title_text).strip()
        title_text = _RELATIVE_DATE.sub("", title_text).strip()
        # Remove person pattern prefixes
        title_text = re.sub(
            r"\b(?:by|brought\s+by|took\s+by)\s*", "", title_text, flags=re.IGNORECASE
        ).strip()
        # Clean up noise words and extra whitespace
        words = [w for w in title_text.split() if w.lower() not in _NOISE_WORDS]
        title_text = " ".join(words).strip()
        # Remove trailing/leading punctuation
        title_text = title_text.strip(".,;:!? ")
        if title_text:
            result["title"] = title_text

    return result
