# AIOS L5 Scheduler Setup — Windows Task Scheduler

## Overview
`Orchestration/tick_runner.py` menjalankan satu tick scheduler (`idx_daily_scheduler.tick(now)`) secara idempoten.

## Requirements
- Python 3.11+ dengan venv aktif
- AIOS dependencies ter-install (`pip install -r requirements.txt`)
- DB `data/investment_platform.db` ter-migrasi

## Manual Test
```bash
python Orchestration/tick_runner.py --dry-run
```

## Production Setup (Windows Task Scheduler)

### 1. Buat Scheduled Task
```cmd
schtasks /Create /TN "AIOS_L5_Tick" /TR "<python> Orchestration/tick_runner.py" /SC MINUTE /MO 5 /ST 08:00 /ET 17:00 /RL HIGHEST /F
```

**Parameter:**
- `/TN "AIOS_L5_Tick"` — nama task
- `/TR "..."` — command (ganti path sesuai instalasi Anda)
- `/SC MINUTE /MO 5` — setiap 5 menit
- `/ST 08:00 /ET 17:00` — jam 08:00–17:00 (sesuaikan dengan jam bursa IDX: 09:00–16:00 WIB)
- `/RL HIGHEST` — run dengan privilege tertinggi
- `/F` — force overwrite jika task sudah ada

### 2. Verifikasi
```cmd
schtasks /Query /TN "AIOS_L5_Tick" /V /FO LIST
```

### 3. Jalankan Manual (Test)
```cmd
schtasks /Run /TN "AIOS_L5_Tick"
```

### 4. Monitor Log
Lihat output di Event Viewer → Task Scheduler → AIOS_L5_Tick history, atau redirect output ke file:
```cmd
schtasks /Create /TN "AIOS_L5_Tick" /TR "<python> Orchestration/tick_runner.py >> logs/tick_runner.log 2>&1" ...
```

### 5. Hapus Task
```cmd
schtasks /Delete /TN "AIOS_L5_Tick" /F
```

## Alternative: Python `schedule` Library
Jika Task Scheduler tidak sesuai, gunakan `schedule`:
```python
# run_scheduler_loop.py
import schedule, time
from Orchestration.tick_runner import main as tick_main

schedule.every(5).minutes.do(tick_main)
while True:
    schedule.run_pending()
    time.sleep(60)
```
Lalu jalankan di background: `nohup python run_scheduler_loop.py &` (Linux) atau `pythonw run_scheduler_loop.py` (Windows).

## Notes
- **Dry-run:** `--dry-run` tidak menonaktifkan DB write — tick() tetap commit. Gunakan DB test atau backup sebelum production.
- **Jam bursa IDX:** 09:00–16:00 WIB (UTC+7). Sesuaikan `/ST` dan `/ET` ke UTC lokal atau WIB.
- **Idempotency:** tick() aman dipanggil berulang — scheduler internal sudah cek duplikat job via `scheduler_job_runs`.
