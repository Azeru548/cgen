/** Firestore persistence for Project → Workspace → Revision (M11).
 *
 *  Layout — one collection per level so a long session never rewrites history:
 *
 *    users/{uid}/projects/{projectId}
 *    users/{uid}/projects/{projectId}/workspaces/{workspaceId}
 *    users/{uid}/projects/{projectId}/workspaces/{workspaceId}/revisions/{revisionId}
 *
 *  The project document holds only the shell (name + which workspace is
 *  active); each workspace document holds its lineage pointers; revisions are
 *  append-only documents. `loadProject` reassembles exactly the `Project`
 *  shape that `lib/revisions.ts` already produces, so the reducers and the
 *  existing 61 unit tests keep working unchanged.
 *
 *  Access control is enforced by `firestore.rules`, not here: a document path
 *  is always built from the signed-in uid, and a caller cannot ask this module
 *  to read or write another user's data.
 */
import {
  collection,
  doc,
  getDoc,
  getDocs,
  orderBy,
  query,
  updateDoc,
  writeBatch,
  type Firestore,
} from "firebase/firestore";
import type { Project, Revision, Workspace } from "@/types/revisions";
import type { RevisionKind } from "@/types/revisions";
import type { GenerateResponse } from "@/types/api";
import { nowIso } from "@/lib/revisions";

export interface ProjectSummary {
  id: string;
  name: string;
  /** Serial shown on the nameplate, e.g. WS-042. */
  serial: string;
  createdAt: string;
  updatedAt: string;
  workspaceCount: number;
  revisionCount: number;
}

interface ProjectDoc {
  name: string;
  serial: string;
  activeWorkspaceId: string;
  createdAt: string;
  updatedAt: string;
  /** Denormalized counts so the home list needs no fan-out reads. */
  workspaceCount?: number;
  revisionCount?: number;
}

interface WorkspaceDoc {
  name: string;
  order: number;
  activeRevisionId: string | null;
  viewerCleared: boolean;
  createdAt: string;
  updatedAt: string;
}

interface RevisionDoc {
  parentId: string | null;
  kind: RevisionKind;
  prompt: string;
  response: GenerateResponse;
  createdAt: string;
  order: number;
}

function projectDocRef(db: Firestore, uid: string, projectId: string) {
  return doc(db, "users", uid, "projects", projectId);
}

function workspacesCol(db: Firestore, uid: string, projectId: string) {
  return collection(db, "users", uid, "projects", projectId, "workspaces");
}

function workspaceDocRef(
  db: Firestore,
  uid: string,
  projectId: string,
  workspaceId: string,
) {
  return doc(db, "users", uid, "projects", projectId, "workspaces", workspaceId);
}

function revisionsCol(
  db: Firestore,
  uid: string,
  projectId: string,
  workspaceId: string,
) {
  return collection(
    db,
    "users",
    uid,
    "projects",
    projectId,
    "workspaces",
    workspaceId,
    "revisions",
  );
}

/** WS-### serial derived from the project id, so it is stable across loads. */
export function serialFor(projectId: string): string {
  let hash = 0;
  for (let i = 0; i < projectId.length; i += 1) {
    hash = (hash * 31 + projectId.charCodeAt(i)) % 1000;
  }
  return `WS-${String(hash).padStart(3, "0")}`;
}

/** List the signed-in user's projects, newest first. */
export async function listProjects(
  db: Firestore,
  uid: string,
): Promise<ProjectSummary[]> {
  const snapshot = await getDocs(
    query(collection(db, "users", uid, "projects"), orderBy("updatedAt", "desc")),
  );
  return snapshot.docs.map((entry) => {
    const data = entry.data() as ProjectDoc;
    return {
      id: entry.id,
      name: data.name,
      serial: data.serial,
      createdAt: data.createdAt,
      updatedAt: data.updatedAt,
      workspaceCount: data.workspaceCount ?? 1,
      revisionCount: data.revisionCount ?? 0,
    };
  });
}

