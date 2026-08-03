# DBT Sentinel

**Impact analyzer for dbt migrations in locked-down environments.**

Compares a delivery package (ZIP from a ticket) against a corporate dbt project and produces a visual HTML assistant: what to create, what to append, dependency order, lineage, and policy warnings — without writing into the dbt repo.

Built for consultants working on restricted VDIs where `pip`, `npm`, Docker, and IDE plugins are not available.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/deps-stdlib%20only-success)](#tech-stack)
[![License](https://img.shields.io/badge/license-see%20repo-lightgrey)](#)

---

## Why it exists

Migrating SaaS-generated dbt models into a large corporate repository is error-prone:

- Packages mix **new files** with **edits to models that already exist**
- Naming differs (`stg_cliente` vs `stg_clientes`), so duplicates slip in
- Teams need a clear **create / append / do-not-touch** decision, not a blind overwrite
- Environments often block installing packages — the tool must run on **Python stdlib alone**

DBT Sentinel turns that comparison into a guided checklist and lineage view.

```text
Ticket ZIP (workspace)  +  Corporate dbt (base, read-only)
            ↓
      engine analysis
            ↓
   output/index.html  ·  session.json  ·  optional snapshot
```

---

## Features

| Capability | What you get |
|---|---|
| **Additive policy** | Prefer *create new files* and *append only new columns/refs*; never rewrite existing SQL by default |
| **Impact checklist** | Grouped by action (create / append / review) and business domain |
| **Execution order** | Topological order: source → sample → staging → intermediate → dim/fact → aggregate |
| **Interactive lineage** | Layer lanes with SVG edges that **fan out** when one model feeds many |
| **Rename detection** | Fuzzy matching + aliases to flag “same object, different name” |
| **Taxonomy checks** | Naming and column-prefix conventions (F / DIB / AGGR, `id_`, `nm_`, …) |
| **Sources awareness** | Warns when `source('…')` is used but missing from `sources.yml` |
| **Final verification** | On finalize, re-scans the base and reports created / appended / missing / partial |
| **Hardened I/O** | Writes only under `output/` and `snapshots/`; path traversal guards; HTML escaping |

---

## Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Runtime | Python 3 (stdlib) | No `pip` / venv required on locked VDIs |
| UI | Single-file HTML + CSS + JS | Open locally; no build step |
| Parsing | Regex / lightweight YAML | Fast structural scan of `.sql` / `.yml` |
| Persistence | JSON session + snapshots | Audit trail per ticket |

Zero third-party Python packages. Zero frontend bundler.

---

## Quick start

```bash
git clone https://github.com/J034ll4n/dbt-sentinel.git
cd dbt-sentinel
```

1. Edit `config.json` — point `base_project_path` at your dbt root (read-only) and put the ticket extract under `workspace/`.
2. Run:

```bash
py -3 main.py
```

3. Open `output/index.html` and follow the **Assistente** / **Ordem** / **Lineage** tabs.

### Demo fixtures

This repo includes a small sample base under `demo_base/` and a helper script:

```bash
py -3 run_demo.py
```

Then open `output/index.html` to explore create/append actions and fan-out lineage without a corporate repo.

### Tests

```bash
py -3 tests.py
```

---

## Configuration (overview)

```json
{
  "base_project_path": "path/to/dbt-root",
  "base_include": ["domain_a", "domain_b"],
  "workspace_path": "workspace",
  "output_path": "output",
  "snapshots_path": "snapshots",
  "card_id": "TICKET-123",
  "add_only": true,
  "enforce_taxonomy": true,
  "detect_removed": false,
  "match_threshold": 0.62
}
```

| Key | Role |
|---|---|
| `base_project_path` | Corporate dbt root (**never modified**) |
| `base_include` | Optional domain folders to scope the scan |
| `workspace_path` | Extracted ticket / ZIP contents |
| `add_only` | Additive policy (create + append-only) |
| `enforce_taxonomy` | Corporate naming / type heuristics |
| `card_id` | Label for the HTML report and snapshot |

Day-to-day consultant steps live in [`GUIA_DE_USO.md`](GUIA_DE_USO.md).

---

## Architecture

```text
┌─────────────┐     ┌──────────────────────────┐     ┌─────────────────┐
│  config.json│────▶│  main.py (CLI + safety)  │────▶│ output/index.html│
└─────────────┘     └────────────┬─────────────┘     │ session.json     │
                                 │                   │ snapshots/       │
                    ┌────────────▼─────────────┐     └─────────────────┘
                    │  engine.py               │
                    │  · scan & parse SQL/YAML │
                    │  · diff + policy buckets │
                    │  · graph / topo / lineage│
                    │  · validate + verify     │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  ui.py → self-contained  │
                    │  HTML report             │
                    └──────────────────────────┘
```

---

## Design principles

1. **Read-only on the corporate tree** — analysis never patches production models.
2. **Policy over diff spam** — surface *what to add*, not every line of SQL churn.
3. **Works offline under IT lockdown** — stdlib + static HTML only.
4. **Consultant-speed UX** — tabs for assistant, order, files, lineage, alerts.
5. **Verifiable close-out** — re-check the base before snapshotting a ticket as done.

---

## What it is not

- Not a replacement for `dbt run` / `dbt test`
- Not a BigQuery or SaaS validator
- Not an auto-merger into the corporate repository

It is a **decision and impact layer** before you touch the real project.

---

## Project layout

```text
main.py          CLI entry, git integrity checks, snapshot + verification
engine.py        Parsing, matching, policy, graph, lineage, validate/verify
ui.py            HTML/CSS/JS report generator
tests.py         Stdlib test suite
config.json      Runtime paths and policy flags
run_demo.py      Generate report against demo_base/
demo_base/       Sample corporate-like dbt tree
GUIA_DE_USO.md   Short operator checklist (PT)
```

---

## Author

Built as a practical tool for dbt migration work under enterprise constraints — and as a portfolio piece showing end-to-end product thinking: problem framing, constrained engineering, UX for non-experts, and safety around production codebases.

Repository: [github.com/J034ll4n/dbt-sentinel](https://github.com/J034ll4n/dbt-sentinel)
