import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { HashRouter, NavLink, Route, Routes, Link } from "react-router-dom";
import { signInWithEmailAndPassword, signOut } from "firebase/auth";
import { auth } from "./firebase.ts";
import { useAlerts, useAuth, useLives, useRoomList } from "./hooks.ts";
import Overview from "./pages/Overview.tsx";
import RoomDetail from "./pages/RoomDetail.tsx";
import Bookings from "./pages/Bookings.tsx";
import Reports from "./pages/Reports.tsx";
import Alerts from "./pages/Alerts.tsx";
import Health from "./pages/Health.tsx";

export default function App() {
  const user = useAuth();
  if (user === undefined) return null;
  if (!user) return <Login />;
  return (
    <HashRouter>
      <FireBanner />
      <TopBar email={user.email ?? ""} />
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/room/:id" element={<RoomDetail />} />
          <Route path="/bookings" element={<Bookings />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/health" element={<Health />} />
        </Routes>
      </main>
    </HashRouter>
  );
}

function TopBar({ email }: { email: string }) {
  const since = useMemo(() => Date.now() - 86_400_000, []);
  const alerts = useAlerts(since);
  const pending = alerts?.filter((a) => !a.ack_ms && !a.resolved_ms && a.severity !== "info").length ?? 0;
  return (
    <header className="topbar">
      <div className="brand">RoomSense<small>หอสมุดกลาง</small></div>
      <nav className="nav">
        <NavLink to="/" end>ภาพรวม</NavLink>
        <NavLink to="/bookings">การจอง</NavLink>
        <NavLink to="/reports">รายงาน</NavLink>
        <NavLink to="/alerts">แจ้งเตือน{pending > 0 && <span className="dot" aria-label={`${pending} รายการยังไม่รับทราบ`}>{pending}</span>}</NavLink>
        <NavLink to="/health">สถานะระบบ</NavLink>
      </nav>
      <span className="user">{email}</span>
      <button className="btn btn-sm" onClick={() => signOut(auth)}>ออกจากระบบ</button>
    </header>
  );
}

/** Critical fire alert: visible on every page + audible alarm until silenced. */
function FireBanner() {
  const rooms = useRoomList() ?? [];
  const lives = useLives(rooms.map((r) => r.id));
  const burning = rooms.filter((r) => lives[r.id]?.flame);
  const [muted, setMuted] = useState(false);
  const audio = useRef<{ ctx: AudioContext; osc: OscillatorNode } | null>(null);

  useEffect(() => {
    const on = burning.length > 0 && !muted;
    if (on && !audio.current) {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = 880;
      gain.gain.value = 0.08;
      // two-tone siren
      const lfo = ctx.createOscillator();
      const lfoGain = ctx.createGain();
      lfo.frequency.value = 2;
      lfoGain.gain.value = 220;
      lfo.connect(lfoGain).connect(osc.frequency);
      osc.connect(gain).connect(ctx.destination);
      osc.start(); lfo.start();
      audio.current = { ctx, osc };
    }
    if (!on && audio.current) {
      audio.current.ctx.close();
      audio.current = null;
    }
  }, [burning.length, muted]);

  useEffect(() => { if (burning.length === 0) setMuted(false); }, [burning.length]);

  if (!burning.length) return null;
  return (
    <div className="fire-banner" role="alert">
      <span>🔥 ตรวจพบไฟ: {burning.map((r) => r.name).join(", ")}</span>
      {burning.map((r) => <Link key={r.id} className="btn btn-sm" to={`/room/${r.id}`}>ดู {r.name}</Link>)}
      {!muted && <button className="btn btn-sm" onClick={() => setMuted(true)}>🔇 ปิดเสียง</button>}
    </div>
  );
}

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try { await signInWithEmailAndPassword(auth, email, password); }
    catch { setErr("อีเมลหรือรหัสผ่านไม่ถูกต้อง"); }
    finally { setBusy(false); }
  };
  return (
    <div className="login">
      <form className="panel" onSubmit={submit}>
        <h1>RoomSense</h1>
        <p className="muted small" style={{ margin: 0 }}>ระบบตรวจสอบการใช้ห้องประชุมกลุ่ม · สำหรับเจ้าหน้าที่</p>
        <label>อีเมล<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>รหัสผ่าน<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {err && <div className="error">{err}</div>}
        <button className="btn btn-primary" disabled={busy}>{busy ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}</button>
      </form>
    </div>
  );
}
