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

/** Read the public web config from the environment, or null if incomplete. */
export function readFirebaseConfig(
  env: Record<string, string | undefined> = process.env,
): FirebaseConfig | null {
  const config: FirebaseConfig = {
    apiKey: env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
    authDomain: env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
    projectId: env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
    storageBucket: env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET ?? "",
    messagingSenderId: env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "",
    appId: env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
  };
  const missing = Object.values(config).some((value) => value.length === 0);
  return missing ? null : config;
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
