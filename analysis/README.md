# Synthetic fleet for the Santa rollout analysis

**Everything in `analysis/data/` is simulated.** No real company, device or user data is used.
The real events from my lab VMs (`analysis/real/`) were used only to shape the categories below.

## How to generate it

```bash
pip install pyyaml          # not needed by the generator; listed for the rest of the repo
python3 analysis/generate_fleet.py              # 3,000 devices, seed 42
python3 analysis/generate_fleet.py --seed 7     # a different but equally realistic fleet
```

The same seed always produces identical data, so results are reproducible.
Outputs (gitignored, because they can be regenerated):

| File | Contents |
| --- | --- |
| `data/devices.csv` | device_id, user, team |
| `data/execution_events.csv.gz` | One row per device, per week, per binary: week, device_id, user, team, category, file_name, path, sha256, signed, team_id, signing_id, count |

`count` is how many times that binary ran on that device that week. The `category` column is
ground truth for checking the analysis; a real Santa event wouldn't carry it.

## Assumptions

### Fleet
- 3,000 macOS devices, one user each, over 4 weeks.
- Team mix: Engineering 35%, Research 15%, Sales 20%, Finance 10%, Support 20%.
  (Lumen's company.md is 70% Mac; this models the Mac fleet only, since Santa is macOS-only.)

### Signed software
- **Standard build:** 8 apps on every device (Chrome, Slack, Zoom, 1Password, Outlook, Teams, Nudge, Santa).
- **Team apps:** 5–8 apps per team (e.g. VS Code and Docker for Engineering, Salesforce for Sales).
- **Common apps:** 300 apps with Zipf-like popularity (a few are on most devices, most are on few).
- **Long tail:** 4,000 rare apps from ~1,200 vendors; each device has 0–4, used about every other week.
- App names are real or generic, but **all Team IDs and hashes are synthetic** (random/derived), not the vendors' real identifiers.
- **Updates:** each signed app ships a new version (new hash, same Team ID and Signing ID) in about 12% of weeks.
  This is what makes hash rules fragile and Team ID / Signing ID rules durable.

### Hard cases (the reasons allowlisting rollouts fail)
| Category | Who | Behaviour |
| --- | --- | --- |
| `homebrew` | 92% of Engineering, 70% of Research, 3–10% of others; 4–18 tools each from a list of 40 | Unsigned (ad-hoc), no Team ID; new version in week 3 |
| `dev_build` | 65% of Engineering, 35% of Research, 2% of Support | Self-compiled in `~/go/bin`, `~/.cargo/bin`, `target/debug`; **unique to each device and rebuilt every week** (new hash every week) |
| `internal_unsigned` | 6 internal tools, mapped to the teams that use them, ~80% adoption | Unsigned; same hash fleet-wide; new release in week 3 |
| `suspicious` | 5 binaries on 1–3 devices each (8 device-binary pairs) | Unsigned, run from Downloads, /tmp or a hidden folder |

### What this doesn't model
- Scripts (Python, shell) run by interpreters: Santa evaluates the interpreter, not the script.
- Santa's own built-in allowances (Apple platform binaries are always allowed).
- Transitive/compiler rules: the analysis in Step 1B.4 applies them, the generator doesn't.
- Devices joining or leaving mid-month, or people changing teams.
- Real-world numbers: proportions are informed estimates for a fast-growing AI company, not measurements.

## Shape of the default output (seed 42)

| Category | Rows |
| --- | --- |
| standard_app | 172,784 |
| common | 89,476 |
| homebrew | 63,316 |
| internal_unsigned | 24,344 |
| rare | 11,086 |
| dev_build | 8,968 |
| suspicious | 8 |
| **Total** | **369,982** |

About 13,000 unique hashes; a median device runs ~29 distinct binaries a week.
