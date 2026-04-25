"""
Tests for the search_memos Lambda handler.
"""

import json

import pytest
from moto import mock_aws

from backend.memo.search_memos import handler
from backend.shared.dynamodb import (
    memo_pk,
    memo_sk,
    gsi1_type_pk,
    gsi1_date_sk,
    gsi2_person_pk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(params: dict | None = None) -> dict:
    """Build a minimal API Gateway proxy event with query string parameters."""
    return {"queryStringParameters": params}


def _parse_response(response: dict) -> tuple[int, dict]:
    """Return (status_code, parsed_body) from a Lambda proxy response."""
    return response["statusCode"], json.loads(response["body"])


def _insert_memo(table, memo_id: str, title: str, memo_type: str, memo_date: str,
                 person_brought_in: str | None = None,
                 person_took_out: str | None = None):
    """Insert a memo item directly into the DynamoDB table."""
    person_name = person_brought_in if memo_type == "incoming" else person_took_out
    item = {
        "PK": memo_pk(memo_id),
        "SK": memo_sk(),
        "memo_id": memo_id,
        "title": title,
        "memo_type": memo_type,
        "memo_date": memo_date,
        "recorded_at": "2024-01-01T00:00:00Z",
        "entity_type": "MEMO",
        "GSI1PK": gsi1_type_pk(memo_type),
        "GSI1SK": gsi1_date_sk(memo_date),
    }
    if person_brought_in:
        item["person_brought_in"] = person_brought_in
    if person_took_out:
        item["person_took_out"] = person_took_out
    if person_name:
        item["GSI2PK"] = gsi2_person_pk(person_name)
        item["GSI2SK"] = gsi1_date_sk(memo_date)
    table.put_item(Item=item)


def _seed_memos(table):
    """Insert a standard set of memos for testing."""
    _insert_memo(table, "m1", "Budget Allocation Q3", "incoming", "2024-03-15",
                 person_brought_in="Jane Doe")
    _insert_memo(table, "m2", "Policy Update Notice", "outgoing", "2024-06-01",
                 person_took_out="John Smith")
    _insert_memo(table, "m3", "Budget Review Q4", "incoming", "2024-04-10",
                 person_brought_in="Alice Brown")
    _insert_memo(table, "m4", "Travel Request", "outgoing", "2024-05-20",
                 person_took_out="Jane Doe")


# ---------------------------------------------------------------------------
# 1. Search by title returns matching memos (case-insensitive partial match)
# ---------------------------------------------------------------------------


class TestSearchByTitle:
    def test_title_search_case_insensitive_partial_match(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"title": "budget"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        titles = {m["title"] for m in data["memos"]}
        assert "Budget Allocation Q3" in titles
        assert "Budget Review Q4" in titles
        assert len(data["memos"]) == 2

    def test_title_search_uppercase_query(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"title": "BUDGET"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert len(data["memos"]) == 2


# ---------------------------------------------------------------------------
# 2. Search by title returns empty array when no match
# ---------------------------------------------------------------------------


class TestSearchByTitleNoMatch:
    def test_title_search_no_match_returns_empty(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"title": "nonexistent"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["memos"] == []
        assert data["count"] == 0


# ---------------------------------------------------------------------------
# 3. Search by memo_type returns only matching type
# ---------------------------------------------------------------------------


class TestSearchByMemoType:
    def test_search_incoming_returns_only_incoming(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"memo_type": "incoming"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert all(m["memo_type"] == "incoming" for m in data["memos"])
        assert len(data["memos"]) == 2

    def test_search_outgoing_returns_only_outgoing(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"memo_type": "outgoing"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert all(m["memo_type"] == "outgoing" for m in data["memos"])
        assert len(data["memos"]) == 2


# ---------------------------------------------------------------------------
# 4. Search by date range returns memos within range (inclusive)
# ---------------------------------------------------------------------------


class TestSearchByDateRange:
    def test_date_range_inclusive(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        # Range covers m1 (2024-03-15) and m3 (2024-04-10)
        event = _make_event({"date_from": "2024-03-01", "date_to": "2024-04-30"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        memo_ids = {m["memo_id"] for m in data["memos"]}
        assert "m1" in memo_ids
        assert "m3" in memo_ids
        assert len(data["memos"]) == 2

    def test_date_range_excludes_outside(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        # Range only covers m2 (2024-06-01)
        event = _make_event({"date_from": "2024-06-01", "date_to": "2024-06-30"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert len(data["memos"]) == 1
        assert data["memos"][0]["memo_id"] == "m2"


# ---------------------------------------------------------------------------
# 5. Search by memo_type + date range combined
# ---------------------------------------------------------------------------


class TestSearchByTypeAndDateRange:
    def test_type_and_date_range_combined(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        # incoming memos between March and April: m1 and m3
        event = _make_event({
            "memo_type": "incoming",
            "date_from": "2024-03-01",
            "date_to": "2024-04-30",
        })

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert all(m["memo_type"] == "incoming" for m in data["memos"])
        memo_ids = {m["memo_id"] for m in data["memos"]}
        assert "m1" in memo_ids
        assert "m3" in memo_ids
        assert len(data["memos"]) == 2

    def test_type_and_date_range_narrows_results(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        # outgoing memos in May only: m4
        event = _make_event({
            "memo_type": "outgoing",
            "date_from": "2024-05-01",
            "date_to": "2024-05-31",
        })

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert len(data["memos"]) == 1
        assert data["memos"][0]["memo_id"] == "m4"


# ---------------------------------------------------------------------------
# 6. Search by person_name returns matching memos
# ---------------------------------------------------------------------------


class TestSearchByPersonName:
    def test_person_name_search(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        # Jane Doe appears as person_brought_in on m1 and person_took_out on m4
        event = _make_event({"person_name": "Jane Doe"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        memo_ids = {m["memo_id"] for m in data["memos"]}
        assert "m1" in memo_ids
        assert "m4" in memo_ids
        assert len(data["memos"]) == 2

    def test_person_name_case_insensitive(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"person_name": "jane doe"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert len(data["memos"]) == 2


# ---------------------------------------------------------------------------
# 7. Search with no parameters returns all memos
# ---------------------------------------------------------------------------


class TestSearchNoParameters:
    def test_no_params_returns_all_memos(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event(None)

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert len(data["memos"]) == 4

    def test_no_params_empty_table(self, dynamodb_table):
        event = _make_event(None)

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["memos"] == []
        assert data["count"] == 0


# ---------------------------------------------------------------------------
# 8. Response includes count matching array length
# ---------------------------------------------------------------------------


class TestResponseCount:
    def test_count_matches_array_length(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"memo_type": "incoming"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["count"] == len(data["memos"])

    def test_count_zero_for_empty_results(self, dynamodb_table):
        event = _make_event({"title": "nothing"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        assert data["count"] == 0
        assert data["count"] == len(data["memos"])


# ---------------------------------------------------------------------------
# 9. Response excludes DynamoDB key attributes
# ---------------------------------------------------------------------------


class TestResponseExcludesKeyAttributes:
    def test_key_attributes_stripped(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event(None)

        status, data = _parse_response(handler(event, None))

        assert status == 200
        key_attrs = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"}
        for memo in data["memos"]:
            for key in key_attrs:
                assert key not in memo

    def test_key_attributes_stripped_in_gsi_query(self, dynamodb_table):
        _seed_memos(dynamodb_table)
        event = _make_event({"memo_type": "incoming"})

        status, data = _parse_response(handler(event, None))

        assert status == 200
        key_attrs = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"}
        for memo in data["memos"]:
            for key in key_attrs:
                assert key not in memo
