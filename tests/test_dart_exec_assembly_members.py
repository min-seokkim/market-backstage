"""PR4-CANONICAL C3 — pure-function tests for dart_exec + assembly_members.

Network-touching ingest paths covered by smoke runs in commit message;
this file pins the parsing primitives so future ingest refactors don't
silently regress birth_ym normalization or term expansion.
"""

from __future__ import annotations

import json

import pytest

from ingest.assembly_members import (
    _last_segment, _make_assembly_actor_id, _parse_terms,
)
from ingest.dart_exec import (
    _make_dart_actor_id, normalize_birth_ym,
)


# ---- DART birth_ym normalization (Korean → YYYYMM) ----------------------

class TestNormalizeBirthYm:
    """DART API returns "1962년 03월"; Tier B matching needs YYYYMM."""

    def test_korean_form(self):
        assert normalize_birth_ym("1962년 03월") == "196203"
        assert normalize_birth_ym("1958년 12월") == "195812"

    def test_dash_form(self):
        assert normalize_birth_ym("1990-05") == "199005"
        assert normalize_birth_ym("1990-12") == "199012"

    def test_already_yyyymm(self):
        assert normalize_birth_ym("196203") == "196203"

    def test_leading_zero_month(self):
        assert normalize_birth_ym("1962년 3월") == "196203"
        assert normalize_birth_ym("1962-3") == "196203"

    def test_empty_or_none(self):
        assert normalize_birth_ym("") is None
        assert normalize_birth_ym(None) is None

    def test_unparseable_returns_none(self):
        assert normalize_birth_ym("invalid") is None
        # Edge: date with no separator falls back gracefully
        result = normalize_birth_ym("198x")
        assert result is None  # no valid year-month digits


# ---- DART actor_id namespace -------------------------------------------

def test_dart_actor_id_pattern():
    actor_id = _make_dart_actor_id("한종희", "00126380", "196203")
    assert actor_id == "person_dart_한종희_00126380_196203"


def test_dart_actor_id_unknown_birth():
    """Missing birth_ym gets 'unknown' suffix — actor_id still stable."""
    actor_id = _make_dart_actor_id("아무개", "00126380", None)
    assert actor_id == "person_dart_아무개_00126380_unknown"


# ---- ASSEMBLY GTELT_ERACO multi-term parsing ---------------------------

class TestParseTerms:
    def test_single_term(self):
        assert _parse_terms("제22대") == [22]

    def test_multi_term(self):
        assert _parse_terms("제9대, 제10대") == [9, 10]

    def test_three_terms(self):
        assert _parse_terms("제12대, 제14대, 제15대") == [12, 14, 15]

    def test_with_extra_whitespace(self):
        # 제 9 대 (extra spaces) should still parse
        assert _parse_terms("제 22 대") == [22]

    def test_empty_returns_empty_list(self):
        assert _parse_terms("") == []
        assert _parse_terms(None) == []


# ---- ASSEMBLY slash-separated trajectory parsing ------------------------

class TestLastSegment:
    """ASSEMBLY API trajectory fields use '/' separator. Last segment is
    the most recent (current) value; full history is in raw_record_json."""

    def test_single_value(self):
        assert _last_segment("조국혁신당") == "조국혁신당"

    def test_two_segments(self):
        assert _last_segment("민주정의당/민주자유당") == "민주자유당"

    def test_three_segments_returns_last(self):
        assert _last_segment(
            "민주정의당/민주자유당/신한국당"
        ) == "신한국당"

    def test_empty_or_none(self):
        assert _last_segment("") is None
        assert _last_segment(None) is None

    def test_strips_surrounding_whitespace(self):
        assert _last_segment("A/  B  ") == "B"


# ---- ASSEMBLY actor_id namespace ----------------------------------------

def test_assembly_actor_id_pattern():
    assert _make_assembly_actor_id("T2T8225E") == "person_assembly_T2T8225E"


# ---- DART exec C5 readiness — birth_ym index path -----------------------

def test_dart_exec_birth_ym_yyyymm_matches_nec_birthday_prefix():
    """Tier B matching pivot — DART normalized birth_ym must compare
    equal to NEC.birthday[:6]. NEC stores YYYYMMDD, DART stores YYYYMM."""
    nec_birthday = "19641222"  # 이재명 example
    dart_birth_ym = normalize_birth_ym("1964년 12월")
    assert dart_birth_ym == nec_birthday[:6]
    assert dart_birth_ym == "196412"
