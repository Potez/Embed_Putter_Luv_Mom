import nodemailer from "nodemailer";
import type { Alert } from "@roomsense/shared";

const env = process.env;
const DASH = (env.DASHBOARD_URL ?? "http://localhost:5173").replace(/\/$/, "");

const SEV_ICON: Record<string, string> = { critical: "🚨", high: "🔴", medium: "🟡", low: "🔵", info: "🟢" };

export function linkFor(a: Pick<Alert, "room_id">): string {
  return a.room_id ? `${DASH}/#/room/${encodeURIComponent(a.room_id)}` : `${DASH}/#/alerts`;
}

/** Spec §3: room, event, time, measured value, link. */
export function formatAlert(a: Alert, roomName?: string): string {
  const when = new Date(a.created_ms).toLocaleString("th-TH", { timeZone: "Asia/Bangkok" });
  return [
    `${SEV_ICON[a.severity] ?? ""} ${a.message}`,
    `ห้อง: ${roomName ?? a.room_id ?? "-"}`,
    `เวลา: ${when}`,
    a.value ? `ค่าที่วัดได้: ${a.value}` : null,
    `เปิด dashboard: ${linkFor(a)}`,
  ].filter(Boolean).join("\n");
}

export async function sendTelegram(text: string): Promise<boolean> {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return false;
  try {
    const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text, disable_web_page_preview: true }),
    });
    if (!res.ok) console.error(`[telegram] ${res.status} ${await res.text()}`);
    return res.ok;
  } catch (e) {
    console.error("[telegram]", (e as Error).message);
    return false;
  }
}

const mailer = env.SMTP_USER && env.SMTP_PASS
  ? nodemailer.createTransport({
      host: env.SMTP_HOST ?? "smtp.gmail.com",
      port: Number(env.SMTP_PORT ?? 465),
      secure: Number(env.SMTP_PORT ?? 465) === 465,
      auth: { user: env.SMTP_USER, pass: env.SMTP_PASS },
    })
  : null;

export async function sendEmail(subject: string, text: string): Promise<boolean> {
  if (!mailer || !env.ALERT_EMAIL_TO) return false;
  try {
    await mailer.sendMail({ from: `RoomSense <${env.SMTP_USER}>`, to: env.ALERT_EMAIL_TO, subject, text });
    return true;
  } catch (e) {
    console.error("[email]", (e as Error).message);
    return false;
  }
}
