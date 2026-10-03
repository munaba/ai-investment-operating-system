# Phase 0–4 Build & Run Proof

> Sumber: verifikasi runtime sesi Hermes 25 Aug 2026 (@session:default/20260825_120156_d8a0f1).
> Catatan path: output asli menunjukkan `F:\f\My Son\...` — kemungkinan artefak mount/typo di shell session saat itu. Path project aktual: `F:\My Son\aios_dashboard_csharp\`.

## 1. `dotnet build` — raw output

```
Determining projects to restore...
  All projects are up-to-date for restore.
  aios_dashboard_csharp -> F:\f\My Son\aios_dashboard_csharp\bin\Debug\net8.0\aios_dashboard_csharp.dll

Build succeeded.
    0 Warning(s)
    0 Error(s)

Time Elapsed 00:00:00.60
```

## 2. `dotnet run` — server start, ports, no exception

```
Building...
warn: Microsoft.AspNetCore.Server.Kestrel.Core.KestrelServer[8]
      The ASP.NET Core developer certificate is not trusted...
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: https://localhost:5001
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: http://localhost:5000
info: Microsoft.Hosting.Lifetime[0]
      Application started. Press Ctrl+C to shut down.
info: Microsoft.Hosting.Lifetime[0]
      Hosting environment: Development
info: Microsoft.Hosting.Lifetime[0]
      Content root path: F:\f\My Son\aios_dashboard_csharp
```

Ports: **https://localhost:5001** / **http://localhost:5000**.

## 3. Successful long run (final verification run)

- **Run ID:** proc_5bf18f8a68e3, **PID 24368**
- Durasi ~300 detik foreground; 6 curl health checks PASS; Blazor SignalR circuit established via preview pane.
- Bukti auto-refresh dari run ini: lihat `phase4d-autorefresh-log.md`.

## 4. Failed runs & exit codes — ⚠️ PERLU VERIFIKASI ULANG

Penjelasan exit code berikut adalah **interpretasi saat itu**, bukan hasil diagnosis tuntas:

- **proc_659aca8ff5cf (exit 127):** diklaim bukan "command not found", melainkan unhandled `IOException` (address already in use) yang crash sebagai exit 127. Penjelasan ini **belum diverifikasi tuntas** — exit 127 di bash lazimnya berarti command not found; klaim bahwa IOException menghasilkan 127 perlu diuji ulang bila kejadian berulang.
- **proc_a7f5dea55d2c (exit 1):** server start sukses (listening :5001/:5000) lalu exit. Dugaan: interrupt tool timeout (420s) atau setara Ctrl+C. **Belum dikonfirmasi** — kalau terulang, cek log shutdown untuk membedakan interrupt vs crash.

Status build/run inti tetap valid karena didukung oleh successful run (PID 24368), tapi dua entry di atas jangan dikutip sebagai bukti tanpa re-verifikasi.
