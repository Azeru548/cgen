"use client";

/**
 * Expired-file revival for the viewer.
 *
 * A previously saved workspace can reference files whose delivery died with a
 * backend restart, or that were minted against another deployment, so the
 * mesh fetch 404s when the revision is opened. The spec in the revision is
 * authoritative, so the caller re-mints fresh files (the backend's no-AI
 * `/remint` path) instead of leaving the viewer dead on the error overlay.
 *
 * Contract:
 *  - only an `HTTP 404` preview error triggers a revival (network failures
 *    and 5xx must not mutate history);
 *  - at most two attempts per workspace per mount: a cold backend can swallow
 *    the first one, but a genuinely broken store must not append revisions in
 *    a loop;
 *  - a workspace that is busy is skipped WITHOUT consuming its attempt — an
 *    operation in flight owns the viewer, and the stale 404 message is
 *    retried once it settles.
 */
import { useEffect, useRef } from "react";
import { track } from "@/lib/telemetry";

/** Bounded so a failing store cannot spam history, generous enough to ride
 *  out one cold start. */
const MAX_ATTEMPTS = 2;

export function useExpiredFileRevival(
  previewError: string | null,
  /** Safe to mutate history right now: a spec is visible and no op is running. */
  canRevive: boolean,
  workspaceId: string,
  /** Called once per workspace; expected to re-mint fresh files. */
  revive: () => void,
): void {
  const attempts = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    if (previewError === null || !/HTTP 404\b/.test(previewError)) return;
    if (!canRevive) return;
    const used = attempts.current.get(workspaceId) ?? 0;
    if (used >= MAX_ATTEMPTS) return;
    attempts.current.set(workspaceId, used + 1);
    track("files_expired");
    revive();
  }, [previewError, canRevive, workspaceId, revive]);
}
