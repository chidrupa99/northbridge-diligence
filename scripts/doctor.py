"""
doctor.py — verify this install works on THIS machine.

    python scripts/doctor.py

The test suite and this script answer different questions, and both are needed.
`pytest` runs against recorded fixtures and never opens a socket, so it proves
the logic is intact — it would pass on a machine with EDGAR firewalled and no
contact header set. This makes real calls and checks the things that actually
break on a new machine: wrong Python, missing dependency, unset or rejected
User-Agent, egress rules that allow one SEC host but not another.

Checks run in the order things fail in practice, and each one that fails prints
what to do about it rather than just going red. Exit code is 0 only if
everything passed, so it can gate a deploy.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]

PASS, FAIL, SKIP = "\033[32m  ok  \033[0m", "\033[31m FAIL \033[0m", "\033[33m skip \033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    PASS, FAIL, SKIP = "  ok  ", " FAIL ", " skip "

# The three SEC hosts this tool talks to. They are separate origins, and a
# corporate egress allowlist routinely permits one and not the others — which
# surfaces as a tool that works until someone asks for a disclosure sweep.
HOSTS = {
    "www.sec.gov": ("https://www.sec.gov/files/company_tickers.json", "ticker lookup"),
    "data.sec.gov": (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        "financial facts",
    ),
    "efts.sec.gov": (
        'https://efts.sec.gov/LATEST/search-index?q=%22substantial+doubt%22&ciks=0000320193',
        "disclosure search",
    ),
}

results: list[tuple[str, bool]] = []


def report(ok: bool | None, label: str, detail: str = "", fix: str = "") -> bool:
    marker = SKIP if ok is None else (PASS if ok else FAIL)
    print(f"[{marker}] {label}" + (f"  —  {detail}" if detail else ""))
    if ok is False and fix:
        for line in fix.strip().splitlines():
            print(f"         {line.strip()}")
    if ok is not None:
        results.append((label, ok))
    return bool(ok)


def check_python() -> bool:
    version = sys.version_info
    ok = version >= (3, 10)
    return report(
        ok,
        "Python version",
        f"{version.major}.{version.minor}.{version.micro}",
        fix="""The MCP SDK requires Python 3.10 or newer, and this code uses 3.10+
               type syntax. Find a newer interpreter -- try `ls /usr/local/bin/python3.*`
               or `brew install python@3.12` -- then recreate the virtualenv with it:
                 <python3.12> -m venv .venv && source .venv/bin/activate
                 pip install -e '.[dev]'
               On Windows the activate path is .venv\\Scripts\\activate instead.""",
    )


def check_dependencies() -> bool:
    missing, found = [], []
    for module, package in (
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
        ("lxml", "lxml"),
        ("mcp", "mcp"),
    ):
        try:
            __import__(module)
            found.append(package)
        except ImportError:
            missing.append(package)

    if missing:
        return report(
            False,
            "Dependencies",
            f"missing: {', '.join(missing)}",
            fix="""Install them into the active environment:
                     pip install -e '.[dev]'
                   If that succeeded but this still fails, you are probably running a
                   different Python than the one you installed into. Check `which python`.""",
        )

    # Which SDK generation is present matters: FastMCP was renamed MCPServer in
    # 2.0, and server.py imports whichever exists.
    try:
        import importlib.metadata as md

        sdk = f"mcp {md.version('mcp')}"
    except Exception:
        sdk = "mcp (version unknown)"
    return report(True, "Dependencies", f"{', '.join(found[:3])}, {sdk}")


def check_package() -> bool:
    """Is THIS project installed, not merely present on disk?

    The most likely single mistake: installing the third-party dependencies but
    not the project itself, or installing into a different Python than the one
    now running. Both leave every dependency satisfied and
    `import northbridge_diligence` still failing, so this needs its own check
    rather than being inferred from the others.
    """
    try:
        import northbridge_diligence
    except ImportError:
        return report(
            False,
            "Package installed",
            "northbridge_diligence not importable",
            fix="""The dependencies are present but this project is not installed.
                   From the repository root:
                     pip install -e '.[dev]'
                   If that reports success and this still fails, pip installed into a
                   different Python than the one running this script. Compare:
                     which python && which pip""",
        )
    location = getattr(northbridge_diligence, "__file__", "") or ""
    editable = "site-packages" not in location
    return report(
        True,
        "Package installed",
        f"v{getattr(northbridge_diligence, '__version__', '?')}"
        + (" (editable)" if editable else ""),
    )


def check_user_agent() -> str | None:
    agent = os.environ.get("EDGAR_USER_AGENT", "").strip()
    if not agent:
        report(
            False,
            "EDGAR_USER_AGENT",
            "not set",
            fix="""SEC rejects unidentified traffic with HTTP 403. Set a contact they
                   could actually reach:
                     export EDGAR_USER_AGENT="Your Name you@example.com"
                   Set the same value in the `env` block of your MCP client config,
                   because the client launches the server in its own environment.""",
        )
        return None
    if "@" not in agent:
        report(
            False,
            "EDGAR_USER_AGENT",
            f'"{agent}" has no contact address',
            fix="""SEC's fair-access policy expects an organisation and a reachable
                   email, e.g. "Northbridge Capital analyst@northbridge.example".""",
        )
        return None
    return agent if report(True, "EDGAR_USER_AGENT", f'"{agent}"') else None


def check_hosts(agent: str) -> bool:
    import requests

    all_ok = True
    for host, (url, purpose) in HOSTS.items():
        started = time.monotonic()
        try:
            response = requests.get(
                url, headers={"User-Agent": agent}, timeout=20
            )
            elapsed = int((time.monotonic() - started) * 1000)
        except requests.RequestException as exc:
            all_ok = False
            report(
                False,
                f"Reach {host}",
                f"{type(exc).__name__}",
                fix=f"""Cannot open a connection at all ({purpose} depends on this host).
                        On a corporate network check the egress allowlist and any proxy —
                        these are three separate origins and are often allowed separately.
                        If you use a proxy, set HTTPS_PROXY before running.""",
            )
            continue

        if response.status_code == 403:
            all_ok = False
            report(
                False,
                f"Reach {host}",
                "HTTP 403 — User-Agent rejected",
                fix="""SEC understood the request and refused it. The contact header is
                       present but not acceptable. Use a real organisation and a reachable
                       email address, not a placeholder.""",
            )
        elif response.status_code != 200:
            all_ok = False
            report(
                False,
                f"Reach {host}",
                f"HTTP {response.status_code}",
                fix="Likely a transient SEC issue. Retry in a minute before digging further.",
            )
        else:
            report(True, f"Reach {host}", f"200 in {elapsed} ms ({purpose})")
    return all_ok


def check_end_to_end() -> bool:
    """One real screen, against a filer that will always exist."""
    from northbridge_diligence import edgar_client as ec

    try:
        result = ec.compute_screening_metrics("AAPL", years=3)
    except Exception as exc:
        return report(
            False,
            "End-to-end screen",
            f"{type(exc).__name__}: {exc}",
            fix="""Network and dependencies checked out, so this points at the client
                   itself. Run `python -m pytest` — if that also fails the install is
                   incomplete; if it passes, the failure is specific to live data.""",
        )

    year = result.get("as_of_fiscal_year")
    metrics = result.get("metrics", {})
    revenue = metrics.get("revenue_cagr")
    if not year or not metrics:
        return report(
            False, "End-to-end screen", "returned an empty result",
            fix="Unexpected — please open the response and check `error`.",
        )
    return report(
        True,
        "End-to-end screen",
        f"AAPL FY{year}, {len(metrics)} metrics, {len(result.get('flags', []))} flags",
    )


def check_server() -> bool:
    import asyncio

    try:
        from northbridge_diligence import server
    except Exception as exc:
        return report(
            False,
            "MCP server",
            f"{type(exc).__name__}: {exc}",
            fix="""northbridge_diligence.server could not be imported, so no MCP client will
                   start it either. If this is an ImportError on `mcp`, the SDK version
                   is incompatible — see requirements.txt.""",
        )

    listed = server.mcp.list_tools()
    if asyncio.iscoroutine(listed):
        listed = asyncio.run(listed)
    names = [tool.name for tool in listed]
    return report(
        len(names) == 8,
        "MCP server",
        f"{len(names)} tools registered",
        fix=f"Expected 8 tools, found {len(names)}: {', '.join(names)}",
    )


def check_skill() -> bool:
    import re

    path = ROOT / "skill" / "SKILL.md"
    if not path.exists():
        return report(False, "Skill", "skill/SKILL.md not found",
                      fix="The skill is part of this repo; re-clone or re-extract it.")
    text = path.read_text()
    front = text.split("---")[1] if text.startswith("---") else ""
    name = re.search(r"name:\s*(.+)", front)
    name = name.group(1).strip() if name else ""
    body = re.search(r"description:\s*>-\n(.*?)(?=\n\w+:|\Z)", front, re.S)
    description = " ".join(body.group(1).split()) if body else ""

    if not name or not description:
        return report(False, "Skill", "frontmatter missing name or description",
                      fix="Both are required, or the skill silently fails to load.")
    if len(name) > 64 or len(description) > 1024:
        return report(
            False, "Skill", f"name {len(name)}/64, description {len(description)}/1024",
            fix="Over the limit means the skill silently fails to load. Shorten it.",
        )
    installed = pathlib.Path.home() / ".claude" / "skills" / "company-screen"
    where = "also installed at ~/.claude/skills/" if installed.exists() else \
            "not yet copied to ~/.claude/skills/ — run: " \
            "mkdir -p ~/.claude/skills && cp -r skill ~/.claude/skills/company-screen"
    return report(True, "Skill", f"{name}, frontmatter valid — {where}")


def main() -> int:
    print("\nNorthbridge Diligence — install check\n")

    # Ordered so this script is useful BEFORE anything is installed: the Python
    # version check runs on any interpreter, so a wrong Python is reported in the
    # first line rather than as a confusing failure three steps later.
    ok_python = check_python()
    ok_deps = check_dependencies()
    ok_package = check_package() if ok_deps else None

    if not (ok_python and ok_deps and ok_package):
        if ok_package is None:
            report(None, "Package installed", "skipped — dependencies missing first")
        report(None, "Remaining checks", "skipped until the above is fixed")
        return summarise()

    agent = check_user_agent()

    if agent:
        network_ok = check_hosts(agent)
        if network_ok:
            check_end_to_end()
        else:
            report(None, "End-to-end screen", "skipped — SEC not reachable")
    else:
        report(None, "SEC connectivity", "skipped — no contact header set")
        report(None, "End-to-end screen", "skipped — no contact header set")

    check_server()
    check_skill()
    return summarise()


def summarise() -> int:
    failed = [name for name, ok in results if not ok]
    print()
    if failed:
        print(f"{len(failed)} of {len(results)} checks failed: {', '.join(failed)}")
        print("Fix the first failure and run again — later ones often follow from it.\n")
        return 1
    print(f"All {len(results)} checks passed. The install is good.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
