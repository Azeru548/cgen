/** First-party launch telemetry.
 *
 * Two small helpers that talk to this project's own backend:
 *
 *   track("generate_completed")   -> counted, aggregate only
 *   reportError(err, "/workspace") -> logged with a request id
 *
 * Deliberately not a third-party analytics SDK: no cookies, no user ids, no
 * prompt text, no cross-site script. The server keeps daily counters and the
 * event log, which is enough to answer "did the launch work today?".
 *
 * Every call is fire-and-forget and can never throw: telemetry must not break
 * the product it is measuring.
 */
import { API_BASE_URL } from "./api";

export type TelemetryEvent =
  | "landing_view"
  | "landing_cta"
  | "sign_in"
  | "sign_out"
  | "workspace_open"
  | "generate_started"
  | "generate_completed"
  | "generate_failed"
  | "modify_started"
  | "modify_completed"
  | "modify_failed"
  | "revision_selected"
  | "files_expired"
  | "download_clicked";

/** Current page path only: no query string, no prompt ever. */
function currentPath(): string {
  if (typeof window === "undefined") return "/";
  return window.location.pathname.slice(0, 200);
}

function post(path: string, body: unknown): void {
  if (typeof window === "undefined") return;
  try {
    const payload = JSON.stringify(body);
    // sendBeacon survives the page being closed (e.g. a click that navigates).
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: "application/json" });
      if (navigator.sendBeacon(`${API_BASE_URL}${path}`, blob)) return;
    }
    void fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* Telemetry is never allowed to affect the UI. */
  }
}

export function track(event: TelemetryEvent): void {
  post("/telemetry/event", { name: event, path: currentPath() });
}

export function reportError(error: unknown, context?: string): void {
  const message =
    error instanceof Error
      ? `${error.name}: ${error.message}`
      : typeof error === "string"
        ? error
        : "Unknown error";
  const stack =
    error instanceof Error && typeof error.stack === "string"
      ? error.stack
      : undefined;
  post("/telemetry/error", {
    message,
    stack,
    path: context ?? currentPath(),
  });
}
