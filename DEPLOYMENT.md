# Deploying at Northbridge

For whoever installs this on analysts' machines. The tool runs locally per user,
alongside their Claude client, so this is desktop support rather than a server
deployment.

If you are picking this up to *extend* it, see [DEVELOPING.md](DEVELOPING.md).

### What you are deploying

A local Python process that an analyst's Claude client starts on demand. There is no service to host, no inbound port, and no database.

| | |
|---|---|
| **Runs** | Locally, per user, launched by the Claude client over stdio |
| **Talks to** | `www.sec.gov`, `data.sec.gov`, `efts.sec.gov` — HTTPS, outbound only |
| **Credentials** | **None.** SEC EDGAR is public: no account, no API key, no cost |
| **Data sent out** | Company names and tickers being researched. No firm data, no positions, no documents |
| **Data stored** | An in-process cache only (64 entries, 1 hour). Nothing written to disk; it dies with the process |
| **Rate limiting** | Self-throttled to ~8 req/s, under SEC's 10/s fair-access limit |

The one configuration value, `EDGAR_USER_AGENT`, is **not a credential** — it is a contact string SEC requires so they can reach someone about unusual traffic. Set it to a real, monitored address at your firm. EDGAR returns HTTP 403 without it.

**Egress:** the three SEC hosts above are separate origins. An allowlist that permits `www.sec.gov` but not `efts.sec.gov` yields a tool that works until someone asks for a disclosure sweep. `doctor.py` tests all three separately for exactly this reason.

### Prerequisites

- **Python 3.10 or newer** — the MCP SDK requires it, and this code uses 3.10+ type syntax
- A **desktop-class** MCP client — **Claude Desktop** or **Claude Code**

`edgar-mcp` speaks MCP over stdio, so the client launches it as a local child
process on the analyst's machine. **claude.ai in a browser and the mobile apps
cannot reach it** — a cloud process cannot spawn a binary on someone's laptop.
Those surfaces would need a remote HTTP/SSE server registered as a Custom
Connector, which is out of scope here.

### 1. Put the code on the machine

Extract the submission zip somewhere permanent — the analyst's home folder is fine; a shared install location works too. In this guide the path is:

```
~/Applications/northbridge-diligence/
```

Substitute your own path; every later step uses it.

```bash
unzip northbridge-diligence-submission.zip -d ~/Applications/
cd ~/Applications/northbridge-diligence
```

If you cloned the git repo instead, replace the `unzip` line with `git clone <url> ~/Applications/northbridge-diligence`. Either way the goal is the same: the folder sitting at a path you know.

### 2. Install its Python dependencies

```bash
python3 scripts/doctor.py                    # confirm Python >= 3.10 BEFORE building
python3 -m venv .venv
source .venv/bin/activate                    # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip          # editable installs need pip >= 21.3
pip install -e .
```

Run `doctor.py` first, before creating the virtualenv. It runs on **any** Python
version, so a too-old interpreter is reported immediately rather than as a
confusing dependency failure two steps later. If `python3` is older than 3.10,
find a newer one (`ls /usr/local/bin/python3.*`, or `brew install python@3.12`)
and use that name in the `venv` line.

> **Upgrading an existing install?** Quit the Claude client before running
> `pip install -e .` again. On Windows the running client holds `edgar-mcp.exe`
> open, pip uninstalls the old package *before* it discovers it cannot write the
> new one, and you are left with no working install. macOS and Linux tolerate the
> replacement, but quitting first is the safe habit on any platform.

`python3 -m venv .venv` creates a **virtual environment** — a private Python installation inside the project folder, so the four libraries this tool needs (`mcp`, `requests`, `beautifulsoup4`, `lxml`) do not touch the system Python other tools may depend on. `source .venv/bin/activate` switches the current terminal to use it. `pip install -e .` reads `pyproject.toml`, installs those dependencies, and puts this project's own `edgar-mcp` command on the venv's PATH.

### 3. Set the SEC contact header

```bash
export EDGAR_USER_AGENT="Northbridge Capital Partners research@northbridge.example"
```

`export` sets an **environment variable** — a named value the terminal remembers for this session and passes to any program launched from it. `EDGAR_USER_AGENT` is the name our code looks up; the string in quotes is what SEC sees when the tool makes a request. This is not a credential — EDGAR is public, no login exists — it is a contact string SEC's fair-access policy requires so they can reach someone about unusual traffic. Use a real, monitored address at your firm; without it, EDGAR returns HTTP 403.

The `export` lasts only for this terminal session. In step 5 you set the same value again inside the Claude client's config, and that copy is what applies when the client launches the server for real.

### 4. Verify — before wiring anything into a client

```bash
python scripts/doctor.py
```

