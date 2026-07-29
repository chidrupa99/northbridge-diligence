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

### 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set the SEC contact header

```bash
export EDGAR_USER_AGENT="Northbridge Capital Partners research@northbridge.example"
```

### 3. Verify — before wiring anything into a client

```bash
python scripts/doctor.py
```

Nine checks: Python version, dependencies, the contact header, reachability of each SEC host separately, a live screen of a real company, the 8 registered tools, and the skill's frontmatter. Every failure prints its fix. Exit code is 0 only when all pass, so it can gate a rollout.

Do this **before** step 4. Otherwise a broken install first appears as a skill that silently returns nothing inside a Claude conversation — the worst possible place to debug it.

### 4. Register with the Claude client

```jsonc
{
  "mcpServers": {
    "northbridge-diligence": {
      "command": "/absolute/path/to/northbridge-diligence/.venv/bin/python",
      "args": ["/absolute/path/to/northbridge-diligence/src/server.py"],
      "env": { "EDGAR_USER_AGENT": "Northbridge Capital Partners research@northbridge.example" }
    }
  }
}
```

Two things that catch people out:

- **Nobody runs `src/server.py` by hand.** It speaks MCP over *stdio*, so it waits silently on standard input — run it in a terminal and you get a cursor that never returns, which looks broken but is correct. The client launches it, the way an operating system talks to a plugged-in device.
- **Point `command` at the virtualenv's Python**, not bare `python`. The client starts the server in its own environment and will not inherit an activated venv, so bare `python` usually resolves to a system install without the dependencies.

The `env` block is separate from the `export` in step 2. That one covers `doctor.py`; this one covers the server as the client runs it. Both need setting.

### 5. Install the skill

```bash
cp -r skill ~/.claude/skills/company-screen
```

### 6. Confirm it works for the analyst

Have them say: **"Screen Beyond Meat for the deal team"** — or any ticker or company name. There is no command to remember; the skill triggers on the request itself.

A correct result has `[S1]`-style markers throughout and a Sources table at the bottom. **If figures appear without source markers, the skill is not being used** — check step 5.

### If something goes wrong

`doctor.py` names the fix for each failure. The three you will actually hit:

| Symptom | Cause |
|---|---|
| `403` from every SEC host | `EDGAR_USER_AGENT` unset or rejected — check the `env` block in step 4, not just the shell |
| Client reports the server failed to start | `command` points at a Python without the dependencies — use the venv path |
| Skill never triggers, answers come without citations | `skill/` not copied to `~/.claude/skills/` |

