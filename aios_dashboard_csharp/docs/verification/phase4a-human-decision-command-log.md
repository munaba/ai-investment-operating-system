# Phase 4a — Human Decision CLI Command Log

> Sumber: sesi Hermes 25 Aug 2026. Implementasi di `Services/HumanDecisionService.cs` — C# TIDAK pernah menulis ke DB langsung; semua mutasi via external Python CLI.

## Command construction (kode persis)

```csharp
var args = new List<string> { "main.py", "sustained-use-final", "decide", "--decision", decision };
if (windowId > 0) args.AddRange(new[] { "--window-id", windowId.ToString() });
if (!string.IsNullOrWhiteSpace(note)) args.AddRange(new[] { "--note", note });
if (!string.IsNullOrWhiteSpace(decidedBy)) args.AddRange(new[] { "--decided-by", decidedBy });
```

## Contoh command persis yang dieksekusi

Submit sample: `decision=CONTINUE`, `windowId=1`, `note="test"`, `decidedBy="operator"`:

```
python main.py sustained-use-final decide --decision CONTINUE --window-id 1 --note test --decided-by operator
```

- **Working directory:** `F:\My Son`
- **Valid enum decisions:** `PENDING`, `CONTINUE`, `SIMPLIFY`, `AUTHORIZE_FUTURE_INVESTIGATION`
- Invalid decision ditolak sebelum Process dijalankan (return error, tidak eksekusi).

## UI safety

- Dropdown restricted ke valid enum saja
- Confirmation checkbox wajib sebelum submit
- Raw stdout/stderr ditampilkan apa adanya pada sukses/gagal
- Re-query DB setelah sukses (no optimistic update)
