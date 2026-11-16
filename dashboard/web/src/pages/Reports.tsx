import { useEffect, useMemo, useState } from "react";
import { get, orderByKey, query, ref, startAt } from "firebase/database";
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend } from "recharts";
import { hourKey, type HourStat } from "@roomsense/shared";
import { db } from "../firebase.ts";
import { useBookings, useRoomList } from "../hooks.ts";
import { Card, chartColor, downloadCsv, Empty, fmtDate, fmtDateTime, Loading } from "../ui.tsx";

const DOW = ["อา", "จ", "อ", "พ", "พฤ", "ศ", "ส"];
const dayKey = (ms: number) => new Date(ms).toLocaleDateString("sv-SE");

export default function Reports() {
  const [days, setDays] = useState(7);
  const [roomFilter, setRoomFilter] = useState("");
  const from = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() - (days - 1) * 86_400_000; }, [days]);
  const rooms = useRoomList();
  const bookings = useBookings(from, Date.now());
  const [stats, setStats] = useState<Record<string, HourStat[]> | undefined>();

  useEffect(() => {
    if (!rooms) return;
    setStats(undefined);
    Promise.all(rooms.map(async (r) => {
      const s = await get(query(ref(db, `stats/${r.id}/hourly`), orderByKey(), startAt(hourKey(from))));
      return [r.id, Object.values((s.val() ?? {}) as Record<string, HourStat>)] as const;
    })).then((e) => setStats(Object.fromEntries(e)));
  }, [rooms, from]);

  const ended = (bookings ?? []).filter((b) => b.result && (!roomFilter || b.room_id === roomFilter));
  const hours = useMemo(
    () => Object.entries(stats ?? {}).filter(([id]) => !roomFilter || id === roomFilter).flatMap(([, h]) => h),
    [stats, roomFilter],
  );

  const daily = useMemo(() => {
    const m = new Map<string, { day: string; util: number[]; noShow: number; total: number; lightEmptyH: number; occupiedH: number }>();
    for (let t = from; t <= Date.now(); t += 86_400_000) m.set(dayKey(t), { day: dayKey(t), util: [], noShow: 0, total: 0, lightEmptyH: 0, occupiedH: 0 });
    for (const b of ended) {
      const d = m.get(dayKey(b.start_ms)); if (!d) continue;
      d.total++; if (b.result!.no_show) d.noShow++; d.util.push(b.result!.util_pct);
    }
    for (const h of hours) {
      const d = m.get(dayKey(h.hour_ms)); if (!d) continue;
      d.lightEmptyH += (h.light_empty * h.sample_sec) / 3600;
      d.occupiedH += (h.occupied * h.sample_sec) / 3600;
    }
    return [...m.values()].map((d) => ({
      ...d,
      label: fmtDate(new Date(`${d.day}T00:00`).getTime()),
      utilPct: d.util.length ? Math.round(d.util.reduce((a, b) => a + b, 0) / d.util.length) : null,
      noShowPct: d.total ? Math.round((100 * d.noShow) / d.total) : null,
      lightEmptyH: +d.lightEmptyH.toFixed(2),
      occupiedH: +d.occupiedH.toFixed(2),
    }));
  }, [ended, hours, from]);

  const heat = useMemo(() => {
    const g = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => ({ occ: 0, n: 0 })));
    for (const h of hours) {
      const d = new Date(h.hour_ms);
      g[d.getDay()][d.getHours()].occ += h.occupied;
      g[d.getDay()][d.getHours()].n += h.samples;
    }
    return g.map((row) => row.map((c) => (c.n ? c.occ / c.n : null)));
  }, [hours]);

  if (!rooms || !bookings) return <Loading />;
  const totalBookings = ended.length;
  const noShows = ended.filter((b) => b.result!.no_show).length;
  const avgUtil = totalBookings ? Math.round(ended.reduce((a, b) => a + b.result!.util_pct, 0) / totalBookings) : null;
  const lightEmpty = daily.reduce((a, d) => a + d.lightEmptyH, 0);
  const roomName = (id: string) => rooms.find((r) => r.id === id)?.name ?? id;

  const exportCsv = () => {
    downloadCsv(`roomsense-bookings-${dayKey(from)}.csv`, [
      ["booking_id", "room", "booked_by", "title", "start", "end", "expected", "peak", "avg", "util_pct", "no_show"],
      ...ended.map((b) => [b.id, roomName(b.room_id), b.booked_by, b.title, fmtDateTime(b.start_ms), fmtDateTime(b.end_ms),
        b.expected, b.result!.peak, b.result!.avg, b.result!.util_pct, b.result!.no_show]),
    ]);
    downloadCsv(`roomsense-daily-${dayKey(from)}.csv`, [
      ["date", "bookings", "no_show", "no_show_pct", "avg_util_pct", "occupied_hours", "light_on_empty_hours"],
      ...daily.map((d) => [d.day, d.total, d.noShow, d.noShowPct, d.utilPct, d.occupiedH, d.lightEmptyH]),
    ]);
  };

  return (
    <div className="stack">
      <div className="page-head">
        <h1>รายงานสรุปผล</h1>
        <div className="row">
          <select value={roomFilter} onChange={(e) => setRoomFilter(e.target.value)} aria-label="ห้อง">
            <option value="">ทุกห้อง</option>
            {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="ช่วงเวลา">
            <option value={7}>7 วัน</option><option value={14}>14 วัน</option><option value={30}>30 วัน</option>
          </select>
          <button className="btn btn-primary" onClick={exportCsv} disabled={!totalBookings && !hours.length}>⬇ Export CSV</button>
        </div>
      </div>

      <div className="summary">
        <div className="kpi"><div className="v num">{avgUtil ?? "–"}%</div><div className="l">อัตราการใช้ห้องเฉลี่ย (คนจริง ÷ ที่จอง)</div></div>
        <div className="kpi"><div className="v num">{totalBookings ? Math.round((100 * noShows) / totalBookings) : "–"}%</div><div className="l">No-show rate ({noShows}/{totalBookings} ครั้ง)</div></div>
        <div className="kpi"><div className="v num">{lightEmpty.toFixed(1)}</div><div className="l">ชั่วโมงที่ไฟเปิดแต่ห้องว่าง</div></div>
      </div>

      {stats === undefined ? <Loading /> : (
        <>
          <div className="grid grid-2">
            <Card title="อัตราการใช้ห้อง & No-show รายวัน">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={daily} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke={chartColor("c-grid")} vertical={false} />
                  <XAxis dataKey="label" fontSize={12} />
                  <YAxis unit="%" fontSize={12} />
                  <Tooltip formatter={(v) => `${v}%`} />
                  <Legend />
                  <Bar name="ใช้งาน %" dataKey="utilPct" fill={chartColor("c-people")} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar name="No-show %" dataKey="noShowPct" fill={chartColor("noshow")} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="ชั่วโมงที่ไฟเปิดแต่ไม่มีคน (ผลด้านพลังงาน)">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={daily} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid stroke={chartColor("c-grid")} vertical={false} />
                  <XAxis dataKey="label" fontSize={12} />
                  <YAxis unit=" ชม." fontSize={12} />
                  <Tooltip formatter={(v) => `${v} ชม.`} />
                  <Bar name="ไฟเปิด-ห้องว่าง" dataKey="lightEmptyH" fill={chartColor("under")} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
              <p className="small muted" style={{ margin: "8px 0 0" }}>เปรียบเทียบวันก่อนเปิดระบบควบคุมไฟอัตโนมัติ กับวันหลังเปิดใช้</p>
            </Card>
          </div>

          <Card title="ช่วงเวลาที่ห้องถูกใช้มากที่สุด (วัน × ชั่วโมง)">
            {!hours.length ? <Empty>ยังไม่มีข้อมูลสรุปรายชั่วโมง</Empty> : (
              <div style={{ overflowX: "auto" }}>
                <div className="heat" style={{ minWidth: 560 }}>
                  <div />
                  {Array.from({ length: 24 }, (_, h) => <div key={h} className="lbl">{h % 3 === 0 ? h : ""}</div>)}
                  {heat.map((row, d) => (
                    <div key={d} style={{ display: "contents" }}>
                      <div className="lbl">{DOW[d]}</div>
                      {row.map((v, h) => (
                        <div key={h} className="cell" title={`${DOW[d]} ${h}:00 — ${v === null ? "ไม่มีข้อมูล" : `มีคน ${Math.round(v * 100)}% ของเวลา`}`}
                          style={v === null ? undefined : { background: `color-mix(in srgb, var(--c-people) ${Math.round(10 + v * 90)}%, var(--surface-2))` }} />
                      ))}
                    </div>
                  ))}
                </div>
                <p className="small muted">สีเข้ม = มีคนใช้ห้องบ่อย · ชี้ที่ช่องเพื่อดูค่า</p>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
