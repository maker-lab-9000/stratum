"""Deterministic evidence collectors (spec §2, §4).

These modules gather ground-truth facts verbatim — DNS, HTTP samples, traceroute,
network enrichment. They NEVER interpret vendor identity or hit/miss state; that
is the LLM's job (§2). Keep this package free of vendor names and header
signatures.
"""