Eleven checks: Python version, whether this project itself is installed, dependencies, the contact header, reachability of each SEC host separately, a live screen of a real company, the 8 registered tools, the skill's frontmatter, and **which Claude clients actually have the server registered**. Every failure prints its fix. Exit code is 0 only when all pass, so it can gate a rollout.

The last check is the one that matters most after step 5, and it will fail now — nothing is registered yet. Run `doctor.py` again after step 6.

Do this **before** step 5. Otherwise a broken install first appears as a skill that silently returns nothing inside a Claude conversation — the worst possible place to debug it.

### 5. Register the server with the Claude client

This one is not a shell command. It edits a **JSON configuration file** on disk that the Claude client reads at launch.

**First decide which surface you are installing for.** The tool has two halves — the MCP server and the skill — and they live in different places for different clients. Registering the server with one client and copying the skill into another client's directory leaves both halves installed and neither surface working, with every check still reporting green. That is the single most common install failure.

| Surface | MCP server config | Skill location | Works? |
|---|---|---|---|
| **Claude Code** — the CLI, or a Code session launched inside the Desktop app | `~/.claude.json` → top-level `mcpServers` (user scope, every project) · or `claude mcp add …` if the CLI is on PATH · or a project-level `.mcp.json` (that folder only) | `~/.claude/skills/company-screen` | **Yes** |
| **Claude Desktop — Cowork / chat sessions** | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) · `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) · or Settings → Developer → Edit Config | **Not `~/.claude/skills/`.** Cowork sessions do not read that directory — enable the skill for your claude.ai account via **Customize** in the Desktop sidebar | **Yes**, both halves — but the skill comes from account sync, not the filesystem |
| **claude.ai web / mobile** | Not possible — `edgar-mcp` speaks stdio and runs as a local child process; a cloud process cannot spawn a binary on your machine. Would need a remote HTTP/SSE server as a Custom Connector, which this repo does not build | Account-synced skills do load here | **No** — the skill triggers but its tools are unreachable |

> [!NOTE]
> **"Claude Desktop" is two surfaces, and this is what most installs get wrong.** Per the [Claude Code skills docs](https://code.claude.com/docs/en/skills): *"Cowork sessions and cloud sessions… don't read `~/.claude/skills/` on your machine. Both interactive and scheduled Cowork sessions load the skills enabled for your claude.ai account."* A Claude Code session in the Desktop app **does** read the local directory; a Cowork chat session in the same app does **not**. Desktop scheduled tasks run locally and behave like any local session.
>
> The claude.ai row is the trap worth knowing: you can enable the skill for your account there and it will trigger, but the MCP server is not reachable, so it has no data. The skill's "no figure without a citation" rule should make that fail visibly rather than invent numbers — but you will see a skill that looks installed and produces nothing.

**Where the file lives:**

- **Claude Code (user scope) — `~/.claude.json`.** This is the route that works when the desktop app is installed without the standalone CLI, so `claude` is not on PATH. It applies to every project rather than one folder. On a fresh install this file exists but has **no `mcpServers` key at all** — it holds cache and telemetry keys — so the key must be *added* alongside them, not edited:

  ```jsonc
  {
    "machineID": "…",              // existing keys — leave every one of them alone
    "firstStartTime": "…",
    "mcpServers": {                // add this whole key as a sibling
      "northbridge-diligence": {
        "command": "/Users/<user>/Applications/northbridge-diligence/.venv/bin/edgar-mcp",
        "env":     { "EDGAR_USER_AGENT": "Northbridge Capital Partners research@northbridge.example" }
      }
    }
  }
  ```

- **Claude Code (project scope) — `.mcp.json`** beside the code. Binds the server to that one folder, which is usually not what a per-user install wants.
- **Claude Desktop (macOS):** `~/Library/Application Support/Claude/claude_desktop_config.json` — easiest opened from Claude Desktop → Settings → Developer → Edit Config.
- **Claude Desktop (Windows):** `%APPDATA%\Claude\claude_desktop_config.json` — same route through Settings → Developer.

> **Quit the client before editing.** Claude Desktop keeps this file in memory and
> writes its own `preferences` back over it while running, so an edit made to a
> live config gets silently clobbered — an added `mcpServers` key was observed
> disappearing within two minutes. Quit the app fully, edit, save, then reopen.
> This is separate from the restart needed *after* editing: quit before, reopen
> after.

**Add — do not replace.** That file may already have content: `preferences`, `mcpServers` for other tools, `coworkUserFilesPath`. Overwriting it wipes what is already there. If `mcpServers` does not exist yet, add the whole key as a sibling of anything already present. If it does, add `northbridge-diligence` inside it alongside the other servers.

The block to add — with **your real paths**, not `/absolute/path/to/...`:

```jsonc
{
  "mcpServers": {
    "northbridge-diligence": {
      "command": "/Users/<user>/Applications/northbridge-diligence/.venv/bin/edgar-mcp",
      "env":     { "EDGAR_USER_AGENT": "Northbridge Capital Partners research@northbridge.example" }
    }
  }
}
```

On Windows the path is `...\.venv\Scripts\edgar-mcp.exe`. To print the exact
value to paste, with the virtualenv active:

```bash
python -c "import shutil; print(shutil.which('edgar-mcp'))"
```

Then **restart Claude Desktop** — it only reads this file at launch.

Four things that catch people out here:

- **Nobody runs `edgar-mcp` by hand.** It speaks MCP over *stdio*, so it waits silently on standard input — run it in a terminal and you get a cursor that never returns, which looks broken but is correct. The client launches it, the way an operating system talks to a plugged-in device.
- **Point `command` at the virtualenv's `edgar-mcp`**, not a bare `edgar-mcp`. The client starts the server in its own environment and will not inherit an activated venv, so an unqualified command will not be found.
- **Absolute paths only.** No `~`, no relative paths. The client is not running from a shell so tilde-expansion does not happen.
- **The `env` block here is separate from the `export` in step 3, and both are required.** A GUI-launched client inherits nothing from a terminal, and each client spawns its own copy of the server — so the value has to be duplicated into every client config you create. The `export` covers `doctor.py` in your shell; the `env` block covers the server as the client runs it. Omit the `env` block and SEC returns 403 to the client while `doctor.py` keeps passing.

If the JSON is malformed — a missing comma, an unmatched bracket — Claude silently ignores the whole file. Paste it through a JSON validator before saving, or watch your editor's syntax highlighting; if the file goes red, do not restart yet.

### 6. Install the skill

```bash
# macOS / Linux
mkdir -p ~/.claude/skills
cp -r skill ~/.claude/skills/company-screen
```

```powershell
# Windows PowerShell — mkdir -p and cp -r are POSIX and will not run here
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse -Force .\skill "$HOME\.claude\skills\company-screen"
```

The directory creation is not decorative: `cp` fails with "No such file or
directory" if `~/.claude/skills/` does not exist yet, which it will not on a
machine where the Claude client has never loaded a skill.

### 7. Confirm it works for the analyst

Have them say: **"Screen Beyond Meat for the deal team"** — or any ticker or company name. There is no command to remember; the skill triggers on the request itself, so "size up Dollar General" or "pull the financials on TGT" work equally well.

**How to confirm it worked.** Two tells:

1. `[S1]`-style source markers on every figure in the memo
2. A Sources table at the bottom mapping each marker to a filing accession and URL

> **Figures without source markers mean the skill is not being used.** Claude answered from its own knowledge rather than calling the tools, and those numbers trace to nothing. Re-check step 6 and confirm the client was restarted after step 5.

If the analyst names an ambiguous company — "Delta", "American" — the skill returns candidates and asks which they mean rather than guessing. That is intended behaviour, not a failure.

### If something goes wrong

`doctor.py` names the fix for each failure. The three you will actually hit:

| Symptom | Cause |
|---|---|
| `403` from every SEC host | `EDGAR_USER_AGENT` unset or rejected — check the `env` block in step 5, not just the shell |
| Client silently ignores the config after you edited it | Malformed JSON (missing comma, unmatched bracket). Run the file through a JSON validator, then restart the client |
| Config disappeared after edit | The file got overwritten instead of merged — restore, then add the `mcpServers` key alongside the other keys rather than replacing them |
| Client reports the server failed to start | `command` does not resolve — use the absolute path to `.venv/bin/edgar-mcp` |
| **Tools unavailable in the client, but `doctor.py` passes** | The server is installed and no client references it — check the client config, not the package. `doctor.py` check 11 names which surfaces are wired |
| **Server works but the skill never fires** | Surface mismatch: the MCP server and the skill are on different clients. Re-read the matrix in step 5 and complete both cells of *one* row |
| Skill never triggers, answers come without citations | `skill/` not copied to the right directory for your surface, the directory creation was skipped so the copy failed, or the client was not restarted |
| `claude: command not found` when trying `claude mcp add` | The standalone CLI is not installed. Use the `~/.claude.json` user-scope route in step 5 instead |
| `pip install -e .` fails with a metadata or build error | pip older than 21.3 — run `python -m pip install --upgrade pip` inside the venv first |
| **Windows: reinstall fails with `WinError 32`, file in use** | The Claude client is running and holding `edgar-mcp.exe` open. **Quit the client first.** pip uninstalls before it fails, so a blocked reinstall leaves no working package and sometimes a stray `~orthbridge-diligence` directory in `site-packages` — delete that, then reinstall with the client closed |

