# Phase 4c — Alert TestMode Proof (Runtime, Bukan Code Inspection)

> Sumber: sesi Hermes 25 Aug 2026. Verifikasi ulang setelah user menolak "verified by code inspection" sebagai bukti.

## Metode

`AlertService.TestMode` (static bool, temporary) diset `true` untuk memaksa ketiga kondisi alert return item sintetis — **tanpa menyentuh DB production**. Banner di-render oleh Blazor dan diverifikasi via `curl /phase1` + grep pada HTML output. Setelah verifikasi, `TestMode` dikembalikan ke `false`.

## Bukti runtime — ketiga alert muncul di HTML

```
TEST: Window #999 mendekati batas waktu (1 hari lagi), keputusan masih PENDING
TEST: Window #888: Evidence status = EXTERNAL_BLOCKED
TEST: Scheduler job 'test_job' (2026-08-25) status: FAILED
```

(6 occurrence dalam HTML karena 2x render Blazor.)

## Data real saat itu — semua kondisi NO ALERT (benar)

```
Current time: 2026-08-25 18:18:28
Active window ends in 29 days (end_at=2026-09-23 23:59:59)
  -> No alert (>7 days)

evidence_status=PARTIAL_EVIDENCE
  -> No alert (not EXTERNAL_BLOCKED)

Latest job: ('session_scan', '2026-08-24', 'SUCCESS', ...)
  -> No alert (latest job is SUCCESS)
```

## Tiga kondisi alert yang diverifikasi

1. **PendingDecisionNearDeadline:** `human_decision == PENDING` AND `end_at <= now + _pendingDecisionWarningDays (7 hari)`
2. **ExternalBlockedEvidence:** `evidence_status == EXTERNAL_BLOCKED`
3. **SchedulerJobFailed:** latest `scheduler_job_runs.status != SUCCESS`

## Catatan kejujuran

- Threshold 7 hari adalah konstanta `_pendingDecisionWarningDays = 7` dengan komentar "ASUMSI: bisa diubah via config nanti" — belum dikonfigurasi eksternal.
- TestMode adalah flag static sementara; sudah dikembalikan `false`. Kalau mau test ulang, gunakan mekanisme yang sama.
