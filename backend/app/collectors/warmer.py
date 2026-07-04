"""Playwright cache warmer (spec §3.2) — best-effort, never fatal.

Drives one real browser navigation to the URL so edge/dispatcher caches populate
the way a browser would, then the sampler (T04) reads clean headers. Optional
(the `warm` flag) and strictly fire-and-continue: no Playwright error — including
a missing browser binary — can abort an analysis (T05 done-criterion). Browser
timing (TTFB/DOM/load) is captured when cheap.

The browser is behind the ``Navigator`` protocol so the warmer's contract (warm
flag, non-fatal errors, timing shape) is unit-tested with a fake; the real
navigation is exercised by the chromium-gated test.
"""

from __future__ import annotations

from typing import Protocol

DEFAULT_TIMEOUT_MS = 15_000

# Navigation Timing API -> our timing dict. Runs in the page after load.
_TIMING_JS = """
() => {
  const nav = performance.getEntriesByType('navigation')[0];
  if (!nav) return null;
  return {
    ttfb_ms: Math.round(nav.responseStart),
    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd),
    load_ms: Math.round(nav.loadEventEnd),
    duration_ms: Math.round(nav.duration),
  };
}
"""


class Navigator(Protocol):
    async def navigate(self, url: str, *, timeout_ms: int) -> dict:
        """Perform one navigation; return a timing dict. Raise on failure."""
        ...


class PlaywrightNavigator:
    """Default navigator: headless Chromium via Playwright."""

    async def navigate(self, url: str, *, timeout_ms: int) -> dict:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                response = await page.goto(url, wait_until="load", timeout=timeout_ms)
                timing = await page.evaluate(_TIMING_JS)
                return {
                    "status": response.status if response else None,
                    "final_url": page.url,
                    **(timing or {}),
                }
            finally:
                await browser.close()


async def warm_cache(
    url: str,
    *,
    warm: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    navigator: Navigator | None = None,
) -> dict:
    """Warm the cache with one navigation. Always returns a serializable dict:

        {"warmed": bool, "skipped": bool, "error": None | str, "timing": dict | None}

    Never raises — a failed warm degrades the stage, it does not fail the run.
    """
    if not warm:
        return {"warmed": False, "skipped": True, "error": None, "timing": None}

    navigator = navigator or PlaywrightNavigator()
    try:
        timing = await navigator.navigate(url, timeout_ms=timeout_ms)
        return {"warmed": True, "skipped": False, "error": None, "timing": timing}
    except Exception as exc:  # noqa: BLE001 — non-fatal by contract
        return {
            "warmed": False,
            "skipped": False,
            "error": f"{type(exc).__name__}: {exc}",
            "timing": None,
        }