/** Read one project back into the reducer's `Project` shape. */
export async function loadProject(
  db: Firestore,
  uid: string,
  projectId: string,
): Promise<Project | null> {
  const projectSnap = await getDoc(projectDocRef(db, uid, projectId));
  if (!projectSnap.exists()) return null;
  const project = projectSnap.data() as ProjectDoc;

  const workspaceSnaps = await getDocs(
    query(workspacesCol(db, uid, projectId), orderBy("order", "asc")),
  );
  const workspaces: Workspace[] = [];
  for (const workspaceSnap of workspaceSnaps.docs) {
    const meta = workspaceSnap.data() as WorkspaceDoc;
    const revisionSnaps = await getDocs(
      query(revisionsCol(db, uid, projectId, workspaceSnap.id), orderBy("order", "asc")),
    );
    const revisions: Revision[] = revisionSnaps.docs.map((entry) => {
      const data = entry.data() as RevisionDoc;
      return {
        id: entry.id,
        parentId: data.parentId,
        kind: data.kind,
        prompt: data.prompt,
        response: data.response,
        createdAt: data.createdAt,
      };
    });
    workspaces.push({
      id: workspaceSnap.id,
      name: meta.name,
      revisions,
      activeRevisionId: meta.activeRevisionId,
      viewerCleared: meta.viewerCleared,
    });
  }
  if (workspaces.length === 0) return null;
  const activeWorkspaceId = workspaces.some(
    (workspace) => workspace.id === project.activeWorkspaceId,
  )
    ? project.activeWorkspaceId
    : workspaces[0].id;
  return {
    id: projectSnap.id,
    name: project.name,
    workspaces,
    activeWorkspaceId,
  };
}

/** Create the project shell plus its first workspace. */
export async function createProjectRecord(
  db: Firestore,
  uid: string,
  project: Project,
): Promise<void> {
  const now = nowIso();
  const batch = writeBatch(db);
  batch.set(projectDocRef(db, uid, project.id), {
    name: project.name,
    serial: serialFor(project.id),
    activeWorkspaceId: project.activeWorkspaceId,
    workspaceCount: project.workspaces.length,
    revisionCount: 0,
    createdAt: now,
    updatedAt: now,
  } satisfies ProjectDoc);
  project.workspaces.forEach((workspace, index) => {
    batch.set(workspaceDocRef(db, uid, project.id, workspace.id), {
      name: workspace.name,
      order: index,
      activeRevisionId: workspace.activeRevisionId,
      viewerCleared: workspace.viewerCleared,
      createdAt: now,
      updatedAt: now,
    } satisfies WorkspaceDoc);
  });
  await batch.commit();
}

/** Persist workspace/active state. Revisions are never touched here. */
export async function saveProjectShell(
  db: Firestore,
  uid: string,
  project: Project,
): Promise<void> {
  const now = nowIso();
  const batch = writeBatch(db);
  batch.set(
    projectDocRef(db, uid, project.id),
    {
      name: project.name,
      serial: serialFor(project.id),
      activeWorkspaceId: project.activeWorkspaceId,
      workspaceCount: project.workspaces.length,
      updatedAt: now,
    },
    { merge: true },
  );
  project.workspaces.forEach((workspace, index) => {
    batch.set(
      workspaceDocRef(db, uid, project.id, workspace.id),
      {
        name: workspace.name,
        order: index,
        activeRevisionId: workspace.activeRevisionId,
        viewerCleared: workspace.viewerCleared,
        updatedAt: now,
      },
      { merge: true },
    );
  });
  await batch.commit();
}

/**
 * Append revisions that are not stored yet.
 *
 * `knownRevisionIds` is the set the caller has already persisted, so an
 * existing revision is never rewritten (revisions are append-only) and a new
 * one costs a single write.
 */
export async function appendRevisions(
  db: Firestore,
  uid: string,
  project: Project,
  knownRevisionIds: ReadonlySet<string>,
): Promise<string[]> {
  const added: string[] = [];
  const batch = writeBatch(db);
  for (const workspace of project.workspaces) {
    for (const revision of workspace.revisions) {
      if (knownRevisionIds.has(revision.id)) continue;
      batch.set(
        doc(revisionsCol(db, uid, project.id, workspace.id), revision.id),
        {
          parentId: revision.parentId,
          kind: revision.kind,
          prompt: revision.prompt,
          response: revision.response,
          createdAt: revision.createdAt,
          order: workspace.revisions.indexOf(revision),
        } satisfies RevisionDoc,
      );
      added.push(revision.id);
    }
  }
  if (added.length > 0) await batch.commit();
  return added;
}

/** Bump the shell's updatedAt after writes land. */
export async function touchProject(
  db: Firestore,
  uid: string,
  projectId: string,
): Promise<void> {
  await updateDoc(projectDocRef(db, uid, projectId), { updatedAt: nowIso() });
}
