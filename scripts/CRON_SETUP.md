# WNI Pipeline — Cron Setup (Linux VM)

Schedules the **WNI (Weathernews)** ingestion pipeline to run automatically
**every 6 hours, starting 07:00 IST** → runs at **07:00, 13:00, 19:00, 01:00 IST**.

> MariApps is **not** scheduled — its login uses SSO/MFA, which cannot be
> completed headlessly on the VM. Keep running MariApps manually (tmux) until
> a non-interactive login (service account / app password) is available.

---

## 1. One-time setup on the VM

```bash
cd /opt/vessel_pipeline          # <-- your checkout path
git pull                         # pull these new files

# point the runner at your checkout (edit PROJECT_DIR at the top if not /opt/vessel_pipeline)
nano scripts/run_wni_pipeline.sh

chmod +x scripts/run_wni_pipeline.sh
```

Test it once by hand before scheduling:

```bash
./scripts/run_wni_pipeline.sh
tail -f logs/wni_cron.log        # watch it; Ctrl-C to stop watching
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
0 1,7,13,19 * * * /opt/vessel_pipeline/scripts/run_wni_pipeline.sh
```

Save and exit. Confirm it registered:

```bash
crontab -l
```

### Cron expression explained
`0 1,7,13,19 * * *` → at minute 0 of hours 01, 07, 13, 19 — i.e. every 6 hours
anchored at 07:00 IST.

---

## 3. Verifying / operating

```bash
# See the pipeline's own log
tail -n 100 /opt/vessel_pipeline/logs/wni_cron.log

# Confirm cron fired (system cron log; path varies by distro)
grep run_wni_pipeline /var/log/syslog

# Temporarily disable: comment out the line in `crontab -e`
```

Notes:
- The runner uses `flock`, so if one run overruns 6 hours the next run is
  skipped instead of stacking.
- New WNI rows automatically populate the `wnix_` expanded columns — the
  pipeline process runs the current `expander` code, and the API reads the DB
  live, so **no API restart is needed** after a cron run.
- The vessel list is now read from the `vessels` table (`wni_enabled = true`),
  not `vessels.txt`.
