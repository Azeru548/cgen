/** Project → Workspace → Revision state model (phase 1, frontend-only).
 *
 *  No backend changes: every backend response (GenerateResponse) is already
 *  self-contained (CAD spec + STEP/STL download URLs), so a Revision simply
 *  stores the response plus lineage metadata. Revisions are append-only —
 *  generate/modify NEVER overwrite or delete previous entries.
 *
 *  Ephemeral-file caveat: backend download links expire (1h TTL, dead on
 *  restart). Old revisions always keep their specs; their file links may
 *  404 with "expired, re-run" surfaced through the existing error path.
 */
import type { GenerateResponse } from "@/types/api";

export type RevisionKind = "generate" | "modify" | "adjust" | "assemble";

export interface Revision {
  id: string;
  parentId: string | null;
  kind: RevisionKind;
  /** Prompt (generate) or instruction (modify) that produced this revision. */
  prompt: string;
  response: GenerateResponse;
  createdAt: string;
}

export interface Workspace {
  id: string;
  name: string;
  /** Append-only: entries are never mutated or removed. */
  revisions: Revision[];
  activeRevisionId: string | null;
  /** Clear Viewer hides the display without deleting anything. */
  viewerCleared: boolean;
}

export interface Project {
  id: string;
  name: string;
  workspaces: Workspace[];
  activeWorkspaceId: string;
}
