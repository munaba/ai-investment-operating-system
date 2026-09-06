# Read-Only Enforcement Proof

> Sumber: sesi Hermes 25 Aug 2026 (@session:default/20260825_120156_d8a0f1).
> DB: `F:\My Son\data\investment_platform.db`

## Tes yang dijalankan

Koneksi SQLite dengan `file:...?mode=ro` (URI mode), lalu:

```python
import sqlite3
conn = sqlite3.connect(r'file:F:\My Son\data\investment_platform.db?mode=ro', uri=True)
c = conn.cursor()
c.execute('SELECT 1')
print('SELECT ok:', c.fetchone()[0])
# INSERT test follows...
```

## Output persis

```
SELECT ok: 1
INSERT failed: attempt to write a readonly database
```

## Interpretasi

- **SELECT** berhasil → koneksi read-only valid dan data terbaca.
- **INSERT** gagal dengan pesan persis `attempt to write a readonly database` (SQLite OperationalError) → write diblokir di layer native SQLite, bukan cuma di level aplikasi C#.

## Lapisan guard lain (implementasi, bukan output runtime)

- EF Core `DbContext` di project meng-override `SaveChanges`/`SaveChangesAsync` untuk throw `InvalidOperationException` ("Read-only context") — defense in depth di samping `Mode=ReadOnly` pada connection string.
