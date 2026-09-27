"use client";

import { useAuth } from "@/components/AuthProvider";

/** Signed-in identity in the top bar, or a compact sign-in affordance. */
export function AccountChip() {
  const { status, email, uid, signIn, signOut } = useAuth();

  if (status === "unavailable") return null;
  if (status === "loading") {
    return <span className="account-chip">Checking account…</span>;
  }
  if (status === "signed-out" || !uid) {
    return (
      <form
        className="account-chip"
        data-testid="account-signin-inline"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const emailValue = String(data.get("email") ?? "");
          const password = String(data.get("password") ?? "");
          if (emailValue && password) void signIn(emailValue, password);
          event.currentTarget.reset();
        }}
      >
        <input
          className="object-input mono"
          type="email"
          name="email"
          placeholder="Email"
          aria-label="Email"
          autoComplete="email"
          required
        />
        <input
          className="object-input mono"
          type="password"
          name="password"
          placeholder="Password"
          aria-label="Password"
          autoComplete="current-password"
          required
        />
        <button type="submit" className="account-signout">
          Sign in
        </button>
      </form>
    );
  }
  return (
    <div className="account-chip" data-testid="account-chip">
      <span className="account-chip-email" title={email ?? uid}>
        {email ?? uid.slice(0, 12)}
      </span>
      <button type="button" className="account-signout" onClick={() => void signOut()}>
        Sign out
      </button>
    </div>
  );
}
