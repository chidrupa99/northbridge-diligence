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
- An MCP client — **Claude Desktop** or **Claude Code**

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
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`python3 -m venv .venv` creates a **virtual environment** — a private Python installation inside the project folder, so the four libraries this tool needs (`mcp`, `requests`, `beautifulsoup4`, `lxml`) do not touch the system Python other tools may depend on. `source .venv/bin/activate` switches the current terminal to use it. `pip install -r requirements.txt` then reads the dependency list and downloads them into that private environment.

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

Nine checks: Python version, dependencies, the contact header, reachability of each SEC host separately, a live screen of a real company, the 8 registered tools, and the skill's frontmatter. Every failure prints its fix. Exit code is 0 only when all pass, so it can gate a rollout.

Do this **before** step 5. Otherwise a broken install first appears as a skill that silently returns nothing inside a Claude conversation — the worst possible place to debug it.

### 5. Register the server with the Claude client

This one is not a shell command. It edits a **JSON configuration file** on disk that the Claude client reads at launch.

**Where the file lives:**

- **Claude Desktop (macOS):** `~/Library/Application Support/Claude/claude_desktop_config.json` — easiest opened from Claude Desktop → Settings → Developer → Edit Config.
- **Claude Desktop (Windows):** `%APPDATA%\Claude\claude_desktop_config.json` — same route through Settings → Developer.
- **Claude Code:** either a project-level `.mcp.json` in the working folder, or `claude mcp add northbridge-diligence /path/to/.venv/bin/python /path/to/src/server.py` from a terminal.

**Add — do not replace.** That file may already have content: `preferences`, `mcpServers` for other tools, `coworkUserFilesPath`. Overwriting it wipes what is already there. If `mcpServers` does not exist yet, add the whole key as a sibling of anything already present. If it does, add `northbridge-diligence` inside it alongside the other servers.

The block to add — with **your real paths**, not `/absolute/path/to/...`:

```jsonc
{
  "mcpServers": {
    "northbridge-diligence": {
      "command": "/Users/<user>/Applications/northbridge-diligence/.venv/bin/python",
      "args":    ["/Users/<user>/Applications/northbridge-diligence/src/server.py"],
      "env":     { "EDGAR_USER_AGENT": "Northbridge Capital Partners research@northbridge.example" }
    }
  }
}
```

Then **restart Claude Desktop** — it only reads this file at launch.

Four things that catch people out here:

- **Nobody runs `src/server.py` by hand.** It speaks MCP over *stdio*, so it waits silently on standard input — run it in a terminal and you get a cursor that never returns, which looks broken but is correct. The client launches it, the way an operating system talks to a plugged-in device.
- **Point `command` at the virtualenv's Python**, not bare `python`. The client starts the server in its own environment and will not inherit an activated venv, so bare `python` usually resolves to a system install without the dependencies.
- **Absolute paths only.** No `~`, no relative paths. The client is not running from a shell so tilde-expansion does not happen.
- **The `env` block here is separate from the `export` in step 3.** That one covered `doctor.py` in your terminal; this one covers the server as the client runs it. Both need setting, with the same value.

If the JSON is malformed — a missing comma, an unmatched bracket — Claude silently ignores the whole file. Paste it through a JSON validator before saving, or watch your editor's syntax highlighting; if the file goes red, do not restart yet.

### 6. Install the skill

```bash
cp -r skill ~/.claude/skills/company-screen
```

### 7. Confirm it works for the analyst

Have them say: **"Screen Beyond Meat for the deal team"** — or any ticker or company name. There is no command to remember; the skill triggers on the request itself.

A correct result has `[S1]`-style markers throughout and a Sources table at the bottom. **If figures appear without source markers, the skill is not being used** — check step 6.

### If something goes wrong

`doctor.py` names the fix for each failure. The three you will actually hit:

| Symptom | Cause |
|---|---|
| `403` from every SEC host | `EDGAR_USER_AGENT` unset or rejected — check the `env` block in step 5, not just the shell |
| Client silently ignores the config after you edited it | Malformed JSON (missing comma, unmatched bracket). Run the file through a JSON validator, then restart the client |
| Config disappeared after edit | The file got overwritten instead of merged — restore, then add the `mcpServers` key alongside the other keys rather than replacing them |
| Client reports the server failed to start | `command` points at a Python without the dependencies — use the venv path |
| Skill never triggers, answers come without citations | `skill/` not copied to `~/.claude/skills/` |

