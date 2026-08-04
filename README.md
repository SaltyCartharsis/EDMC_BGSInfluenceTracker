# EDMC BGS Influence Tracker

Elite Dangerous Market Connector (EDMC) plugin that estimates Background Simulation (BGS) influence gains from missions and bounty redemptions.

## Layout

| File | Role |
|------|------|
| `load.py` | EDMC plugin entrypoint (UI, prefs) |
| `journal_handlers.py` | Pure journal event → tracker/session mapping |
| `edsm_client.py` | EDSM population/factions fetch + apply |
| `influence_model.py` | Pure influence estimation engine |
| `overlay_client.py` | Optional EDMC Overlay adapter |
| `discord_report.py` | ANSI Discord session report builder |

### Bounty vouchers vs Powerplay payout perks
The journal does **not** put base voucher value and Powerplay cash bonus on the same
`RedeemVoucher` event. Face value is on kill-time `Bounty` events; cash received is on
`RedeemVoucher`. This plugin tracks both and attributes BGS influence from **base** only.

### References
- [Frontier Journal Manual v32 (PDF)](https://hosting.zaonce.net/community/journal/v32/Journal_Manual-v32.pdf)
- [EDMC Plugin Development (PLUGINS.md)](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md)

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

ruff check .
black --check .
mypy influence_model.py journal_handlers.py edsm_client.py overlay_client.py discord_report.py
pytest
```

See `AGENTS.md` for testing strategy and project conventions.
