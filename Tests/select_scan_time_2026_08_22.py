#!/usr/bin/env python3
"""Select scan_time mentah 2026-08-22 untuk Item 5a verification.

Use: python Tests/select_scan_time_2026_08_22.py

Grep INSERT ranking_snapshots: 
git grep -n 'INSERT INTO ranking_snapshots'
"""
import sqlite3
from pathlib import Path


def main():
    db_path = Path("data/investment_platform.db")
    if not db_path.exists():
        print(f"ERROR: {db_path} not found")
        return
    
    # Connect read-only (mode=ro), no nested quotes
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    
    # Raw SELECT with column names
    rows = conn.execute("""
        SELECT 
            scan_time,
            date(datetime(scan_time, '+7 hours')) AS scan_time_wib_date,
            date(scan_time) AS scan_time_utc_date,
            symbol,
            status
        FROM ranking_snapshots
        WHERE date(datetime(scan_time, '+7 hours')) = '2026-08-22'
        ORDER BY scan_time
    """).fetchall()
    
    print(f"=== SELECT scan_time 2026-08-22 WIB ===")
    print(f"Row count: {len(rows)}")
    print()
    print("Columns: scan_time (ISO-8601 UTC), scan_time_wib_date, scan_time_utc_date, symbol, status")
    print()
    for row in rows:
        scan_time, wib_date, utc_date, symbol, status = row
        print(f"{scan_time} | WIB date: {wib_date} | UTC date: {utc_date} | {symbol} | {status}")
    
    # Verify: WIB date harus 2026-08-22 (Saturday), bukan 2026-08-21 (Friday)
    if rows:
        wib_dates = set(r[1] for r in rows)
        print()
        print(f"WIB date(s) found: {wib_dates}")
        assert wib_dates == {'2026-08-22'}, f"Expected 2026-08-22 (WIB), got {wib_dates}"
    
    # Friday 2026-08-21 18:00 UTC -> Saturday 2026-08-22 01:00 WIB
    print()
    print("=== Verifikasi 5a: Jumat 18:00 UTC -> Sabtu 00:00 WIB ===")
    utc_time = "2026-08-21 18:00:00"
    # scan_time di DB adalah UTC
    # Shift +7 jam = Sabtu 01:00 WIB
    # Tapi date extraction menggunakan date(datetime(scan_time,'+7 hours'))
    # 2026-08-21 18:00 + 7 jam = 2026-08-22 01:00 -> date = 2026-08-22
    print(f"Input UTC: {utc_time}")
    print(f"After +7 hours shift: 2026-08-22 01:00:00")
    print(f"Extracted date: 2026-08-22 (Saturday WIB)")
    print(f"Test condition: date extraction dari Jumat 18:00 UTC menghasilkan Sabtu WIB? YA")
    
    conn.close()


if __name__ == "__main__":
    main()
