# DESIGN_LOG — Catatan Keputusan Desain

File ini mencatat keputusan desain/ubah tata letak yang **tidak berasal
dari temuan audit**. Tujuannya: kalau suatu commit dicek dan dicocokkan ke
file audit, jelas dari mana asalnya — jangan sampai "audit bilang tidak
perlu" tapi halamannya berubah, tanpa penjelasan.

Format: satu entri per keputusan. Wajib menyebut alasan dan sumber
(acuan audit atau keputusan pemilik produk).

---

## 2026-09-10 — Signature layout fixes: arc, profil, atlas, materi

**Commit:** `83f9f28` (arc), `591e301` (profil), `0d0289a` (atlas),
`9bec8d3` (materi)

### Status

Ini adalah **keputusan desain konsistensi lintas halaman**, bukan hasil
audit ANTISLOP.

> Signature layout fixes arc/profil/atlas/materi (`83f9f28`, `591e301`,
> `0d0289a`, `9bec8d3`) adalah keputusan desain konsistensi lintas
> halaman, bukan hasil audit ANTISLOP — audit sumber menyatakan 4 halaman
> ini sudah bersih (skor <1.2/10) sebelum perubahan.

### Bukti dari audit sumber

`_AUDIT_ANTISLOP.md` menyatakan eksplisit di baris 303:

> Tidak perlu: `arc`, `atlas`, `jejak`, `profil`, dan seluruh React —
> sudah di bawah 2.0.

Skor per halaman di audit yang sama (baris 11-22):

| Halaman | Skor | Verdict audit |
|---|---|---|
| `aios-arc.html` | 1.0 / 10 | Bersih |
| `aios-atlas.html` | 1.2 / 10 | Bersih |
| `aios-profil.html` | 0.5 / 10 | Pristine — referensi anti-slop |
| `aios-materi.html` | 2.8 / 10 | Rendah |

Untuk arc (baris 75), atlas (baris 91), dan profil (baris 251), audit
menulis **"Rewrite suggestion: Tidak perlu"** / "Tidak ada".

### Mengapa tetap diubah kalau audit bilang tidak perlu

Dua sumber acuan yang **berbeda**, dan keduanya sah:

1. **`_AUDIT_ANTISLOP.md`** menilai *keaslian konten* (slop: template,
   filler, halusinasi). Di audit ini 4 halaman di atas bersih.
2. **`_AUDIT_DESIGN.md` §7** menilai *signature visual* — apakah tiap
   halaman punya elemen identitas yang khas, bukan grid generik. Checklist
   §7 (baris 386-393) memuat rekomendasi untuk ke-6 halaman, termasuk 4
   yang bersih secara ANTISLOP.

Jadi "bersih dari slop" **bukan** berarti "tidak punya signature".
Keduanya dinilai dengan rubrik berbeda — perubahan ini mengikuti §7
DESIGN, bukan temuan ANTISLOP.

Keputusan mengikuti §7 apa adanya diambil oleh pemilik produk
(2026-09-10), dengan Ikhtisar tetap dikecualikan (BLOCKED, replatform).

### Yang dikerjakan

| Halaman | Perubahan | Pola yang diganti |
|---|---|---|
| Arc | tabs → lens rail vertikal + brief ledger penuh lebar | pill row horizontal |
| Profil | 5 keputusan → manifesto wall nomor 6rem di gutter | `repeat(3,1fr)` + 5× `shead` identik |
| Atlas | 11 towers → peta absolut constellation | `repeat(3,1fr)` ×2 |
| Materi | 8 devices → loom hero 620px + strip vertikal 108px | `repeat(4,1fr)` + `auto-fill 108px` |

(Atrium `37709f0` dan Jejak `b9263ca` berada di batch yang sama, tapi
keduanya **memang** punya temuan di `_AUDIT_ANTISLOP.md` — atrium skor
3.0/10 dengan pelanggaran "3 equal cards"; jejak skor 0.8/10. Keduanya
tidak masuk entri ini.)

### Cara membaca kalau menemukan commit ini di masa depan

- Jangan mencari pasangan temuan ANTISLOP untuk 4 commit ini — tidak ada.
- Yang menjadi acuan adalah `_AUDIT_DESIGN.md` §7 baris 386-393.
- Bila ingin mengembalikan ke kondisi sebelum perubahan, revert 4 hash di
  atas; audit ANTISLOP tidak akan terdampak karena skor ke-4 halaman
  tidak bersumber dari perubahan ini.

---

## 2026-09-11 — Revert Jejak ke grid 3 kolom (TASK 5)

Jejak dikecualikan dari keputusan design arc/profil/atlas/materi, direvert kembali ke grid 3 kolom karena audit ANTISLOP menyatakan "Pristine — paling kuat anti-slop" (skor 0.8/10).

- `git revert e187bca --no-edit` → `b16c348`, `git revert b9263ca --no-edit` → `900dd54` (tanpa conflict; histori utuh).
- Verifikasi: `git diff b9263ca^ -- aios-jejak.html aios_dashboard_react/public/static/jejak.html` = 0 baris; byte-identical setelah `tr -d '\r'` (SOURCE+MIRROR); `receipt` 0 hit; grid kembali `repeat(3,1fr)`.
