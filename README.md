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
| Mission completions | `MissionCompleted` with positive `FactionEffects` INF for the tracked faction | Influence tier 1–5 from `+`…`+++++` |
| Bounty voucher hand-ins | `RedeemVoucher` type bounty | **Base** face-value credits only |
| Combat bonds | `RedeemVoucher` type CombatBond | Bond credit amount |
| Trade profit | `MarketSell` at a station controlled by the tracked faction | `TotalSale − Count×AvgPricePaid` (profit &gt; 0) |
| Exploration data sales | Cartographics sales | Reported only — **not** in Est. Δ yet |

Only the configured **system of interest** + **minor faction** are scored.

### Pipeline (per scored action)

1. **Effort points** from the journal payload  
   - Missions: `0.5 × log2(tier)` (tier 1–5)  
   - Bounties: `1.33 × log2(base_credits)`  
   - Combat bonds: `1.15 × log2(credits)`  
   - Trade profit: `1.1 × log2(profit)`

2. **Diminishing returns** within the session (per activity type)  
   - Missions / bounties / bonds / trade each have their own counter and mild log decay

3. **Population factor** (larger systems move influence more slowly)  
   - Population floored at 1 000  
   - `factor = max(0.025, 1 − log10(pop) / 10.875)`

4. **Competition / other-CMDR proxy** (heuristic only)  
   - We cannot see other players’ actions  
   - System proxy: more minor factions + higher population → softer base  
   - **Settings — same-faction allies (`A`)** and **opposing players (`O`)**  
     (counts of other active CMDRs; you are not included):  
     player-side multiplier `= (1 + A) / (1 + O)`  
     Assumes similar effort per CMDR. Allies raise faction-side Est. Δ; opponents lower it.  
   - Combined: `competition = clamp(system_part × player_share, 0.15 … 4.0)`  
   - Changing A/O recomputes Est. Δ for the whole session  
   - Optional: uncheck *Include estimated influence Δ* to omit Est from Discord reports

5. **Empirical scale → estimated % points** (after pop × competition)  
   - Mission: `× 0.35`  
   - Bounty: `× 0.12` (intentionally lower than missions — BVs were over-valued)  
   - Combat bond: `× 0.14`  
   - Trade profit: `× 0.16`

6. **Session total**  
   - `Est. Δ` sums each action’s estimated % for the session  

### Mission INF reporting (BGS-Tally style)

Discord/UI report mission influence as total units and per-tier counts, not “N missions”:

```text
INF +7 (1×2 2×1 3×1)
```

Total `+7` = Σ(tier × count). Arabic tiers 1–5 match `+` … `+++++`.

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
