/**
 * Minimal 404 page — replaces the silent <Navigate to="/" /> fallback so an
 * unknown URL reports itself instead of quietly landing on the dashboard.
 */
export default function NotFound() {
  return (
    <div
      style={{
        minHeight: '60vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '0.75rem',
        textAlign: 'center',
        padding: '2rem',
      }}
    >
      <p
        style={{
          fontSize: '0.75rem',
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color: 'var(--ink-soft, #6B7488)',
          margin: 0,
        }}
      >
        404 — Halaman tidak ditemukan
      </p>
      <h1 style={{ fontSize: '2rem', margin: 0 }}>Alamat ini tidak ada di AIOS.</h1>
      <p style={{ maxWidth: '38ch', color: 'var(--ink-soft, #6B7488)', margin: 0 }}>
        Periksa kembali tautannya, atau kembali ke Atrium.
      </p>
      <a
        href="/atrium"
        style={{
          marginTop: '0.5rem',
          padding: '0.55rem 1.1rem',
          borderRadius: '999px',
          border: '1px solid var(--line, #E7E2D8)',
          textDecoration: 'none',
          color: 'inherit',
        }}
      >
        Kembali ke Atrium
      </a>
    </div>
  );
}
