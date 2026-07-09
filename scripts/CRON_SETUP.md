# Pipeline Cron Setup (Linux VM)

Schedules the ingestion pipelines to run automatically **every 6 hours**:

| Pipeline | Times (IST) | Cron hours | Runner |
|----------|-------------|-----------|--------|
| **WNI** | 07:00, 13:00, 19:00, 01:00 | `0 1,7,13,19` | `run_wni_pipeline.sh` |
| **MariApps** | 07:30, 13:30, 19:30, 01:30 | `30 1,7,13,19` | `run_mariapps_pipeline.sh` |

MariApps is offset 30 min from WNI so the two scrapers don't run at the same minute.

> **MariApps requires MFA-disabled SSO.** The automated login signs in with
> `MARIAPPS_USERNAME` / `MARIAPPS_PASSWORD` (Microsoft SSO). That account **must
> have MFA/2FA turned off** or the headless login cannot complete and the run
> aborts cleanly (it will not hang). Set both values in `.env`.

---

## 1. One-time setup on the VM

```bash
cd /opt/vessel_pipeline          # <-- your checkout path
git pull                         # pull these new files

# point the runners at your checkout (edit PROJECT_DIR at the top if not /opt/vessel_pipeline)
nano scripts/run_wni_pipeline.sh
nano scripts/run_mariapps_pipeline.sh

chmod +x scripts/run_wni_pipeline.sh scripts/run_mariapps_pipeline.sh
```

For MariApps, make sure `.env` has the MFA-disabled SSO credentials:

```bash
# in /opt/vessel_pipeline/.env
MARIAPPS_USERNAME=pms@ozellar.com
MARIAPPS_PASSWORD=<the rotated password>
```

Test each once by hand before scheduling:

```bash
./scripts/run_wni_pipeline.sh
tail -f logs/wni_cron.log            # watch it; Ctrl-C to stop watching

./scripts/run_mariapps_pipeline.sh
tail -f logs/mariapps_cron.log       # confirm login succeeds + vessels scrape
```

---

## 2. Install the cron job

Open the crontab for the user that owns the checkout:

```bash
crontab -e
```

Add these two lines (the `CRON_TZ` line makes the schedule IST regardless of
the server's own timezone — requires Vixie/standard cron, which Ubuntu uses):

```cron
CRON_TZ=Asia/Kolkata
0  1,7,13,19 * * * /opt/vessel_pipeline/scripts/run_wni_pipeline.sh
30 1,7,13,19 * * * /opt/vessel_pipeline/scripts/run_mariapps_pipeline.sh
```

Save and exit. Confirm it registered:

```bash
crontab -l
```

### Cron expression explained
- `0  1,7,13,19 * * *` → WNI at **:00** of hours 01, 07, 13, 19 IST.
- `30 1,7,13,19 * * *` → MariApps at **:30** of the same hours (offset so the
  two scrapers never start on the same minute).

---

## 3. Verifying / operating

```bash
# See each pipeline's own log
tail -n 100 /opt/vessel_pipeline/logs/wni_cron.log
tail -n 100 /opt/vessel_pipeline/logs/mariapps_cron.log

# Confirm cron fired (system cron log; path varies by distro)
grep -E 'run_wni_pipeline|run_mariapps_pipeline' /var/log/syslog

# Temporarily disable one: comment out its line in `crontab -e`
```

Notes:
- Each runner uses `flock`, so if a run overruns 6 hours the next run is
  skipped instead of stacking.
- New WNI rows automatically populate the `wnix_` expanded columns — the
  pipeline runs the current `expander` code and the API reads the DB live, so
  **no API restart is needed** after a cron run.
- Vessel lists are read from the `vessels` table — WNI uses `wni_enabled = true`,
  MariApps uses `mari_enabled = true` (not `vessels.txt` / hardcoded lists).
- MariApps re-runs the automated SSO login on every run (fresh `auth.json`). If
  the SSO account's MFA is ever re-enabled, the run aborts cleanly and logs an
  error — it will not hang.
