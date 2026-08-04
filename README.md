# EDMC BGS Influence Tracker

Elite Dangerous Market Connector (EDMC) plugin that estimates Background Simulation (BGS) influence gains from missions and bounty redemptions, with session Discord reports for Powerplay / BGS activity.

## Credits & inspiration

This project would not exist in its present form without **[BGS-Tally](https://github.com/aussig/BGS-Tally)** by [aussig](https://github.com/aussig) and contributors.

We used BGS-Tally as a reference for:

- How a mature EDMC plugin is structured (unique package layout, prefs tab, journal hooks)
- Compact Discord / ANSI reporting patterns for faction activity (especially the “tally” style)
- Practical patterns for presenting BGS-oriented session data to squadrons in Discord

BGS-Tally remains the gold standard for full BGS activity tracking. This plugin focuses on a narrower slice (influence estimation + base bounty / exploration reporting) and is **not** affiliated with or endorsed by the BGS-Tally project. Any mistakes here are ours alone — thank you to the BGS-Tally authors for the open reference.

## Layout

| Path | Role |
|------|------|
| `load.py` | EDMC plugin entrypoint (UI, prefs hooks) |
| `bgsinf/` | Unique package (avoids colliding with other plugins) |
| `bgsinf/journal_handlers.py` | Journal event → tracker/session mapping |
| `bgsinf/edsm_client.py` | EDSM population/factions fetch + apply |
| `bgsinf/influence_model.py` | Influence estimation engine |
| `bgsinf/overlay.py` | Optional EDMC Overlay adapter |
| `bgsinf/discord_report.py` | ANSI Discord session report builder |

## Influence change estimation

The plugin does **not** read true BGS influence from the server after a tick. It **estimates**
how much influence your session actions *likely* contributed to the tracked minor faction
in the system of interest, using community-derived heuristics (SINC guide / Jane Turner /
Taipandot-style testing). Treat the result as a **rough guide**, not an exact forecast.

### What contributes to Est. Δ

| Action | When counted | Input used for estimation |
|--------|----------------|---------------------------|
| Mission completions | `MissionCompleted` with positive `FactionEffects` INF for the tracked faction | Influence string length (`+` … `+++++`, clamped 1–5) |
| Bounty voucher hand-ins | `RedeemVoucher` type bounty for the tracked faction | **Base** (face-value) credits only — see below |
| Exploration data sales | Tracked for Discord/session totals | **Not** folded into Est. Δ yet |

Only the configured **system of interest** + **minor faction** are scored. Wrong system/faction events are ignored.

### Pipeline (per scored action)

1. **Effort points** from the journal payload  
   - Missions: `0.5 × log2(n)` where `n` is the number of `+` characters (1–5)  
   - Bounties: `1.33 × log2(base_credits)` (base credits floored at 1 for the log)

2. **Diminishing returns** within the session (separate counters for missions vs bounties)  
   - Missions: divide by `1 + 0.15 × log(1 + mission_count)`  
   - Bounties: divide by `1 + 0.12 × log(1 + bounty_count)`  
   So the second and third hand-ins of the same type earn less than the first.

3. **Population factor** (larger systems move influence more slowly)  
   - Population is floored at 1 000  
   - `factor = max(0.025, 1 − log10(pop) / 10.875)`

4. **Empirical scale → estimated % points**  
   - Mission: `points × population_factor × 0.35`  
   - Bounty: `points × population_factor × 0.28`  

5. **Session total**  
   - `Est. Δ` is the sum of each action’s estimated % contribution for the session  
   - Shown on the main window and in Discord reports; reset with **Reset session totals**

### Bounty base vs Powerplay cash

The journal does **not** put base voucher value and Powerplay cash bonus on the same
`RedeemVoucher` event:

- Face value is recorded on kill-time **`Bounty`** events (`Rewards[].Reward`)
- Cash paid is on **`RedeemVoucher`** (may include ALD / other payout perks)

The plugin stacks kill-time face values as **pending base**, then on redeem:

- If cash &gt; pending → base = pending, perk bonus = cash − pending  
- If cash ≤ pending → treat as partial redeem without detectable perk  
- If no kills were tracked this session → cash is treated as base (perk unknown)

**Est. Δ and Discord “BVs” use base credits only**, so Powerplay rank payouts do not inflate the influence estimate.

### What is *not* modeled

- True post-tick INF from the galaxy (refresh EDSM/journal for current INF %)
- Exploration / cartographics contribution to Est. Δ (sold value is still reported)
- Trade, CZ, murders, and other BGS levers (use BGS-Tally for full activity coverage)
- Soft factors (states, overlapping player work, exact Frontier formula changes)

### References
- [BGS-Tally](https://github.com/aussig/BGS-Tally) — primary inspiration for Discord report style and plugin structure
- [Frontier Journal Manual v32 (PDF)](https://hosting.zaonce.net/community/journal/v32/Journal_Manual-v32.pdf)
- [EDMC Plugin Development (PLUGINS.md)](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md)

## Install (release zip)

1. Download the latest **release zip** from [Releases](https://github.com/SaltyCartharsis/EDMC_BGSInfluenceTracker/releases)
2. Unzip so you have a folder named `EDMC_BGSInfluenceTracker`
3. Place that folder in the EDMC plugins directory:
   - **Windows:** `%LOCALAPPDATA%\EDMarketConnector\plugins`
   - **macOS:** `~/Library/Application Support/EDMarketConnector/plugins`
   - **Linux:** `~/.local/share/EDMarketConnector/plugins`
4. Restart EDMC

Release artifacts contain **runtime files only** (no tests or dev tooling).

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

ruff check .
black --check .
mypy bgsinf
pytest
```

### Publishing a release

```bash
# 1. Bump __version__ in load.py if needed
# 2. Commit on main, then:
git tag v1.0.1
git push origin v1.0.1
```

That runs [`.github/workflows/release.yml`](.github/workflows/release.yml), which zips only the EDMC runtime modules and attaches them to a GitHub Release. You can also run the workflow manually from the Actions tab.

See `AGENTS.md` for testing strategy and project conventions.
