# EDMC BGS Influence Tracker

Elite Dangerous Market Connector (EDMC) plugin that estimates Background Simulation (BGS) influence gains from missions and bounty redemptions.

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

### Bounty vouchers vs Powerplay payout perks
The journal does **not** put base voucher value and Powerplay cash bonus on the same
`RedeemVoucher` event. Face value is on kill-time `Bounty` events; cash received is on
`RedeemVoucher`. This plugin tracks both and attributes BGS influence from **base** only.

### References
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
