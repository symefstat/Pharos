"""
Country → Prosus-lens region mapping.

The feed tables store `country` as ISO-3166 alpha-2 (or 'GLOBAL'); the Prosus
page filters by region. Mapping at query time keeps region logic in one place
and needs no migration or backfill: a region lens becomes a
`country IN (countries_for_region(...))` filter.

'latam', 'india' and 'europe' are Prosus's declared strategic geographies and
are the three lenses surfaced in the UI; the rest exist so every article lands
in a bucket rather than a catch-all.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List

# Turkey sits with Europe: Prosus reports iyzico/PayU Turkey alongside its
# European fintech footprint.
REGION_COUNTRIES: Dict[str, FrozenSet[str]] = {
    "latam": frozenset({
        "BR", "MX", "AR", "CL", "CO", "PE", "UY", "EC", "VE", "BO", "PY",
        "CR", "PA", "DO", "GT", "SV", "HN", "NI", "CU", "PR",
    }),
    "india": frozenset({"IN"}),
    "europe": frozenset({
        "GB", "DE", "FR", "NL", "ES", "IT", "PT", "PL", "RO", "CZ", "SK",
        "HU", "AT", "BE", "CH", "SE", "NO", "DK", "FI", "IE", "GR", "BG",
        "HR", "SI", "LT", "LV", "EE", "LU", "MT", "CY", "IS", "UA", "RS",
        "TR",
    }),
    "us": frozenset({"US", "CA"}),
    "china": frozenset({"CN", "HK"}),
    "sea": frozenset({"ID", "SG", "PH", "VN", "TH", "MY", "KH", "MM", "LA", "BN"}),
    "mena": frozenset({
        "AE", "SA", "EG", "QA", "KW", "BH", "OM", "JO", "LB", "IL",
        "MA", "TN", "DZ", "IQ",
    }),
    "africa": frozenset({
        "ZA", "NG", "KE", "GH", "ET", "TZ", "UG", "SN", "CI", "ZM", "ZW",
    }),
}

_COUNTRY_TO_REGION: Dict[str, str] = {
    cc: region for region, ccs in REGION_COUNTRIES.items() for cc in ccs
}


def region_for_country(country: str | None) -> str:
    """Region bucket for a feed row's `country` value.
    'GLOBAL' → 'global'; unknown/missing codes → 'other'. Pure."""
    if not country:
        return "other"
    cc = country.strip().upper()
    if cc == "GLOBAL":
        return "global"
    return _COUNTRY_TO_REGION.get(cc, "other")


def countries_for_region(region: str) -> List[str]:
    """Sorted country codes for a region — the `.in_()` filter list for a
    region lens. Unknown region → []. Pure."""
    return sorted(REGION_COUNTRIES.get(region, frozenset()))
