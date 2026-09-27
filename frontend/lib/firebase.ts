/** Firebase app, Auth, and Firestore singletons.
 *
 *  The web config is public by design (Firebase ships it to every browser),
 *  so it comes from NEXT_PUBLIC_* env vars rather than a checked-in secret.
 *  Nothing here reads a service-role key; the backend holds that.
 *
 *  Every export is lazy so the app still renders when Firebase is not
 *  configured — a missing key degrades to "accounts unavailable", never a
 *  crash on load.
 */
import { initializeApp, getApps, getApp, type FirebaseApp } from "firebase/app";
import {
  getAuth,
  browserLocalPersistence,
  setPersistence,
  type Auth,
} from "firebase/auth";
import { getFirestore, type Firestore } from "firebase/firestore";

export interface FirebaseConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  storageBucket: string;
  messagingSenderId: string;
  appId: string;
}

/**
 * Public Firebase web config for cgen.
 *
 * These identifiers are not secrets — Firebase's own setup guide has you
 * paste them into client code, and they ship to every browser. They are
 * committed so the app works on any host (e.g. pxxl.space) without anyone
 * having to configure build-time environment variables first.
 *
 * `NEXT_PUBLIC_FIREBASE_*` still takes precedence when present, so a
 * deployment can override the project without a code change.
 */
const COMMITTED_FIREBASE_CONFIG: FirebaseConfig = {
  apiKey: "AIzaSyBscSEjaKsUeFgvWI1SHbip4j53eExeRBA",
  authDomain: "vouch-c28ec.firebaseapp.com",
  projectId: "vouch-c28ec",
  storageBucket: "vouch-c28ec.firebasestorage.app",
  messagingSenderId: "306848610885",
  appId: "1:306848610885:web:197d3a1782711ec736812c",
};

/**
 * Read the public web config, or null if nothing is configured.
 *
 * Each variable is referenced explicitly: Next.js inlines individual
 * `process.env.NEXT_PUBLIC_*` accesses at build time, but reading the
 * `process.env` object as a whole yields nothing in the browser bundle.
 */
export function readFirebaseConfig(
  env: Record<string, string | undefined> = {
    NEXT_PUBLIC_FIREBASE_API_KEY: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    NEXT_PUBLIC_FIREBASE_PROJECT_ID: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
    NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID:
      process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
    NEXT_PUBLIC_FIREBASE_APP_ID: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  },
): FirebaseConfig | null {
  const fromEnv: FirebaseConfig = {
    apiKey: env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
    authDomain: env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
    projectId: env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
    storageBucket: env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET ?? "",
    messagingSenderId: env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "",
    appId: env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
  };
  const complete = (config: FirebaseConfig) =>
    Object.values(config).every((value) => value.length > 0) ? config : null;
  return complete(fromEnv) ?? complete(COMMITTED_FIREBASE_CONFIG);
}

export const firebaseConfig: FirebaseConfig | null = readFirebaseConfig();

let appRef: FirebaseApp | null = null;
let authRef: Auth | null = null;
let firestoreRef: Firestore | null = null;

function ensureApp(): FirebaseApp {
  if (appRef) return appRef;
  if (!firebaseConfig) {
    throw new Error(
      "Firebase is not configured. Set the NEXT_PUBLIC_FIREBASE_* env vars.",
    );
  }
  appRef = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);
  return appRef;
}

/** True when accounts can be used at all in this build. */
export const isFirebaseConfigured = firebaseConfig !== null;

export function firebaseAuth(): Auth {
  if (!authRef) authRef = getAuth(ensureApp());
  return authRef;
}

export function firestore(): Firestore {
  if (!firestoreRef) firestoreRef = getFirestore(ensureApp());
  return firestoreRef;
}

/** Persist the session so a reload keeps the user signed in. */
export async function persistAuthSession(): Promise<void> {
  if (!isFirebaseConfigured) return;
  await setPersistence(firebaseAuth(), browserLocalPersistence);
}
