"use client";

import { useEffect } from "react";
import { reportError } from "@/lib/telemetry";

/** Catches the two classes of error React does not: uncaught exceptions from
 *  event handlers and timers, and unhandled promise rejections (a failed mesh
 *  fetch, a Firestore write). Route render errors are caught by app/error.tsx.
 */
export function TelemetryBridge() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      reportError(event.error ?? event.message);
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      reportError(event.reason);
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return null;
}
