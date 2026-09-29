"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import Image from "next/image";
import { SignInForm } from "@/components/SignInForm";
import { useAuth } from "@/components/AuthProvider";

function SignInInner() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/workspace";
  const { status } = useAuth();

  /* Someone already signed in has no business on this page. */
  useEffect(() => {
    if (status === "signed-in") router.replace(next);
  }, [status, next, router]);

  return (
    <div className="auth">
      <Link className="auth-back mono" href="/">
        ← cgen
      </Link>
      <div className="auth-card">
        <Image
          src="/logo-removebg.png"
          alt="cgen"
          width={44}
          height={44}
          className="brand-logo"
          priority
        />
        <h1 className="auth-title">Your bench</h1>
        <p className="auth-sub">
          An account keeps every project, workspace and revision under your
          email, on any device.
        </p>
        {status === "unavailable" ? (
          <p className="auth-note">
            Accounts are unavailable right now. You can still{" "}
            <Link href="/workspace">work without one</Link>.
          </p>
        ) : (
          <SignInForm />
        )}
        <p className="auth-foot mono">
          <Link href="/workspace">Skip — use the bench without an account</Link>
        </p>
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={null}>
      <SignInInner />
    </Suspense>
  );
}
