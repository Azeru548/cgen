"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Firestore } from "firebase/firestore";
import { useAuth } from "@/components/AuthProvider";
import {
  appendRevisions,
  createProjectRecord,
  loadProject,
  saveProjectShell,
} from "@/lib/projectStore";
import { createProject } from "@/lib/revisions";
import type { Project } from "@/types/revisions";

/**
 * Mirror the in-memory project into Firestore for signed-in users.
 *
 * Guests are untouched: the app keeps working exactly as before with state
 * held only in React, so signing in is never required to use cgen.
 *
 * For a signed-in user the hook loads their most recent project once, then
 * writes on every change. New revisions are appended (never rewritten); the
 * project shell carries only pointers, so a generate costs one small write
 * rather than rewriting the whole history.
 */
export function useProjectSync(
  project: Project,
  setProject: (update: (current: Project) => Project) => void,
  db: Firestore | null,
) {
  const { uid, status: authStatus } = useAuth();
  const hydrated = useRef(false);
  const knownRevisions = useRef<Set<string>>(new Set());
  const [phase, setPhase] = useState<"loading" | "on" | "error">("loading");
  const persistence: "off" | "loading" | "on" | "error" = db === null ? "off" : phase;

  /* Load the user's project when they sign in (or on first mount for them). */
  useEffect(() => {
    if (authStatus !== "signed-in" || db === null || uid === null) {
      hydrated.current = false;
      knownRevisions.current = new Set();
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const { listProjects } = await import("@/lib/projectStore");
        const projects = await listProjects(db, uid);
        if (cancelled) return;
        if (projects.length === 0) {
          const fresh = createProject("My project");
          await createProjectRecord(db, uid, fresh);
          if (cancelled) return;
          knownRevisions.current = new Set();
          setProject(() => fresh);
        } else {
          const latest = projects[0]!;
          const loaded = await loadProject(db, uid, latest.id);
          if (cancelled) return;
          if (loaded) {
            knownRevisions.current = new Set(
              loaded.workspaces.flatMap((w) => w.revisions.map((r) => r.id)),
            );
            setProject(() => loaded);
          }
        }
        if (!cancelled) {
          hydrated.current = true;
          setPhase("on");
        }
      } catch {
        if (!cancelled) setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authStatus, db, uid, setProject]);

  /* Persist changes once hydration is done. */
  const flush = useCallback(async () => {
    if (db === null || uid === null || !hydrated.current) return;
    try {
      const added = await appendRevisions(db, uid, project, knownRevisions.current);
      added.forEach((id) => knownRevisions.current.add(id));
      await saveProjectShell(db, uid, project);
      setPhase("on");
    } catch {
      setPhase("error");
    }
  }, [db, uid, project]);

  useEffect(() => {
    if (!hydrated.current) return;
    const timer = setTimeout(() => {
      void flush();
    }, 400);
    return () => clearTimeout(timer);
  }, [flush]);

  return { persistence, uid };
}
