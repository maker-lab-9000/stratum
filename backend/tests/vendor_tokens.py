"""Vendor names / header signatures that must never appear in vendor-agnostic
code (architecture rule #1: that knowledge lives only in the LLM prompt).

Shared by the validator guard (test_validator) and the eval-corpus guard
(test_evals)."""

FORBIDDEN_VENDOR_TOKENS = [
    "akamai", "cloudflare", "fastly", "cloudfront", "varnish", "dispatcher",
    "nginx", "x-cache", "cf-ray", "cf-cache-status", "x-served-by",
    "x-dispatcher", "x-amz-cf-id", "x-varnish", "x-cache-status", "edgekey",
    "akamaiedge", "cloudfront", "server-timing",
]
