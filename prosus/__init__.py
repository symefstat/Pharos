"""
Prosus portfolio lens — entity matching and region mapping.

The reference data lives in the `prosus_companies` Supabase table
(SQL Tables/prosus_companies.sql, seeded by prosus_seed.py). This package is
the pure logic around it:

  matcher.py — build an alias index from the table and tag feed articles with
               the portfolio companies they mention (prosus_tags column).
  regions.py — map the feed tables' ISO-3166 `country` codes to Prosus-lens
               regions (latam / india / europe / ...) at query time.
"""
