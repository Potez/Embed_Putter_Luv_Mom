import { useEffect, useMemo, useRef, useState } from "react";
import { onValue, ref } from "firebase/database";
import { packetDelivery, sensorToCloudMs, stats, toMs, type Reading } from "@roomsense/shared";
import { db } from "../firebase.ts";
import { useDevices, useEvents, useNow, useReadings, useRoomList, useValue } from "../hooks.ts";
import { ago, Card, downloadCsv, Empty, fmtDateTime, Loading } from "../ui.tsx";

const WINDOWS = [{ m: 15, l: "15 นาที" }, { m: 60, l: "1 ชม." }, { m: 24 * 60, l: "24 ชม." }];
const fmtUptime = (s?: number) => {
  if (s === undefined) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}ว ${h}ชม.` : h ? `${h}ชม. ${m}น.` : `${m} นาที`;
};
const ms = (v?: number) => (v === undefined ? "–" : `${Math.round(v)} ms`);

export default function Health() {
  const now = useNow(2000);
  const [win, setWin] = useState(60);
  const from = useMemo(() => Date.now() - win * 60_000, [win]);
  const devices = useDevices();
  const rooms = useRoomList();
  const worker = useValue<number>("worker/heartbeat_ms");

  if (!devices || !rooms) return <Loading />;
  return (
    <div className="stack">
      <div className="page-head">
        <h1>สถานะระบบ</h1>
        <div className="row">
          {WINDOWS.map((w) => <button key={w.m} className={`btn btn-sm ${win === w.m ? "btn-primary" : ""}`} onClick={() => setWin(w.m)}>{w.l}</button>)}
        </div>
      </div>

      <Card title="อุปกรณ์" actions={<span className="small muted">Worker (แจ้งเตือน): {worker && now - worker < 90_000 ? "🟢 ทำงาน" : "⚫ ไม่ทำงาน"}</span>}>
        {!devices.length ? <Empty>ยังไม่มีอุปกรณ์รายงานสถานะ</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>อุปกรณ์</th><th>สถานะ</th><th>RSSI</th><th>Uptime</th><th>Heap ว่าง</th><th>Reboot / Reconnect</th><th>Buffer</th><th>เห็นล่าสุด</th></tr></thead>
              <tbody>
                {devices.map((d) => {
                  const online = !!d.last_seen && now - toMs(d.last_seen) < 60_000;
                  return (
                    <tr key={d.id}>
                      <td><strong>{d.id}</strong><div className="small muted">{d.kind}{d.room_id ? ` · ${d.room_id}` : ""}</div></td>
                      <td>{online ? <span className="badge st-free">🟢 Online</span> : <span className="badge st-offline">⚫ Offline</span>}</td>
                      <td className="num">{d.rssi ?? "–"} dBm</td>
                      <td className="num">{fmtUptime(d.uptime_s)}</td>
                      <td className="num">{d.heap_free ? `${Math.round(d.heap_free / 1024)} KB` : "–"}</td>
                      <td className="num">{d.reboots ?? 0} / {d.reconnects ?? 0}</td>
                      <td className="small">
                        {d.buffer_depth ? `${d.buffer_depth} รอส่ง` : "–"}
                        {d.last_outage && <div className="muted">เน็ตหลุดล่าสุด {fmtDateTime(toMs(d.last_outage.from))}–{new Date(toMs(d.last_outage.to)).toLocaleTimeString("th-TH")} · ส่งย้อนหลัง {d.last_outage.backfilled}</div>}
                      </td>
                      <td className="small">{d.last_seen ? ago(toMs(d.last_seen), now) : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-2">
        {rooms.map((r) => <RoomMetrics key={`${r.id}-${win}`} roomId={r.id} name={r.name} from={from} />)}
      </div>
    </div>
  );
}

function RoomMetrics({ roomId, name, from }: { roomId: string; name: string; from: number }) {
  const readings = useReadings(roomId, from);
  const events = useEvents(roomId, Math.floor(from / 1000));
  const dash = useDashLatency(roomId);

  const m = useMemo(() => {
    if (!readings) return null;
    const pdr = packetDelivery(readings.filter((r) => r.node_seq !== undefined).map((r) => r.node_seq!));
    const sensor = stats(readings.map(sensorToCloudMs).filter((x): x is number => x !== null));
    const light = stats((events ?? []).filter((e) => e.type === "light_on" && e.latency_ms).map((e) => e.latency_ms!));
    const conf = stats(readings.filter((r) => typeof r.ai_conf === "number").map((r) => r.ai_conf!));
    const buffered = readings.filter((r) => r.buffered).length;
    return { pdr, sensor, light, conf, buffered, n: readings.length };
  }, [readings, events]);

  const exportCsv = (rs: Reading[]) => downloadCsv(`roomsense-${roomId}-readings.csv`, [
    ["ts", "node_ts", "server_ts", "node_seq", "people_ai", "ai_conf", "people_ir", "pir", "light_on", "ldr", "temp_c", "humidity", "sound_db", "flame", "buffered"],
    ...rs.map((r) => [r.ts, r.node_ts, r.server_ts, r.node_seq, r.people_ai, r.ai_conf, r.people_ir, r.pir, r.light_on, r.ldr, r.temp_c, r.humidity, r.sound_db, r.flame, r.buffered]),
  ]);

  return (
    <Card title={name} actions={readings?.length ? <button className="btn btn-sm" onClick={() => exportCsv(readings)}>⬇ Raw CSV</button> : null}>
      {!m ? <Loading /> : (
        <table>
          <tbody>
            <tr><th>Packet delivery rate</th><td className="num">{m.pdr.pdr === null ? "–" : `${(m.pdr.pdr * 100).toFixed(1)}%`} <span className="muted small">({m.pdr.received}/{m.pdr.expected} packets)</span></td></tr>
            <tr><th>Latency sensor → cloud</th><td className="num">{m.sensor ? `${ms(m.sensor.mean)} (min ${ms(m.sensor.min)} / max ${ms(m.sensor.max)})` : "–"}</td></tr>
            <tr><th>Latency cloud → dashboard</th><td className="num">{dash ? `${ms(dash.mean)} (min ${ms(dash.min)} / max ${ms(dash.max)}, n=${dash.n})` : "รอข้อมูลสด…"}</td></tr>
            <tr><th>Latency คนเข้า → ไฟติด</th><td className="num">{m.light ? `${ms(m.light.mean)} (min ${ms(m.light.min)} / max ${ms(m.light.max)})` : "–"}</td></tr>
            <tr><th>AI confidence เฉลี่ย</th><td className="num">{m.conf ? `${(m.conf.mean * 100).toFixed(1)}%` : "–"}</td></tr>
            <tr><th>ข้อมูลจาก buffer (E4)</th><td className="num">{m.buffered} รายการ</td></tr>
            <tr><th>จำนวน readings</th><td className="num">{m.n}</td></tr>
          </tbody>
        </table>
      )}
    </Card>
  );
}

/** Measures cloud -> this browser latency for each live update (needs server_ts and synced clocks). */
function useDashLatency(roomId: string) {
  const samples = useRef<number[]>([]);
  const [, force] = useState(0);
  useEffect(() => {
    let first = true;
    return onValue(ref(db, `rooms/${roomId}/live`), (s) => {
      const r = s.val() as Reading | null;
      if (first) { first = false; return; } // initial value is cached, not a fresh update
      if (!r?.server_ts) return;
      const d = Date.now() - r.server_ts;
      if (d >= 0 && d < 60_000) {
        samples.current = [...samples.current.slice(-199), d];
        force((x) => x + 1);
      }
    });
  }, [roomId]);
  return stats(samples.current);
}
