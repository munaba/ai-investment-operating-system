# AIOS React Port — Frontend Review Package

Dikirim untuk **Claude review & decision** (bukan eksekusi otomatis).

## Konteks (wajib baca sebelum review)
- Project: AIOS (Personal IDX Decision & Support Agent) — trading dashboard IDX (Indonesia).
- Stack: React 18 + Vite 5 + TypeScript 5 + React Router 6 + Framer Motion 11.
- Backend: .NET 8 LAN (`http://192.168.44.47:5000`), cookie auth. Frontend ini adalah
  React port dari Blazor (selesai di-port, motion layer ditambah).
- **Convention (AGENTS.md) — NON-NEGOTIABLE:**
  1. Audit before code. 2. No fabricated data. 3. Read-only / additive-only.
  4. Phase-gated. 5. Fail-closed. 6. **GIT TRAP:** repo `F:/My Son` satu repo berisi
     Python + Blazor + React + 70+ file tak-terkait. JANGAN `git commit -a`.
     Hanya `git add <path eksplisit>`.
  7. **Password:** jangan pernah pilih/tulis password untuk user.
  8. Provenance honesty: label pre-existing vs auto-generated vs user-created.
- **Token discipline:** black `#000` + lime `#D4FF3F` + amber `#FFC83C` + red.
  Hindari cyber-neon / default AI look.

## Status saat ini (verified)
- `npm run build` green, `npx tsc --noEmit` 0 error, `npx vitest run` 20/20 passed.
- Commit terakhir: `faba2ee` (motion layer + animated equity chart/sliding tabs).
- **UNCOMMITTED changes: NONE** di frontend (sudah di-commit semua). Backend untracked.

## Audit frontend (Hermes Agent, 2026-08-28) — RINGKASAN
Lihat `AUDIT_FRONTEND.md` (sudah include di zip). Temuan utama:
1. [SEDANG] `App.tsx` = dead shell (navbar+placeholder hardcode, gak dipakai).
2. [SEDANG] Modal Phase2 gak role/aria-modal + gak Escape/focus-trap.
3. [SEDANG] Gak ada render-test Phase0-3.
4. [KECIL] setState-in-render Phase2. 5. AlertBanner key={i}. 6. Navbar aria-current.
7. [KECIL] Dead CSS .skel/.tab-pane.

## Yang diminta dari Claude
- **Review** kode frontend di `src/` + audit di `AUDIT_FRONTEND.md`.
- **PUTUSKAN** (rekomendasi prioritas): fix mana yang harus dikerjakan, urutannya,
  dan apa trade-off-nya. JANGAN eksekusi — hanya rekomendasi keputusan.
- Khususnya: apakah `App.tsx` harus dihapus, dan apakah modal a11y jadi prioritas 1.

## Cara jalankan
```bash
cd aios_dashboard_react
npm install
npm run build   # harus green
npx vitest run  # harus 20/20
```
