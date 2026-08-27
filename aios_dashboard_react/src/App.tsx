import GateStrip from './components/GateStrip'
import './App.css'

export default function App() {
  return (
    <div className="app-shell">
      <nav className="navbar">
        <span className="navbar-brand">AIOS</span>
        <div className="navbar-nav">
          <a className="nav-link active" href="#">Overview</a>
          <a className="nav-link" href="#">Phase 1</a>
          <a className="nav-link" href="#">Phase 2</a>
          <a className="nav-link" href="#">Phase 3</a>
        </div>
        <span className="ro-plate">read-only</span>
      </nav>

      <GateStrip />

      <main className="main-content">
        <h1 className="display-serif">Redesign React — kerangka awal</h1>
        <p className="page-sub">
          GateStrip di atas sudah full port ke Framer Motion (stagger entrance, evidence
          bar animasi, amber pulse via <code>animate</code> loop). Bagian ini placeholder
          menunggu halaman Phase 0–3 di-port berikutnya.
        </p>
      </main>
    </div>
  )
}
