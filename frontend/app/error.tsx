"use client";

import { useEffect } from "react";
import Link from "next/link";
import { reportError } from "@/lib/telemetry";

/** Route-level error boundary. Next renders this instead of a blank screen
 *  when a page throws during render, and the error is reported so a launch-day
 *  crash is visible on the server rather than only in one visitor's console. */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    reportError(error, "route-error");
  }, [error]);

  return (
    <main className="legal">
      <div className="legal-inner">
        <p className="legal-eyebrow mono">
          <span>Error</span>
          <span>{error.digest ?? "unhandled"}</span>
        </p>

        <h1>That page failed to render.</h1>
        <p className="legal-lede">
          The error was logged. Retrying usually clears it; if it keeps
          happening, the workspace data for this page may be the cause.
        </p>

        <div className="legal-actions">
          <button type="button" className="lp-cta" onClick={() => reset()}>
            Try again
          </button>
          <Link className="lp-ghost mono" href="/">
            Back to the bench
          </Link>
        </div>
      </div>
    </main>
  );
}
