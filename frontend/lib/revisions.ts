/** Pure Project → Workspace → Revision helpers (no React, no I/O).
 *
 *  All functions treat state as immutable and return new objects; stored
 *  revisions are never mutated. Safe to unit-test without a framework.
 */
import type { GenerateResponse } from "@/types/api";
import type {
  Project,
  Revision,
  RevisionKind,
  Workspace,
} from "@/types/revisions";

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function createProject(name: string): Project {
  const workspace = createWorkspace("Workspace 1");
  return {
    id: newId(),
    name,
    workspaces: [workspace],
    activeWorkspaceId: workspace.id,
  };
}

export function createWorkspace(name: string): Workspace {
  return {
    id: newId(),
    name,
    revisions: [],
    activeRevisionId: null,
    viewerCleared: false,
  };
}

export function getActiveWorkspace(project: Project): Workspace {
  const found = project.workspaces.find((w) => w.id === project.activeWorkspaceId);
  return found ?? project.workspaces[0];
}

export function getActiveRevision(workspace: Workspace): Revision | null {
  if (workspace.activeRevisionId === null) return null;
  return workspace.revisions.find((r) => r.id === workspace.activeRevisionId) ?? null;
}

/** Append a new workspace and switch to it. Existing workspaces untouched. */
export function addWorkspace(project: Project, name: string): Project {
  const workspace = createWorkspace(name);
  return {
    ...project,
    workspaces: [...project.workspaces, workspace],
    activeWorkspaceId: workspace.id,
  };
}

export function switchWorkspace(project: Project, workspaceId: string): Project {
  if (!project.workspaces.some((w) => w.id === workspaceId)) return project;
  return { ...project, activeWorkspaceId: workspaceId };
}

/**
 * Append a successful generate/modify result as a new revision.
 * Parent = previously active revision (null for the first one).
 * Any clear-viewer flag is lifted: there is something to show again.
 */
export function appendRevision(
  project: Project,
  kind: RevisionKind,
  prompt: string,
  response: GenerateResponse,
  createdAt: string = nowIso(),
): Project {
  const active = getActiveWorkspace(project);
  const revision: Revision = {
    id: newId(),
    parentId: active.activeRevisionId,
    kind,
    prompt,
    response,
    createdAt,
  };
  return {
    ...project,
    workspaces: project.workspaces.map((w) =>
      w.id === active.id
        ? {
            ...w,
            revisions: [...w.revisions, revision],
            activeRevisionId: revision.id,
            viewerCleared: false,
          }
        : w,
    ),
  };
}

/** Hide the display; revisions, workspaces, and project are preserved. */
export function clearViewer(project: Project): Project {
  const active = getActiveWorkspace(project);
  return {
    ...project,
    workspaces: project.workspaces.map((w) =>
      w.id === active.id ? { ...w, viewerCleared: true } : w,
    ),
  };
}

/** Re-view a historical revision (read-only time travel). */
export function selectRevision(project: Project, revisionId: string): Project {
  const active = getActiveWorkspace(project);
  if (!active.revisions.some((r) => r.id === revisionId)) return project;
  return {
    ...project,
    workspaces: project.workspaces.map((w) =>
      w.id === active.id
        ? { ...w, activeRevisionId: revisionId, viewerCleared: false }
        : w,
    ),
  };
}

/** Revision selected for display, or null when the viewer should be empty. */
export function visibleRevision(workspace: Workspace): Revision | null {
  if (workspace.viewerCleared) return null;
  return getActiveRevision(workspace);
}
