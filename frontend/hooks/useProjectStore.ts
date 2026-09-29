"use client";

import { useCallback, useState } from "react";
import { useAuth, useFirestore } from "@/components/AuthProvider";
import { createProjectRecord, listProjects } from "@/lib/projectStore";
import { createProject } from "@/lib/revisions";
import type { Project } from "@/types/revisions";

/**
 * Create the account's first project from onboarding.
 *
 * Guests keep the in-memory default project, so this is a no-op for them and
 * the workspace still opens.
 */
export function useProjectStore() {
  const { uid } = useAuth();
  const db = useFirestore();
  const [error, setError] = useState<string | null>(null);

  const startProject = useCallback(
    async (name: string): Promise<Project | null> => {
      if (db === null || uid === null) {
        setError(null);
        return null;
      }
      try {
        const existing = await listProjects(db, uid);
        if (existing.length > 0) return null;
        const project = createProject(name);
        await createProjectRecord(db, uid, project);
        setError(null);
        return project;
      } catch {
        setError("Could not create your project. Try again.");
        return null;
      }
    },
    [db, uid],
  );

  return { startProject, error };
}
