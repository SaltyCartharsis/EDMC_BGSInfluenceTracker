# Project Rules for Grok Build

## Safety & Permissions
- Do not touch '.env', secrets, or credential files.
- Prefer Plan Mode for any structural or multi-file changes.
- Ask before running destructive shell commands or external network calls that mutate state.
- Do not commit secrets or real player journals; use synthetic fixtures only.

## Tech Stack
- Language: Python
- Package manager: pip / pacman (or uv for dev workflows)
- Testing: pytest (optional: pytest-cov)
- Linting/Formatting: ruff + black
- Typing: mypy (or pyright); strict first on pure modules
- Optional: pre-commit, GitHub Actions CI

## Architecture (testability)
This is a small **EDMC plugin**, not a multi-package app. Prefer:

| Module | Role | Test approach |
|--------|------|----------------|
| `bgsinf/influence_model.py` | Pure BGS math / `TrackerState` | Unit tests (highest value) |
| `bgsinf/journal_handlers.py` | Pure journal → state mapping | Fixture-based unit tests |
| `bgsinf/edsm_client.py` | EDSM fetch + apply | Mocked `http_get`; no live network |
| `bgsinf/overlay.py` | Optional overlay adapter | Thin unit tests with mocks |
| `bgsinf/discord_report.py` | Discord ANSI report | Unit tests |
| `load.py` | EDMC glue, Tk UI, prefs | Host-only; thin wrappers |

- Put all pure code under the unique package **`bgsinf/`** (like BGS-Tally's `bgstally/`).
  Never use generic top-level module names (`overlay_client`, `widgets`, `utils`) — EDMC
  shares one import namespace across plugins and collisions disable loading.
- Keep host/UI only in `load.py`.
- Journal event shapes: Frontier [Journal Manual v32](https://hosting.zaonce.net/community/journal/v32/Journal_Manual-v32.pdf).
- EDMC plugin hooks/API: [EDCD PLUGINS.md](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md).
- Dev deps (`requirements-dev.txt` / `pyproject.toml`) stay separate so the plugin folder remains drop-in for EDMC.

## Coding Standards
- Prefer clear, explicit code over cleverness.
- Use type hints / strong typing everywhere.
- Prefer 'const' / immutable patterns where practical.
- Keep functions small and focused.
- Never introduce breaking changes to public APIs without discussion.

## Testing Strategy

### 1. Unit tests — `influence_model.py` (priority 1)
Pure stdlib; no EDMC, no network. Cover:
- `mission_points`: `"+"`, `"++"`, spaces, empty, clamp at 5
- `bounty_points`: known credits → points; edge cases (`0`, large)
- `population_factor`: floor at 1000 pop, min factor 0.025, decreases with population
- `add_mission` / `add_bounty`: same system+faction only; mismatch → `None`
- Diminishing returns: later actions earn less than the first for the same inputs
- Totals: `total_points`, `total_est_delta`, `bucket_counts`
- `reset_session`: clears actions/totals/counts; keeps system/faction/population

Use pytest + `assert` / `pytest.approx` for floats. Table-driven cases preferred.
Optional: golden numbers from community formula tables so tweaks show as intentional diffs.
Aim for high coverage on this module (~100%).

### 2. Journal / handler tests (priority 2)
Logic lives in `journal_handlers.process_journal_entry` (pure). `load.py` only notifies/UI-updates.

Cover synthetic journal fixtures under `tests/fixtures/journal/` (manual-aligned):
- `FSDJump` / `Location` / `CarrierJump` — population, factions, influence
- `MissionCompleted` — `FactionEffects` / `Influence` (`+` and non-matching faction)
- `Bounty` (kill) — face-value `Rewards[]` / skimmer `Reward` → pending base stack
- `RedeemVoucher` type bounty — cash; split base vs Powerplay perk using pending kills

### Bounty base vs Powerplay cash (important)
Official Journal Manual (v32/v34) **does not** document separate base vs Powerplay
perk fields on `RedeemVoucher`. Documented fields are Type, Amount (net cash after
broker fee), BrokerPercentage, and Factions[{Faction,Amount}].

Reliable split:
- **Base (face value):** kill-time `Bounty` events (`Rewards[].Reward` / skimmer `Reward`)
- **Cash paid:** `RedeemVoucher` `Factions[].Amount` (may include ALD/etc. payout bonus)
- **Implied perk bonus:** cash − pending base when kills were tracked this session

BGS influence estimates use **base credits only**. Without prior `Bounty` awards in
session, cash is treated as base (bonus unknown).

### 3. Overlay client (low effort)
- No `edmcoverlay` → `available is False`, `send` no-ops
- Mock client → `send` forwards kwargs
- Client raises → swallowed (current design)

### 4. Network — `edsm_client` (mock only)
Logic in `edsm_client.fetch_edsm_system` / `apply_edsm_system_data`. Inject `http_get` or mock `requests.get`. Never hit EDSM in unit CI.
- Happy path merges factions + population
- Timeout/HTTP error → empty default dict
- `apply_edsm_system_data` updates tracker system/pop/tracked faction influence

### 5. Do not automate early
- Full EDMC GUI / prefs (needs real EDMC + Tk)
- Live Overlay process
- Live EDSM (flaky, rate limits)
- Full end-to-end game journal replay (fixtures first)

### Manual smoke (when UI/journal paths change)
Load in EDMC → set system/faction → jump → mission complete / bounty redeem → check status line, overlay (if present), CSV export.

## Tooling

### Core
| Tool | Role |
|------|------|
| pytest | Unit/handler tests under `tests/` |
| ruff | Lint + import sort |
| black | Format (share line length with ruff) |
| mypy / pyright | Types; start with `influence_model.py` + `overlay_client.py` |

### Optional
| Tool | Role |
|------|------|
| pre-commit | black/ruff/mypy on commit |
| pip-tools or uv + `requirements-dev.txt` | Pin dev deps |
| GitHub Actions | ruff + black --check + pytest on push/PR |
| pytest-cov | Coverage; prioritize `influence_model.py` |

### Not a good fit yet
- Hypothesis (unless formal formula invariants)
- Tox/nox multi-version matrix (match EDMC’s Python)
- Selenium / Tk GUI frameworks

### Suggested layout
```text
influence_model.py
journal_handlers.py
edsm_client.py
overlay_client.py
load.py
tests/
  test_influence_model.py
  test_journal_handlers.py
  test_edsm_client.py
  test_overlay_client.py
  fixtures/journal/
pyproject.toml
requirements-dev.txt
```

### Automated gate (CI / local)
```bash
ruff check .
black --check .
mypy bgsinf
pytest
```

## Build, Test & Verification (mandatory)
Before declaring any non-trivial work done:
1. Run the linter/formatter (`ruff`, `black`)
2. Run the full test suite (`pytest`)
3. Manually smoke-test the changed path if UI/journal/overlay/EDSM paths were touched

### Implementation priority
1. pytest on `influence_model.py` — done
2. ruff + black — done
3. Extract pure journal handlers + fixture tests — done
4. mypy on pure modules — ongoing
5. EDSM mocks — done
6. pre-commit + CI once local commands are stable

## Git Discipline
- Conventional Commits
- Feature branches only ('feature/', 'fix/', 'chore/')
- Never force-push to main/master
- Squash-merge preferred
