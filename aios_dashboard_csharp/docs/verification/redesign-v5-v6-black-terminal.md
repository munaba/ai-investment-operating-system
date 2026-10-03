# Visual Redesign v5–v6 — Black Terminal (Robinhood-bold)

> Sesi: Aug 26, 2026. Murni perubahan visual/CSS/markup — `@code`,
> service, query DB, auth middleware, jalur human_decision tidak disentuh.

## Arah desain

**True-black + grayscale discipline + satu aksen lime.** Dipelajari dari
prinsip Robinhood (bukan dicopy): surface hitam pekat, satu aksen super
jenuh, serif berkarakter untuk display, kontras ekstrem. Diterjemahkan
ke konteks AIOS (trading personal IDX, human-gated, read-only).

## Palet final

| Nama | Hex | Peran |
|------|-----|-------|
| Black | `#000000` | Surface |
| Panel | `#0C0C0C` | Card/panel |
| Edge | `#232323` | Border/divider |
| White | `#FFFFFF` | Teks utama |
| Gray / Gray-dim | `#9E9E9E` / `#5A5A5A` | Sekunder/disabled |
| **Signal Lime** | `#D4FF3F` | Mesin: status OK, evidence, aksi |
| Amber Gate | `#FFC83C` | Khusus menunggu keputusan manusia |
| Red | `#FF5C5C` | Error/danger |

Bahasa warna: **lime = mesin bicara, amber = gantian manusia.**

## Tipografi

- Display/state words: **Fraunces** (serif, self-hosted woff2) — hanya di
  momen keputusan: brand wordmark, gate chain state words, judul halaman.
- Body: IBM Plex Sans. Data/angka: IBM Plex Mono (tabular-nums).

## Signature element — Gate Chain

Visualisasi alur human-gated: Brief → Journal → **Your call** → Position.
Konektor dot lime = lolos otomatis; amber berdenyut = sedang menunggu
keputusan manusia. Satu-satunya loop animation yang disengaja (state
indicator, bukan dekorasi). Diimplementasi penuh di GateStrip (sticky,
refresh 60s via InvokeAsync) dan mockup Phase 3.

## Icon system

**Lucide**, inline SVG sprite (`wwwroot/icons/_sprite.svg`, 16 ikon,
±3 KB), recolor via currentColor. Fungsional: nav labels, tab labels,
card headers, export buttons, console prompt, AlertBanner types
(MarkupString render). **Zero emoji** di UI markup (sisa ✅❌ hanya dalam
string hasil form sebagai feedback teks).

## Keputusan desain kunci

1. **Monument stats dibunuh** (audit v3: tell #6) — equity Rp 100jt 38px
   diganti data line mono 13px. Hierarki lewat type weight & whitespace.
2. **Center stack dibunuh** (tell #8) — empty state Book asimetris:
   kiri copy filosofi, kanan langkah CLI actionable dengan copy buttons.
3. **Accent rail dihapus** (tell #4) — hierarchy tanpa garis warna tempel.
4. **Ilustrasi custom di-skip dengan sengaja** — icon system + tipografi
   kuat lebih konsisten daripada ilustrasi yang berisiko generik.
5. **Motion disiplin**: clock tick (lime flash), hover indent/copy-reveal,
   amber pulse (gate manusia saja). `prefers-reduced-motion` dihormati.

## Hasil audit slop

Metode: 10 tells (claude-design Slop Diagnostic) + frontend-design
cliché check + Anti-Slop density test.

| Versi | Skor | Catatan |
|-------|------|---------|
| v3 | 6/10 | Monument stat, center stack, accent rail, default hue/type |
| v4 | 1/10 | Struktur beres; tapi masih charcoal-navy + Archivo (kurang berani) |
| v5–v6 | **1/10** | True black + lime + Fraunces; icon system konsisten; nol emoji |

Sisa 1 poin: amber pulse (disengaja — state indicator human gate).

## File terkait

- `wwwroot/css/theme.css` — theme utama
- `wwwroot/css/icons.css` — icon system + skeleton + motion utilities
- `wwwroot/fonts/` — fraunces-600/700, ibm-plex-sans-400/600, ibm-plex-mono-400/500, archivo (legacy)
- `wwwroot/icons/` — 16 SVG Lucide + `_sprite.svg`
- `wwwroot/favicon.svg` / `.png` — gate mark (2 baris lime = mesin, 1 amber = manusia)
- `Components/Layout/GateStrip.razor` — signature component

## Kualitas kode (bonus sesi ini)

Semua catch block senyap dibersihkan: Phase0 LoadTablesAsync,
Phase1 LoadSymbolsAsync + refresh_log write, Phase3 LoadAllDataAsync
(+Logger inject), AlertService, DatabaseService.TestConnectionAsync,
AlertBanner.RefreshAlertsAsync — semua kini log exception (ILogger /
Console.Error) dengan konteks. Pola
`catch (OperationCanceledException/ObjectDisposedException)` di timer
loop dibiarkan: shutdown lifecycle yang memang disengaja.
