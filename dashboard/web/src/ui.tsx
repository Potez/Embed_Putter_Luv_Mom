import type { ReactNode } from "react";
import type { RoomStatus, Severity, SoundLevel } from "@roomsense/shared";

// Colour + icon + text together, never colour alone (spec §5).
export const STATUS: Record<RoomStatus, { label: string; icon: string; cls: string }> = {
  free:      { label: "ว่าง",       icon: "🟢", cls: "st-free" },
  in_use:    { label: "ใช้งาน",     icon: "🔵", cls: "st-inuse" },
  underused: { label: "ใช้ไม่คุ้ม",  icon: "🟡", cls: "st-under" },
  no_show:   { label: "No-show",   icon: "🔴", cls: "st-noshow" },
  offline:   { label: "Offline",   icon: "⚫", cls: "st-offline" },
  fire:      { label: "ตรวจพบไฟ!", icon: "🔥", cls: "st-fire" },
};

export const SEVERITY: Record<Severity, { label: string; cls: string }> = {
  critical: { label: "วิกฤต", cls: "sev-critical" },
  high:     { label: "สูง",   cls: "sev-high" },
  medium:   { label: "กลาง",  cls: "sev-medium" },
  low:      { label: "ต่ำ",   cls: "sev-low" },
  info:     { label: "ข้อมูล", cls: "sev-info" },
};

export const SOUND: Record<SoundLevel, string> = { quiet: "🤫 เงียบ", talk: "💬 พูดคุย", loud: "📢 ดัง" };

export function StatusBadge({ status, big }: { status: RoomStatus; big?: boolean }) {
  const s = STATUS[status];
  return <span className={`badge ${s.cls} ${big ? "badge-big" : ""}`}><span aria-hidden>{s.icon}</span> {s.label}</span>;
}

export function SevBadge({ sev }: { sev: Severity }) {
  return <span className={`badge ${SEVERITY[sev].cls}`}>{SEVERITY[sev].label}</span>;
}

export function ago(ms: number, now: number): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return `${s} วินาทีที่แล้ว`;
  if (s < 3600) return `${Math.floor(s / 60)} นาทีที่แล้ว`;
  if (s < 86400) return `${Math.floor(s / 3600)} ชม.ที่แล้ว`;
  return `${Math.floor(s / 86400)} วันที่แล้ว`;
}

export const fmtTime = (ms: number) => new Date(ms).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
export const fmtDate = (ms: number) => new Date(ms).toLocaleDateString("th-TH", { day: "numeric", month: "short" });
export const fmtDateTime = (ms: number) => `${fmtDate(ms)} ${fmtTime(ms)}`;

export function minsLeft(endMs: number, now: number) {
  const m = Math.max(0, Math.round((endMs - now) / 60000));
  return m >= 60 ? `${Math.floor(m / 60)} ชม. ${m % 60} นาที` : `${m} นาที`;
}

export function Card({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="panel">
      {(title || actions) && <header className="panel-head"><h2>{title}</h2>{actions}</header>}
      {children}
    </section>
  );
}

export function Loading() {
  return <div className="muted pad">กำลังโหลด…</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="muted pad center">{children}</div>;
}

export function downloadCsv(filename: string, rows: (string | number | boolean | null | undefined)[][]) {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  // BOM so Excel opens Thai text correctly
  const blob = new Blob(["﻿" + rows.map((r) => r.map(esc).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Recharts colours read from CSS tokens so charts follow light/dark theme. */
export const chartColor = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim() || "#888";
