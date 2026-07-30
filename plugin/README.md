# northbridge-diligence plugin

Bundles both halves of the tool — the `edgar-mcp` MCP server and the
`company-screen` skill — into one installable unit.

## Why this exists

Installed by hand, the two halves go to different places, and *which* places
depends on which Claude surface you use. Register the server with Claude Desktop
while copying the skill into Claude Code's directory and you get an install where
every check passes and the skill never fires. That happened on a real Windows
machine: `doctor.py` reported all checks green while nothing worked.

A plugin makes that failure **structurally impossible** rather than merely
documented — there is no way to install one half without the other.

## Install

```bash
/plugin marketplace add /absolute/path/to/northbridge-diligence
/plugin install northbridge-diligence
```

The plugin expects the Python package to be installed in a virtualenv at the
repository root, which is what the README's setup produces:

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
```

## Known limits, stated rather than discovered

**The bundled `.mcp.json` hardcodes a POSIX venv path.** It points at
`${CLAUDE_PLUGIN_ROOT}/../.venv/bin/edgar-mcp`, which resolves correctly when the
plugin sits inside the cloned repository — the documented layout. Two cases need a
one-line edit:

- **Windows.** Change the command to
  `${CLAUDE_PLUGIN_ROOT}/../.venv/Scripts/edgar-mcp.exe`. A single bundled config
  cannot cover both platforms, because the interpreter path differs and there is
  no conditional syntax.
- **Installed away from the repo.** If the plugin directory is copied somewhere
  else, `../.venv` no longer exists. Point `command` at the absolute path to your
  `edgar-mcp`, which `python -c "import shutil; print(shutil.which('edgar-mcp'))"`
  will print with the venv active.

**`EDGAR_USER_AGENT` is passed through from the environment**, so it must be set
where the client can see it. A GUI-launched client inherits nothing from a
terminal — set it in your shell profile, or replace `${EDGAR_USER_AGENT}` in
`.mcp.json` with the literal contact string.

**Validated against Claude Code 2.1.91.** `displayName` and `$schema` are
documented manifest fields but that version rejects them as unrecognised keys, so
they are deliberately omitted. Re-add them if you are on 2.1.143 or later and want
the nicer picker label.

## The manual path still works

Nothing here removes the hand-install route. `README.md` § Setup documents it, and
`doctor.py` recognises either.
