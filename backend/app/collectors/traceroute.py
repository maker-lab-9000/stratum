"""TCP traceroute runner (spec §3.4, §9) — deterministic evidence only.

Runs a TCP traceroute to port 443 via ``mtr --json`` (preferred) or
``tcptraceroute`` and normalizes the output to a hop list
``{n, ip, rtt_ms, unresponsive}``. It records raw network facts; it never maps
hops to cache layers — that inference is architecturally forbidden (§2 corollary)
and belongs to no code at all.

Robustness (T06 done-criterion): operational failures — missing binary, missing
NET_RAW capability, subprocess hang — never raise out of ``run_traceroute``.
They come back as a JSON-serializable result with ``hops: []`` and a typed
``error``, so an analysis still completes with the rest of its evidence intact.

Subprocess execution is behind the ``SubprocessRunner`` protocol so tests feed
recorded ``mtr``/``tcptraceroute`` output without touching the network.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import shutil
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

DEFAULT_PORT = 443
DEFAULT_COUNT = 3
DEFAULT_TIMEOUT_S = 30.0

_NET_RAW_HINT = (
    "The traceroute tool needs raw-socket privileges. In Docker grant the api "
    "service NET_RAW (and likely NET_ADMIN), or use host networking (spec §9)."
)


# --- typed errors -------------------------------------------------------------

class TracerouteError(Exception):
    error_type = "TracerouteError"

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        return {"type": self.error_type, "message": self.message, "hint": self.hint}


class TracerouteUnavailable(TracerouteError):
    """No traceroute binary is installed/found."""

    error_type = "TracerouteUnavailable"


class TraceroutePermissionError(TracerouteError):
    """The tool ran but lacked raw-socket capability (NET_RAW)."""

    error_type = "TraceroutePermissionError"


class TracerouteTimeout(TracerouteError):
    """The subprocess exceeded its timeout and yielded no usable hops."""

    error_type = "TracerouteTimeout"


# --- subprocess abstraction ---------------------------------------------------

@dataclass
class RunResult:
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool


class SubprocessRunner(Protocol):
    async def run(self, argv: list[str], timeout_s: float) -> RunResult:
        """Run argv. Raise FileNotFoundError if the binary is missing. On
        timeout, kill and return partial output with ``timed_out=True``."""
        ...


class DefaultSubprocessRunner:
    async def run(self, argv: list[str], timeout_s: float) -> RunResult:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            return RunResult(
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                proc.returncode,
                timed_out=False,
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                stdout, stderr = await proc.communicate()
            except Exception:
                stdout, stderr = b"", b""
            return RunResult(
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                proc.returncode,
                timed_out=True,
            )


# --- public entrypoint --------------------------------------------------------

async def run_traceroute(
    host: str,
    *,
    port: int = DEFAULT_PORT,
    count: int = DEFAULT_COUNT,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    tool: str | None = None,
    runner: SubprocessRunner | None = None,
) -> dict:
    """TCP traceroute to ``host``:``port``. Always returns a serializable dict:

        {"tool", "target", "port", "hops": [...], "timed_out": bool,
         "error": None | {"type", "message", "hint"}}
    """
    runner = runner or DefaultSubprocessRunner()
    target = _target_host(host)
    tool, argv = _select_tool_and_argv(tool, target, port, count)

    if tool is None:
        return _error_result(
            None,
            target,
            port,
            TracerouteUnavailable(
                "No traceroute tool found (looked for mtr, tcptraceroute).",
                hint="Install mtr (recommended) or tcptraceroute. " + _NET_RAW_HINT,
            ),
        )

    try:
        result = await runner.run(argv, timeout_s)
    except FileNotFoundError:
        return _error_result(
            tool,
            target,
            port,
            TracerouteUnavailable(
                f"{tool} not found on PATH.",
                hint="Install mtr (recommended) or tcptraceroute. " + _NET_RAW_HINT,
            ),
        )

    parser = parse_mtr_json if tool == "mtr" else parse_tcptraceroute
    try:
        hops = parser(result.stdout)
    except Exception:
        hops = []

    if hops:
        # Success — possibly partial if it timed out mid-run (scenario 4).
        return {
            "tool": tool,
            "target": target,
            "port": port,
            "hops": hops,
            "timed_out": result.timed_out,
            "error": None,
        }

    # No hops: classify the failure.
    if _looks_like_permission_error(result.stderr):
        return _error_result(
            tool,
            target,
            port,
            TraceroutePermissionError(result.stderr.strip()[:300] or "raw socket denied", hint=_NET_RAW_HINT),
        )
    if result.timed_out:
        return _error_result(
            tool, target, port, TracerouteTimeout(f"{tool} timed out after {timeout_s}s with no hops.")
        )
    return _error_result(
        tool,
        target,
        port,
        TracerouteError(
            f"{tool} produced no hops (exit {result.returncode}). {result.stderr.strip()[:200]}"
        ),
    )


# --- parsers ------------------------------------------------------------------

def parse_mtr_json(text: str) -> list[dict]:
    """Parse ``mtr --json`` output (hubs list) into normalized hops."""
    data = json.loads(text)
    hubs = data["report"]["hubs"]
    hops: list[dict] = []
    for hub in hubs:
        host = hub.get("host")
        unresponsive = host in (None, "", "???")
        rtt = None if unresponsive else _first_present(hub, ("Best", "Avg", "Last"))
        hops.append(
            {
                "n": int(hub.get("count")),
                "ip": None if unresponsive else host,
                "rtt_ms": _round(rtt),
                "unresponsive": unresponsive,
            }
        )
    return _collapse_final_duplicates(hops)


def parse_tcptraceroute(text: str) -> list[dict]:
    """Parse ``tcptraceroute`` text output into normalized hops."""
    hops: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^(\d+)\s+(.*)$", stripped)
        if not match:
            continue
        n = int(match.group(1))
        tokens = match.group(2).split()
        if tokens and all(tok == "*" for tok in tokens):
            hops.append({"n": n, "ip": None, "rtt_ms": None, "unresponsive": True})
            continue

        ip: str | None = None
        rtts: list[float] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if ip is None and _is_ip(tok):
                ip = tok
            elif _is_float(tok) and i + 1 < len(tokens) and tokens[i + 1] == "ms":
                rtts.append(float(tok))
                i += 1
            i += 1

        if ip is None:
            hops.append({"n": n, "ip": None, "rtt_ms": None, "unresponsive": True})
        else:
            hops.append(
                {
                    "n": n,
                    "ip": ip,
                    "rtt_ms": _round(min(rtts)) if rtts else None,
                    "unresponsive": False,
                }
            )
    return _collapse_final_duplicates(hops)


# --- helpers ------------------------------------------------------------------

def _select_tool_and_argv(
    tool: str | None, target: str, port: int, count: int
) -> tuple[str | None, list[str]]:
    if tool is None:
        if shutil.which("mtr"):
            tool = "mtr"
        elif shutil.which("tcptraceroute"):
            tool = "tcptraceroute"
    if tool == "mtr":
        return tool, ["mtr", "--json", "-n", "-T", "-P", str(port), "-c", str(count), target]
    if tool == "tcptraceroute":
        return tool, ["tcptraceroute", "-n", target, str(port)]
    return None, []


def _error_result(tool: str | None, target: str, port: int, err: TracerouteError) -> dict:
    return {
        "tool": tool,
        "target": target,
        "port": port,
        "hops": [],
        "timed_out": False,
        "error": err.to_dict(),
    }


def _collapse_final_duplicates(hops: list[dict]) -> list[dict]:
    """Collapse trailing consecutive hops that share an IP (the destination
    probed several times) into one hop, keeping the earliest hop number and the
    best (min) RTT (spec §3.4 scenario 5)."""
    result = list(hops)
    while len(result) >= 2:
        prev, last = result[-2], result[-1]
        if prev["ip"] is not None and prev["ip"] == last["ip"]:
            result[-2:] = [
                {
                    "n": prev["n"],
                    "ip": prev["ip"],
                    "rtt_ms": _min_ignore_none(prev["rtt_ms"], last["rtt_ms"]),
                    "unresponsive": False,
                }
            ]
        else:
            break
    return result


def _looks_like_permission_error(stderr: str) -> bool:
    lowered = stderr.lower()
    needles = (
        "operation not permitted",
        "permission denied",
        "must be run as root",
        "must be root",
        "requires root",
        "raw socket",
        "net_raw",
        "you do not have permission",
        "setuid",
        # mtr / mtr-packet phrasing when it cannot open raw sockets:
        "failure to open ipv4 sockets",
        "failure to open ipv6 sockets",
        "failure to start mtr-packet",
    )
    return any(needle in lowered for needle in needles)


def _target_host(host: str) -> str:
    value = host.strip()
    if "://" in value:
        value = urlparse(value).hostname or ""
    elif "/" in value:
        value = value.split("/", 1)[0]
    return value.rstrip(".")


def _is_ip(token: str) -> bool:
    try:
        ipaddress.ip_address(token)
        return True
    except ValueError:
        return False


def _is_float(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


def _first_present(hub: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in hub and hub[key] is not None:
            return hub[key]
    return None


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


def _min_ignore_none(a: float | None, b: float | None) -> float | None:
    values = [v for v in (a, b) if v is not None]
    return min(values) if values else None
