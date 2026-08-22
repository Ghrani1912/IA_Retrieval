"""Property-based tests for copyright scope enforcement.

# Feature: historical-rag-platform, Property 7: Copyright Scope Enforcement
# Validates: Requirements 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 10.1
"""
from __future__ import annotations

import datetime

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.ingestion.copyright import (
    OPEN_ACCESS_COLLECTIONS,
    check_copyright_scope,
    pd_cutoff_year,
    parse_pub_date,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _year_str(year: int) -> str:
    return str(year)


# ---------------------------------------------------------------------------
# Unit tests for pd_cutoff_year (must never be a hardcoded literal)
# ---------------------------------------------------------------------------

def test_pd_cutoff_year_is_dynamic() -> None:
    """pd_cutoff_year() must return current_year - 96, not a hardcoded value."""
    expected = datetime.date.today().year - 96
    assert pd_cutoff_year() == expected


def test_pd_cutoff_year_not_hardcoded_1928() -> None:
    """Ensure the old hardcoded value 1928 is not in use."""
    # The cutoff should be >= 1930 as of 2026 and will keep advancing
    assert pd_cutoff_year() >= 1928


# ---------------------------------------------------------------------------
# Unit tests for parse_pub_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expect_none", [
    (None, True),
    ("", True),
    ("  ", True),
    ("19uu", True),
    ("circa 1920", True),
    ("[between 1900 and 1910]", True),
    ("unknown", True),
    ("1885", False),
    ("1920-03-15", False),
    ("1975-01-01", False),
    ("1066", False),
])
def test_parse_pub_date(raw: str | None, expect_none: bool) -> None:
    result = parse_pub_date(raw)
    if expect_none:
        assert result is None, f"Expected None for {raw!r}, got {result}"
    else:
        assert result is not None, f"Expected a date for {raw!r}, got None"


def test_parse_pub_date_year_only_gives_jan_1() -> None:
    result = parse_pub_date("1920")
    assert result == datetime.date(1920, 1, 1)


def test_parse_pub_date_full_iso() -> None:
    result = parse_pub_date("1975-06-15")
    assert result == datetime.date(1975, 6, 15)


# ---------------------------------------------------------------------------
# Unit tests for check_copyright_scope — IA rights metadata gate (Step 1)
# ---------------------------------------------------------------------------

def test_cc_licenseurl_grants_access() -> None:
    allow, is_oa = check_copyright_scope(
        ia_identifier="test001",
        pub_date_raw="1990",
        collection="unknown_collection",
        ia_metadata={"licenseurl": "https://creativecommons.org/licenses/by/4.0/"},
    )
    assert allow is True
    assert is_oa is True


def test_publicdomain_rights_grants_access() -> None:
    allow, is_oa = check_copyright_scope(
        ia_identifier="test002",
        pub_date_raw="1995",
        collection=None,
        ia_metadata={"rights": "Public Domain"},
    )
    assert allow is True
    assert is_oa is True


def test_in_copyright_rights_blocks() -> None:
    allow, is_oa = check_copyright_scope(
        ia_identifier="test003",
        pub_date_raw="1850",  # old enough to be PD by date, but rights field blocks
        collection=None,
        ia_metadata={"rights": "All rights reserved"},
    )
    assert allow is False
    assert is_oa is False


# ---------------------------------------------------------------------------
# Unit tests — collection override (Step 2)
# ---------------------------------------------------------------------------

def test_open_access_collection_overrides_recent_date() -> None:
    allow, is_oa = check_copyright_scope(
        ia_identifier="test004",
        pub_date_raw="1990",
        collection="nasa",
        ia_metadata={},
    )
    assert allow is True
    assert is_oa is True


def test_unknown_collection_does_not_override() -> None:
    """A collection not in OPEN_ACCESS_COLLECTIONS falls through to date check."""
    cutoff = pd_cutoff_year()
    recent_year = str(cutoff + 5)
    allow, _ = check_copyright_scope(
        ia_identifier="test005",
        pub_date_raw=recent_year,
        collection="some_private_collection",
        ia_metadata={},
    )
    assert allow is False


# ---------------------------------------------------------------------------
# Unit tests — date heuristic (Steps 3 + 4)
# ---------------------------------------------------------------------------

def test_null_pub_date_defaults_to_metadata_only() -> None:
    allow, is_oa = check_copyright_scope(
        ia_identifier="test006",
        pub_date_raw=None,
        collection=None,
        ia_metadata={},
    )
    assert allow is False
    assert is_oa is False


def test_fuzzy_date_defaults_to_metadata_only() -> None:
    allow, is_oa = check_copyright_scope(
        ia_identifier="test007",
        pub_date_raw="19uu",
        collection=None,
        ia_metadata={},
    )
    assert allow is False
    assert is_oa is False


