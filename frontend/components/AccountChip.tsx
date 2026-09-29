"use client";

import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";

/** Signed-in identity in the top bar, or a sign-in affordance. */
export function AccountChip() {
  const { status, email, uid, signOut } = useAuth();

  if (status === "unavailable") return null;
  if (status === "loading") {
    return <span className="account-chip">Checking account…</span>;
  }
  if (status === "signed-out" || !uid) {
    return (
      <div className="account-chip" data-testid="account-signin-inline">
        <Link className="account-chip-link" href="/signin">
          Sign in
        </Link>
      </div>
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
