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

One gap is worth naming, because this script had it. Until the client-registration
check existed, every check could pass while **no Claude client had the server
registered at all** — the earlier checks import the package in-process and count
tools, which proves the server is installable, not that anything will ever launch
it. A Windows install hit exactly that: ten green checks, and a skill that never
fired, because the MCP server had been registered with Claude Desktop while the
skill sat in Claude Code's directory. `check_clients` reads the client config
files on disk so an unwired install reports as unwired.
"""

from __future__ import annotations

import json
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

SERVER_NAME = "northbridge-diligence"
SKILL_DIR = pathlib.Path.home() / ".claude" / "skills" / "company-screen"


def _desktop_config() -> pathlib.Path:
    """Claude Desktop's config path for this platform."""
    home = pathlib.Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = pathlib.Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def client_configs() -> list[tuple[str, pathlib.Path]]:
    """Every config file a Claude client might read, newest convention first.

    Claude Code reads user scope from ~/.claude.json and project scope from a
    .mcp.json beside the code. Claude Desktop reads its own file. They are
    genuinely separate surfaces: registering with one does not register with the
    other, which is the failure this whole check exists to surface.
    """
    return [
        ("Claude Code (user scope)", pathlib.Path.home() / ".claude.json"),
        ("Claude Code (project scope)", ROOT / ".mcp.json"),
        ("Claude Desktop", _desktop_config()),
    ]


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
        f"{len(names)} tools registered (importable — see Client registration below)",
        fix=f"Expected 8 tools, found {len(names)}: {', '.join(names)}",
    )


def inspect_client_config(path: pathlib.Path) -> dict:
    """Read one client config and describe how this server is registered in it.

    Returns a dict with `state` set to one of:
      absent      — no such file; the client probably is not installed
      unreadable  — file exists but is not parseable JSON
      no-servers  — valid JSON with no `mcpServers` key at all
      not-listed  — has `mcpServers`, but not ours
      registered  — ours is present

    Split out from the check so the parsing is unit-testable without a real
    Claude install. A missing file is deliberately not an error: nobody is
    expected to have every client.
    """
    if not path.exists():
        return {"state": "absent"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return {"state": "unreadable", "error": f"{type(exc).__name__}"}
    if not isinstance(data, dict):
        return {"state": "unreadable", "error": "top level is not an object"}

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return {"state": "no-servers"}
    entry = servers.get(SERVER_NAME)
    if not isinstance(entry, dict):
        return {"state": "not-listed", "others": sorted(servers)}

    command = entry.get("command") or ""
    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    return {
        "state": "registered",
        "command": command,
        "command_exists": bool(command) and pathlib.Path(command).exists(),
        "has_user_agent": bool(env.get("EDGAR_USER_AGENT", "").strip()),
    }


def check_clients() -> bool:
    """Is the server actually registered with a client that will launch it?

    Every check above this one runs in-process. They prove the package is
    installed and the tools are importable — not that any client knows the
    server exists. Those are different claims, and conflating them is how an
    install reports healthy while the skill never fires.
    """
    wired, problems, notes = [], [], []

    for label, path in client_configs():
        info = inspect_client_config(path)
        state = info["state"]
        if state == "absent":
            continue
        if state == "unreadable":
            problems.append(f"{label}: config is not valid JSON ({info['error']}) — "
                            f"the client ignores the whole file until this is fixed")
            continue
        if state in ("no-servers", "not-listed"):
            continue
        wired.append(label)
        if not info["command_exists"]:
            problems.append(
                f"{label}: registered, but `command` does not exist on disk "
                f"({info['command'] or 'empty'})"
            )
        if not info["has_user_agent"]:
            problems.append(
                f"{label}: registered, but no EDGAR_USER_AGENT in its `env` block — "
                f"a GUI-launched client inherits nothing from your shell, so SEC will 403"
            )

    skill_installed = SKILL_DIR.exists()

    if not wired:
        # A config that exists but cannot be parsed is a different diagnosis
        # from one that simply has no entry, and reporting the generic message
        # would send the installer looking in the wrong place. The client
        # ignores an unparseable file wholesale, so every other server in it is
        # silently dead too.
        if problems:
            return report(
                False,
                "Client registration",
                "no usable registration found",
                fix="\n".join(problems + [
                    "Fix the file above first — a client ignores it entirely while it is "
                    "malformed — then add the mcpServers entry per DEPLOYMENT.md section 5.",
                ]),
            )
        return report(
            False,
            "Client registration",
            "no Claude client has this server registered",
            fix="""The package is installed but nothing will ever launch it. Add an
                   `mcpServers` entry named northbridge-diligence to whichever client you
                   use, then restart it:
                     Claude Code    ~/.claude.json  (top-level "mcpServers" key)
                     Claude Desktop Settings -> Developer -> Edit Config
                   See DEPLOYMENT.md section 5 for the exact block and the per-platform
                   paths. If you are only running tests, this check is expected to fail.""",
        )

    # The exact shape of the Windows failure: MCP on one surface, skill on another.
    only_desktop = wired == ["Claude Desktop"]
    if only_desktop:
        # Per the Claude Code skills docs, Cowork sessions -- the Desktop chat
        # surface -- do not read ~/.claude/skills/ at all; they load skills
        # enabled for the claude.ai account. A Claude Code session launched
        # inside the Desktop app does read it. Same app, two surfaces, and this
        # is the split that produced a healthy-looking but non-working install.
        notes.append(
            "the server is registered with Claude Desktop only. If you use the Desktop "
            "chat (Cowork) surface, it does NOT read ~/.claude/skills/ — enable the "
            "skill for your claude.ai account via Customize in the Desktop sidebar. "
            "A Claude Code session inside the Desktop app does read the local "
            "directory. See DEPLOYMENT.md section 5."
        )
    if not skill_installed:
        notes.append(
            "the skill is not in ~/.claude/skills/company-screen — Claude Code will "
            "not see it. Run the copy in DEPLOYMENT.md section 6."
        )

    detail = "wired: " + ", ".join(wired)
    if problems:
        return report(False, "Client registration", detail,
                      fix="\n".join(problems))
    ok = report(True, "Client registration", detail)
    for note in notes:
        for i, line in enumerate(_wrap(note)):
            print(f"         {'note: ' if i == 0 else '      '}{line}")
    return ok


def _wrap(text: str, width: int = 74) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


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
    # Present on disk is not the same as visible to the surface in use: Cowork
    # sessions load skills from the claude.ai account, not from this directory.
    where = "also in ~/.claude/skills/ (read by Claude Code)" if installed.exists() else \
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
    check_clients()
    return summarise()


def summarise() -> int:
    failed = [name for name, ok in results if not ok]
    print()
    if failed:
        print(f"{len(failed)} of {len(results)} checks failed: {', '.join(failed)}")
        print("Fix the first failure and run again — later ones often follow from it.\n")
        return 1
    # Deliberately narrower than "the install is good". Every check here is
    # local: they prove the server runs and a client references it, not that the
    # client and the skill are on the same surface. Overclaiming here is what let
    # a broken install look healthy.
    print(f"All {len(results)} checks passed — server installed and registered "
          f"with a client.")
    print("Confirm end to end by asking your client to "
          '"Screen Beyond Meat for the deal team".\n')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