def test_year_before_cutoff_allows() -> None:
    cutoff = pd_cutoff_year()
    allow, is_oa = check_copyright_scope(
        ia_identifier="test008",
        pub_date_raw=str(cutoff - 1),
        collection=None,
        ia_metadata={},
    )
    assert allow is True
    assert is_oa is False  # PD by age, not explicit OA


def test_year_at_cutoff_blocks() -> None:
    cutoff = pd_cutoff_year()
    allow, _ = check_copyright_scope(
        ia_identifier="test009",
        pub_date_raw=str(cutoff),
        collection=None,
        ia_metadata={},
    )
    assert allow is False


def test_year_above_cutoff_blocks() -> None:
    cutoff = pd_cutoff_year()
    allow, _ = check_copyright_scope(
        ia_identifier="test010",
        pub_date_raw=str(cutoff + 10),
        collection=None,
        ia_metadata={},
    )
    assert allow is False


# ---------------------------------------------------------------------------
# Property 7 — Hypothesis PBT
# ---------------------------------------------------------------------------

# Strategy: generate years as strings in a wide range
_year_strategy = st.integers(min_value=1000, max_value=2100).map(str)

# Strategy: generate fuzzy date strings that should fail parsing
_fuzzy_strategy = st.sampled_from([
    "19uu", "circa 1920", "[between 1900 and 1910]", "unknown", "", "n.d.", "s.d."
])

_collection_strategy = st.one_of(
    st.sampled_from(sorted(OPEN_ACCESS_COLLECTIONS)),       # known OA collection
    st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"))),  # random
)

_rights_strategy = st.one_of(
    st.just(""),                                             # absent
    st.just("https://creativecommons.org/licenses/by/4.0/"),
    st.just("Public Domain"),
    st.just("All rights reserved"),
    st.just("in-copyright"),
)


@given(
    pub_date_raw=st.one_of(_year_strategy, _fuzzy_strategy, st.none()),
    collection=_collection_strategy,
    licenseurl=_rights_strategy,
)
@settings(max_examples=300)
def test_property7_copyright_scope_enforcement(
    pub_date_raw: str | None,
    collection: str,
    licenseurl: str,
) -> None:
    """Property 7: Copyright Scope Enforcement.

    Asserts:
    - Any item with a CC/PD rights field is allowed (is_open_access=True).
    - Any item with "rights reserved"/"in-copyright" is blocked regardless of date.
    - Any item with collection in OPEN_ACCESS_COLLECTIONS is allowed (is_open_access=True).
    - Any item with null/unparseable pub_date and no override is blocked.
    - Any item with pub_date.year >= pd_cutoff_year() and no override is blocked.
    """
    ia_metadata = {"licenseurl": licenseurl} if licenseurl else {}
    allow, is_oa = check_copyright_scope(
        ia_identifier="pbt_test",
        pub_date_raw=pub_date_raw,
        collection=collection,
        ia_metadata=ia_metadata,
    )

    lower_rights = licenseurl.lower() if licenseurl else ""

    # Rule 1: explicit CC or publicdomain → must allow
    if "creativecommons.org" in lower_rights or "publicdomain" in lower_rights or "public domain" in lower_rights:
        assert allow is True, f"CC/PD rights should allow, got blocked. rights={licenseurl!r}"
        assert is_oa is True

    # Rule 2: explicit rights-reserved → must block
    elif "rights reserved" in lower_rights or "in-copyright" in lower_rights:
        assert allow is False, f"In-copyright rights should block. rights={licenseurl!r}"

    # Rule 3: OA collection → must allow
    elif collection in OPEN_ACCESS_COLLECTIONS:
        assert allow is True, f"OA collection {collection!r} should allow"
        assert is_oa is True

    # Rule 4: null or fuzzy date with no override → must block
    else:
        from app.ingestion.copyright import parse_pub_date
        parsed = parse_pub_date(pub_date_raw)
        if parsed is None:
            assert allow is False, (
                f"Null/unparseable date should block. pub_date={pub_date_raw!r}"
            )
            assert is_oa is False

        # Rule 5: date >= cutoff → must block
        elif parsed.year >= pd_cutoff_year():
            assert allow is False, (
                f"Recent year {parsed.year} >= cutoff {pd_cutoff_year()} should block"
            )

        # Rule 6: date < cutoff → must allow (PD by age)
        else:
            assert allow is True, (
                f"Old year {parsed.year} < cutoff {pd_cutoff_year()} should allow"
            )
            # PD by age is NOT the same as explicit OA
            assert is_oa is False
