"""Copyright and access-scope enforcement for IA ingestion.

Priority order (per design.md Addendum A.2):
  1. IA rights/licenseurl metadata field
  2. Collection membership in OPEN_ACCESS_COLLECTIONS
  3. Date heuristic: pub_date.year < pd_cutoff_year()  (never hardcoded)
  4. NULL / unparseable pub_date → metadata_only (safe default)
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load open-access collection list once at import time
# ---------------------------------------------------------------------------

_COLLECTIONS_FILE = Path(__file__).parent / "open_access_collections.json"

def _load_open_access_collections() -> frozenset[str]:
    with _COLLECTIONS_FILE.open() as fh:
        data = json.load(fh)
    collections = frozenset(data["collections"])
    logger.info(
        "Loaded OPEN_ACCESS_COLLECTIONS (%d entries): %s",
        len(collections),
        sorted(collections),
    )
    return collections


OPEN_ACCESS_COLLECTIONS: frozenset[str] = _load_open_access_collections()


# ---------------------------------------------------------------------------
# Rolling public-domain cutoff  (current_year - 96, never a literal year)
# ---------------------------------------------------------------------------

def pd_cutoff_year() -> int:
    """Return the most recent year whose works are in US public domain.

    US copyright expires 96 years after publication (post-1977 term changes
    make this an approximation for pre-1978 works; exact rules vary, but
    current_year - 96 is the safe, dynamically updated floor for the pipeline).
    """
    return datetime.date.today().year - 96


# ---------------------------------------------------------------------------
# Date parsing (handles fuzzy IA date strings)
# ---------------------------------------------------------------------------

def parse_pub_date(raw: str | None) -> datetime.date | None:
    """Parse an IA publication date string into a date.

    IA dates are frequently fuzzy ('19uu', 'circa 1920', '[between 1900 and
    1910]').  Returns None for any value that cannot be resolved to at least a
    year, and logs a warning so operators can review the raw string.

    Returns:
        A datetime.date if the raw value is parseable, else None.
    """
    if not raw or not raw.strip():
        return None

    raw = raw.strip()

    # Attempt full ISO date parse (e.g. "1920-03-15")
    try:
        return datetime.date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        pass

    # Attempt year-only parse from the first four characters
    try:
        year = int(raw[:4])
        if 1000 <= year <= datetime.date.today().year + 5:
            return datetime.date(year, 1, 1)
    except (ValueError, TypeError):
        pass

    logger.warning(
        "Unparseable pub_date value %r — treating source as metadata_only", raw
    )
    return None


# ---------------------------------------------------------------------------
# Rights metadata helpers
# ---------------------------------------------------------------------------

_CC_PREFIXES = ("creativecommons.org", "creativecommons.org")
_PD_STRINGS = ("publicdomain", "public domain", "public-domain")
_RESTRICTED_STRINGS = ("rights reserved", "in-copyright", "all rights reserved")


def _check_rights_field(value: str) -> str | None:
    """Return 'allow', 'block', or None (inconclusive) based on rights text."""
    lower = value.lower()
    if any(cc in lower for cc in _CC_PREFIXES):
        return "allow"
    if any(pd in lower for pd in _PD_STRINGS):
        return "allow"
    if any(r in lower for r in _RESTRICTED_STRINGS):
        return "block"
    return None


# ---------------------------------------------------------------------------
# Main copyright check
# ---------------------------------------------------------------------------

def check_copyright_scope(
    ia_identifier: str,
    pub_date_raw: str | None,
    collection: str | None,
    ia_metadata: dict,
) -> tuple[bool, bool]:
    """Determine whether full text may be fetched for an IA item.

    Args:
        ia_identifier: The IA item identifier (for logging).
        pub_date_raw: The raw publication date string from IA.
        collection: The IA collection name.
        ia_metadata: The full metadata dict from the IA Metadata API.

    Returns:
        (allow_fulltext: bool, is_open_access: bool)
        - allow_fulltext: True if the full OCR text may be fetched.
        - is_open_access: True if access is granted via an explicit rights/
          collection signal (not just age).
    """
    # ------------------------------------------------------------------
    # Step 1: IA rights / licenseurl metadata field
    # ------------------------------------------------------------------
    for field in ("licenseurl", "rights", "licenseUrl"):
        raw_rights = ia_metadata.get(field, "")
        if not raw_rights:
            continue
        decision = _check_rights_field(str(raw_rights))
        if decision == "allow":
            logger.debug(
                "%s: rights field '%s'=%r → open access", ia_identifier, field, raw_rights
            )
            return True, True
        if decision == "block":
            logger.debug(
                "%s: rights field '%s'=%r → in-copyright", ia_identifier, field, raw_rights
            )
            return False, False

    # ------------------------------------------------------------------
    # Step 2: Collection membership
    # ------------------------------------------------------------------
    if collection and collection in OPEN_ACCESS_COLLECTIONS:
        logger.debug(
            "%s: collection %r in OPEN_ACCESS_COLLECTIONS → open access",
            ia_identifier,
            collection,
        )
        return True, True

    # ------------------------------------------------------------------
    # Step 3 + 4: Date heuristic (with NULL / fuzzy safe default)
    # ------------------------------------------------------------------
    parsed_date = parse_pub_date(pub_date_raw)
    if parsed_date is None:
        logger.warning(
            "%s: access-scope-undetermined — pub_date=%r is null/unparseable → metadata_only",
            ia_identifier,
            pub_date_raw,
        )
        return False, False

    cutoff = pd_cutoff_year()
    if parsed_date.year < cutoff:
        logger.debug(
            "%s: pub_date year %d < cutoff %d → PD by age",
            ia_identifier,
            parsed_date.year,
            cutoff,
        )
        return True, False  # PD by age, not an explicit open-access declaration

    logger.debug(
        "%s: pub_date year %d >= cutoff %d → in-copyright",
        ia_identifier,
        parsed_date.year,
        cutoff,
    )
    return False, False
