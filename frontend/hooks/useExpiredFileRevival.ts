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
 *  - exactly one attempt per workspace per mount: if storage itself is
 *    broken, reminting again could never succeed, so a failed attempt must
 *    not loop;
 *  - a workspace that is busy is skipped WITHOUT consuming its attempt — an
 *    operation in flight owns the viewer, and the stale 404 message is
 *    retried once it settles.
 */
import { useEffect, useRef } from "react";

export function useExpiredFileRevival(
  previewError: string | null,
  /** Safe to mutate history right now: a spec is visible and no op is running. */
  canRevive: boolean,
  workspaceId: string,
  /** Called once per workspace; expected to re-mint fresh files. */
  revive: () => void,
): void {
  const revived = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (previewError === null || !/HTTP 404\b/.test(previewError)) return;
    if (!canRevive) return;
    if (revived.current.has(workspaceId)) return;
    revived.current.add(workspaceId);
    revive();
  }, [previewError, canRevive, workspaceId, revive]);
}
