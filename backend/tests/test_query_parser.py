"""Unit tests for the parse_voice_query utility."""

import calendar
from datetime import date, timedelta

import pytest

from backend.voice.query_parser import parse_voice_query


class TestTitleKeywords:
    """Tests for extracting title keywords from queries."""

    def test_about_keyword_extracts_title(self):
        """'about budget' should extract title 'budget'."""
        result = parse_voice_query("find memos about budget")
        assert result["title"] == "budget"

    def test_about_multi_word_title(self):
        """'about quarterly budget' should extract multi-word title."""
        result = parse_voice_query("find memos about quarterly budget")
        assert result["title"] == "quarterly budget"


class TestMemoType:
    """Tests for extracting memo type."""

    def test_incoming_memo_type(self):
        """'incoming' keyword should set memo_type."""
        result = parse_voice_query("show incoming memos")
        assert result["memo_type"] == "incoming"

    def test_outgoing_memo_type(self):
        """'outgoing' keyword should set memo_type."""
        result = parse_voice_query("show outgoing memos")
        assert result["memo_type"] == "outgoing"

    def test_memo_type_case_insensitive(self):
        """Memo type extraction should be case-insensitive."""
        result = parse_voice_query("show INCOMING memos")
        assert result["memo_type"] == "incoming"


class TestPersonName:
    """Tests for extracting person names."""

    def test_by_person_name(self):
        """'by John Smith' should extract person_name."""
        result = parse_voice_query("memos by John Smith")
        assert result["person_name"] == "John Smith"

    def test_brought_by_person_name(self):
        """'brought by Jane Doe' should extract person_name."""
        result = parse_voice_query("memos brought by Jane Doe")
        assert result["person_name"] == "Jane Doe"

    def test_took_by_person_name(self):
        """'took by Bob Jones' should extract person_name."""
        result = parse_voice_query("memos took by Bob Jones")
        assert result["person_name"] == "Bob Jones"


class TestMonthYearDates:
    """Tests for parsing month+year date patterns."""

    def test_january_2024(self):
        """'January 2024' should produce date range for that month."""
        result = parse_voice_query("memos from January 2024")
        assert result["date_from"] == "2024-01-01"
        assert result["date_to"] == "2024-01-31"

    def test_february_leap_year(self):
        """February in a leap year should have 29 days."""
        result = parse_voice_query("memos from February 2024")
        assert result["date_from"] == "2024-02-01"
        assert result["date_to"] == "2024-02-29"

    def test_month_year_case_insensitive(self):
        """Month names should be case-insensitive."""
        result = parse_voice_query("memos from MARCH 2024")
        assert result["date_from"] == "2024-03-01"
        assert result["date_to"] == "2024-03-31"


class TestISODates:
    """Tests for parsing ISO date patterns."""

    def test_iso_date_range_from_to(self):
        """'from YYYY-MM-DD to YYYY-MM-DD' should extract date range."""
        result = parse_voice_query("memos from 2024-01-01 to 2024-03-31")
        assert result["date_from"] == "2024-01-01"
        assert result["date_to"] == "2024-03-31"

    def test_iso_date_range_between_and(self):
        """'between YYYY-MM-DD and YYYY-MM-DD' should extract date range."""
        result = parse_voice_query("memos between 2024-06-01 and 2024-06-30")
        assert result["date_from"] == "2024-06-01"
        assert result["date_to"] == "2024-06-30"

    def test_single_iso_date(self):
        """A single ISO date should set both date_from and date_to."""
        result = parse_voice_query("memos from 2024-05-15")
        assert result["date_from"] == "2024-05-15"
        assert result["date_to"] == "2024-05-15"


class TestRelativeDates:
    """Tests for parsing relative date patterns."""

    def test_today(self):
        """'today' should resolve to today's date."""
        result = parse_voice_query("memos from today")
        today = date.today().isoformat()
        assert result["date_from"] == today
        assert result["date_to"] == today

    def test_yesterday(self):
        """'yesterday' should resolve to yesterday's date."""
        result = parse_voice_query("memos from yesterday")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert result["date_from"] == yesterday
        assert result["date_to"] == yesterday

    def test_last_month(self):
        """'last month' should resolve to the previous month's range."""
        result = parse_voice_query("memos from last month")
        today = date.today()
        first_of_current = today.replace(day=1)
        last_of_prev = first_of_current - timedelta(days=1)
        start = last_of_prev.replace(day=1)
        assert result["date_from"] == start.isoformat()
        assert result["date_to"] == last_of_prev.isoformat()

    def test_this_month(self):
        """'this month' should resolve to the current month's range."""
        result = parse_voice_query("memos from this month")
        today = date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        assert result["date_from"] == today.replace(day=1).isoformat()
        assert result["date_to"] == today.replace(day=last_day).isoformat()


class TestCombinedQueries:
    """Tests for queries with multiple parameters."""

    def test_combined_all_parameters(self):
        """A query with type, date, title, and person should extract all."""
        result = parse_voice_query(
            "find outgoing memos from January 2024 about budget by John Smith"
        )
        assert result["memo_type"] == "outgoing"
        assert result["date_from"] == "2024-01-01"
        assert result["date_to"] == "2024-01-31"
        assert result["title"] == "budget"
        assert result["person_name"] == "John Smith"

    def test_type_and_person(self):
        """Query with memo type and person name."""
        result = parse_voice_query("show outgoing memos by John Smith")
        assert result["memo_type"] == "outgoing"
        assert result["person_name"] == "John Smith"


class TestEmptyAndUnparseable:
    """Tests for empty or unparseable input."""

    def test_empty_string_returns_empty_dict(self):
        """Empty string should return empty dict."""
        assert parse_voice_query("") == {}

    def test_none_returns_empty_dict(self):
        """None input should return empty dict."""
        assert parse_voice_query(None) == {}

    def test_whitespace_only_returns_empty_dict(self):
        """Whitespace-only input should return empty dict."""
        assert parse_voice_query("   ") == {}

    def test_noise_words_only_returns_empty_dict(self):
        """Input with only noise words should return empty dict."""
        assert parse_voice_query("show me all memos") == {}

    def test_random_text_returns_empty_dict(self):
        """Unrecognizable text should return empty dict."""
        assert parse_voice_query("hello world") == {}


class TestCaseInsensitivity:
    """Tests for case-insensitive parsing."""

    def test_uppercase_memo_type(self):
        """INCOMING should be recognized."""
        result = parse_voice_query("show INCOMING memos")
        assert result["memo_type"] == "incoming"

    def test_mixed_case_month(self):
        """Mixed case month names should be recognized."""
        result = parse_voice_query("memos from jAnUaRy 2024")
        assert result["date_from"] == "2024-01-01"

    def test_uppercase_about(self):
        """ABOUT keyword should be recognized."""
        result = parse_voice_query("find memos ABOUT budget")
        assert result["title"] == "budget"
