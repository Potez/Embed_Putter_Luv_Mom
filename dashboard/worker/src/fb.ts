import { initializeApp, applicationDefault } from "firebase-admin/app";
import { getDatabase } from "firebase-admin/database";

const projectId = process.env.FIREBASE_PROJECT_ID ?? "demo-roomsense";
const emulator = !!process.env.FIREBASE_DATABASE_EMULATOR_HOST;

export const app = initializeApp({
  projectId,
  databaseURL: process.env.FIREBASE_DATABASE_URL ?? `http://127.0.0.1:9000/?ns=${projectId}-default-rtdb`,
  // With emulators no credentials are needed; in production set GOOGLE_APPLICATION_CREDENTIALS.
  ...(emulator ? {} : { credential: applicationDefault() }),
});

export const db = getDatabase(app);
