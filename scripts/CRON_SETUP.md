# Pipeline Cron Setup (Linux VM)

Schedules the ingestion pipelines to run automatically **every 6 hours**:

| Pipeline | Times (IST) | Cron hours | Runner |
|----------|-------------|-----------|--------|
| **WNI** | 07:00, 13:00, 19:00, 01:00 | `0 1,7,13,19` | `run_wni_pipeline.sh` |
| **MariApps** | 07:30, 13:30, 19:30, 01:30 | `30 1,7,13,19` | `run_mariapps_pipeline.sh` |

MariApps is offset 30 min from WNI so the two scrapers don't run at the same minute.

Also schedules the **Bunker Report** scrape, once daily (bunker deliveries
aren't time-sensitive the way noon-report data is — adjust if you want it
more frequent):

| Pipeline | Time (IST) | Cron hours | Runner |
|----------|------------|-----------|--------|
| **Bunker Report** | 02:00 | `0 2` | `run_bunker_report_scraper.sh` |

`run_mariapps_pipeline.sh` calls `backend.mariapps_pipeline.mariapps_pipeline`
directly, not `backend.main_entry` — so the Bunker Report scrape
(`bunker_report_scraper.run()`) was never actually invoked by cron before
this, only by manually running `python -m backend.main_entry`. This is a
separate script/cron line, not folded into the MariApps one, so it can be
scheduled or disabled independently and gets its own log file.

Also schedules the **Data Quality daily check** (client request 2026-10),
once daily after the 01:00/01:30 WNI+MariApps run has landed yesterday's data:

| Pipeline | Time (IST) | Cron hours | Runner |
|----------|------------|-----------|--------|
| **Data Quality check** | 02:30 | `30 2` | `run_data_quality_check.sh` |

Checks yesterday's reports (plus any older still-open finding's date, to
catch late corrections) for 3 confirmed mandatory-field gaps — missing
weather (BF Wind / Sig. Wave Height), missing CP instruction in remarks, and
zero fuel logged on a real steaming day — and emails a per-vessel digest to
`vessel_notification_recipients`. **One-time setup before the first cron
run**: `python -m import_notification_recipients` to seed the per-vessel
TO/CC lists (see that script for the source list).

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
nano scripts/run_bunker_report_scraper.sh
nano scripts/run_data_quality_check.sh

chmod +x scripts/run_wni_pipeline.sh scripts/run_mariapps_pipeline.sh scripts/run_bunker_report_scraper.sh scripts/run_data_quality_check.sh
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

./scripts/run_bunker_report_scraper.sh
tail -f logs/bunker_report_cron.log  # confirm login succeeds + bunker records scrape

python -m import_notification_recipients   # one-time, before the first data-quality run
./scripts/run_data_quality_check.sh
tail -f logs/data_quality_cron.log   # confirm "N vessels checked, M mailed"
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
0  2          * * * /opt/vessel_pipeline/scripts/run_bunker_report_scraper.sh
30 2          * * * /opt/vessel_pipeline/scripts/run_data_quality_check.sh
```

Save and exit. Confirm it registered:

```bash
crontab -l
```

### Cron expression explained
- `0  1,7,13,19 * * *` → WNI at **:00** of hours 01, 07, 13, 19 IST.
- `30 1,7,13,19 * * *` → MariApps at **:30** of the same hours (offset so the
  two scrapers never start on the same minute).
- `0  2 * * *` → Bunker Report once daily at 02:00 IST, clear of the 01:00/01:30
  WNI+MariApps run.
- `30 2 * * *` → Data Quality check once daily at 02:30 IST, after the
  01:00/01:30 WNI+MariApps run so yesterday's data has landed.

---

## 3. Verifying / operating

```bash
# See each pipeline's own log
tail -n 100 /opt/vessel_pipeline/logs/wni_cron.log
tail -n 100 /opt/vessel_pipeline/logs/mariapps_cron.log
tail -n 100 /opt/vessel_pipeline/logs/bunker_report_cron.log
tail -n 100 /opt/vessel_pipeline/logs/data_quality_cron.log

# Confirm cron fired (system cron log; path varies by distro)
grep -E 'run_wni_pipeline|run_mariapps_pipeline|run_bunker_report_scraper|run_data_quality_check' /var/log/syslog

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
