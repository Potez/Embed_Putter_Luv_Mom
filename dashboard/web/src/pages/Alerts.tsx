import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ref, update } from "firebase/database";
import type { Severity } from "@roomsense/shared";
import { auth, db } from "../firebase.ts";
import { useAlerts, useRoomList } from "../hooks.ts";
import { Card, Empty, fmtDateTime, Loading, SEVERITY, SevBadge } from "../ui.tsx";

export default function Alerts() {
  const [days, setDays] = useState(1);
  const since = useMemo(() => Date.now() - days * 86_400_000, [days]);
  const alerts = useAlerts(since);
  const rooms = useRoomList();
  const [room, setRoom] = useState("");
  const [sev, setSev] = useState<"" | Severity>("");
  const [onlyOpen, setOnlyOpen] = useState(false);

  if (!alerts || !rooms) return <Loading />;
  const list = alerts.filter((a) =>
    (!room || a.room_id === room) && (!sev || a.severity === sev) && (!onlyOpen || (!a.ack_ms && !a.resolved_ms)));
  const ack = (id: string) =>
    update(ref(db, `alerts/${id}`), { ack_by: auth.currentUser?.email ?? "staff", ack_ms: Date.now() });

  return (
    <div className="stack">
      <div className="page-head"><h1>การแจ้งเตือน</h1></div>
      <Card>
        <div className="form" style={{ marginBottom: 12 }}>
          <label>ห้อง
            <select value={room} onChange={(e) => setRoom(e.target.value)}>
              <option value="">ทุกห้อง</option>
              {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </label>
          <label>ระดับ
            <select value={sev} onChange={(e) => setSev(e.target.value as Severity | "")}>
              <option value="">ทุกระดับ</option>
              {(Object.keys(SEVERITY) as Severity[]).map((s) => <option key={s} value={s}>{SEVERITY[s].label}</option>)}
            </select>
          </label>
          <label>ช่วงเวลา
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={1}>24 ชม.</option><option value={7}>7 วัน</option><option value={30}>30 วัน</option>
            </select>
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} style={{ minHeight: 0 }} /> เฉพาะที่ยังไม่รับทราบ
          </label>
        </div>
        {!list.length ? <Empty>ไม่มีการแจ้งเตือน 🎉</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>เวลา</th><th>ระดับ</th><th>เหตุการณ์</th><th>ค่าที่วัดได้</th><th>ส่งไปที่</th><th>สถานะ</th></tr></thead>
              <tbody>
                {list.map((a) => (
                  <tr key={a.id}>
                    <td className="num small">{fmtDateTime(a.created_ms)}</td>
                    <td><SevBadge sev={a.severity} /></td>
                    <td>{a.message}{a.room_id && <> · <Link to={`/room/${a.room_id}`}>ดูห้อง</Link></>}</td>
                    <td className="small">{a.value ?? "–"}</td>
                    <td className="small muted">{(a.channels ?? ["web"]).join(", ")}</td>
                    <td className="small">
                      {a.ack_ms ? <span className="muted">✔ รับทราบโดย {a.ack_by}</span>
                        : a.severity === "info" ? null : <button className="btn btn-sm btn-primary" onClick={() => ack(a.id)}>รับทราบ</button>}
                      {a.resolved_ms && <div className="muted">คลี่คลายแล้ว</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
