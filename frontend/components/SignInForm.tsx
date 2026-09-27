"use client";

import { useState, type FormEvent } from "react";
import { useAuth } from "@/components/AuthProvider";

/** Email + password sign-in. One form, two modes, no marketing chrome. */
export function SignInForm() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "in") await signIn(email, password);
      else await signUp(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="signin" onSubmit={submit} data-testid="signin-form">
      <h2 className="signin-title">
        {mode === "in" ? "Sign in" : "Create account"}
      </h2>
      <label className="signin-field">
        <span>Email</span>
        <input
          type="email"
          className="object-input"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
          disabled={busy}
        />
      </label>
      <label className="signin-field">
        <span>Password</span>
        <input
          type="password"
          className="object-input"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "in" ? "current-password" : "new-password"}
          minLength={6}
          required
          disabled={busy}
        />
      </label>
      {error ? (
        <p className="signin-error" role="alert">
          {error}
        </p>
      ) : null}
      <button type="submit" className="generate-button" disabled={busy}>
        {busy ? "Working…" : mode === "in" ? "Sign in" : "Create account"}
      </button>
      <button
        type="button"
        className="signin-switch mono"
        onClick={() => {
          setMode(mode === "in" ? "up" : "in");
          setError(null);
        }}
        disabled={busy}
      >
        {mode === "in" ? "Need an account? Create one" : "Have an account? Sign in"}
      </button>
    </form>
  );
}
