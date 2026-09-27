"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  type User,
} from "firebase/auth";
import { firestore, firebaseAuth, isFirebaseConfigured, persistAuthSession } from "@/lib/firebase";

export type AuthStatus = "loading" | "signed-out" | "signed-in" | "unavailable";

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  uid: string | null;
  email: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  /* Only the Firebase listener writes state; `unavailable` is derived, so no
   * effect ever has to setState just to configure itself. */
  const [session, setSession] = useState<{ ready: boolean; user: User | null }>({
    ready: false,
    user: null,
  });

  const status: AuthStatus = !isFirebaseConfigured
    ? "unavailable"
    : !session.ready
      ? "loading"
      : session.user
        ? "signed-in"
        : "signed-out";

  useEffect(() => {
    if (!isFirebaseConfigured) return;
    let cancelled = false;
    void persistAuthSession();
    const unsubscribe = onAuthStateChanged(firebaseAuth(), (next) => {
      if (cancelled) return;
      setSession({ ready: true, user: next });
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  /* Surface a clear message instead of the raw SDK error text, which can be
   * cryptic ("auth/invalid-credential") and sometimes leak whether an account
   * exists. */
  const translate = useCallback((error: unknown): never => {
    const code =
      typeof error === "object" && error !== null && "code" in error
        ? String((error as { code: unknown }).code)
        : "";
    const messages: Record<string, string> = {
      "auth/invalid-credential": "Email or password is incorrect.",
      "auth/email-already-in-use": "An account with that email already exists.",
      "auth/weak-password": "Password must be at least 6 characters.",
      "auth/invalid-email": "That email address is not valid.",
      "auth/too-many-requests": "Too many attempts. Wait a moment and try again.",
      "auth/network-request-failed": "Network error. Check your connection.",
    };
    const known = messages[code];
    throw new Error(known ?? "Sign-in failed. Try again.");
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      if (!isFirebaseConfigured) throw new Error("Accounts are not configured.");
      try {
        await signInWithEmailAndPassword(firebaseAuth(), email, password);
      } catch (error) {
        translate(error);
      }
    },
    [translate],
  );

  const signUp = useCallback(
    async (email: string, password: string) => {
      if (!isFirebaseConfigured) throw new Error("Accounts are not configured.");
      try {
        await createUserWithEmailAndPassword(firebaseAuth(), email, password);
      } catch (error) {
        translate(error);
      }
    },
    [translate],
  );

  const signOut = useCallback(async () => {
    if (!isFirebaseConfigured) return;
    await firebaseSignOut(firebaseAuth());
  }, []);

  const user = session.user;
  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      uid: user?.uid ?? null,
      email: user?.email ?? null,
      signIn,
      signUp,
      signOut,
    }),
    [status, user, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return value;
}

/** Firestore handle, or null when Firebase is not configured. */
export function useFirestore() {
  return useMemo(() => (isFirebaseConfigured ? firestore() : null), []);
}
