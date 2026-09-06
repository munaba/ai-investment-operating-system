# Phase 4b — Chart Empty State Proof (No Dummy Data)

> Sumber: sesi Hermes 25 Aug 2026. Halaman `/equity` (Phase 3 tab) saat DB belum punya trades.

## DB state saat verifikasi

```
trades: 0
closed positions with P&L: 0
```

## Rendered HTML persis (curl output)

```html
<div class="tab-pane fade" id="equity" role="tabpanel">
  <div class="alert alert-info text-center py-5">
    <h5>📊 Belum ada data trade untuk periode ini</h5>
    <p class="text-muted mb-0">Chart equity/P&L akan muncul otomatis setelah ada trade yang terekseskusi.</p>
  </div>
</div>
```

## Kesimpulan

- Chart **tidak** dirender ketika tidak ada data — yang muncul honest empty state message.
- **Tidak ada dummy/placeholder data** yang disisipkan agar chart "kelihatan hidup".
- Chart equity curve baru render setelah ada closed positions dengan `RealizedPnl != 0`.
