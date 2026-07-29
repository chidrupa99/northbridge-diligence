# Submission map

**Chidrupa Mamunooru** · PressW Delivery Engineer take-home

Where each item the brief asks for lives.

| # | The brief asks for | Where it is |
|---|---|---|
| **1** | The MCP server code, runnable, with setup instructions | [`src/`](src/) — `edgar_client.py` (all logic), `server.py` (MCP shim, 8 tools).<br>Setup: [README § Setup](README.md#setup). Full deployment guide: [DEPLOYMENT.md](DEPLOYMENT.md) |
| **2** | The skill, with its trigger and instructions | [`skill/SKILL.md`](skill/SKILL.md) — trigger in the YAML frontmatter `description`; workflow and memo template in the body |
| **3** | A short README: tools built and why, what was left out, where the seams are | [`README.md`](README.md) — § The tools, § Design decisions & seams |
| **4** | One sample output against a real public company | [`samples/`](samples/) — **two** provided, see below |
| **5** | A few sentences on what you'd build next | [README § What I'd build next](README.md#what-id-build-next-another-week) |

## On item 4 — two samples, not one

The brief asks for one. A second is included because one company cannot show that
the tool discriminates.

- **[Beyond Meat](samples/BYND_screening_memo.md)** — the distress case. Five
  flags fire. Demonstrates the tool catching a *profit mirage*: FY2025 net income
  is **+$219M** while the operating business lost **−$334M**, and it names the
  ~$553M of non-operating profit rather than reporting "profitable".
- **[Target](samples/TGT_screening_memo.md)** — the healthy case. Solvency flags
  stay silent. The one flag that does fire (`LIQUIDITY`, current ratio 0.94) is
  shown to be an artefact of a global threshold applied to a retailer, not a
  finding — which is a stated seam doing its job in public.

Each is provided as Markdown and as a self-contained HTML one-pager.

## Supporting evidence (not asked for, included as proof)

| | |
|---|---|
| [`tests/`](tests/) | 67 offline tests plus a golden-set regression, ~1s, no network. Named after the failure modes they prevent |
| [`scripts/doctor.py`](scripts/doctor.py) | Install verification — 10 live checks, each printing its own fix |
| [`DEVELOPING.md`](DEVELOPING.md) | Engineer handoff: test harness, fixtures, tuning knobs, 11 invariants, gotchas |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Client-side install: security posture, egress requirements, troubleshooting |
| [`docs/PRD.md`](docs/PRD.md) | Product framing: problem, requirements, roadmap |
| [`docs/architecture_flow.png`](docs/architecture_flow.png) | System diagram (Mermaid source and an HTML viewer alongside) |

## The one-line version

Ratios, the judgment of whether a ratio is *meaningful*, and every red flag are
computed in Python — not decided in the prompt. Two analysts running the same
screen get byte-identical flags, which is a property a prompt cannot have. The
skill's job is to select and narrate, which is the part a language model should
actually do.

## Quickest way to evaluate this

```bash
git clone https://github.com/chidrupa99/northbridge-diligence.git
cd northbridge-diligence
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
export EDGAR_USER_AGENT="Your Org you@example.com"
python scripts/doctor.py
```

Ten green lines and it works on your machine. Then read
[`samples/BYND_screening_memo.md`](samples/BYND_screening_memo.md) — it shows the
argument faster than the README does.
