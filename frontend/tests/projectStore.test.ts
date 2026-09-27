/** M11: Firestore project persistence, tested without a real Firebase project.
 *
 *  The Firestore SDK is mocked at the module boundary: these tests exercise
 *  cgen's document layout and write behaviour, not Google's client. The fake
 *  store records writes and serves seeded documents.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Firestore } from "firebase/firestore";
import {
  appendRevisions,
  createProjectRecord,
  loadProject,
  listProjects,
  saveProjectShell,
  serialFor,
} from "../lib/projectStore";
import { appendRevision, createProject, createWorkspace } from "../lib/revisions";
import type { GenerateResponse } from "@/types/api";
import type { Project } from "@/types/revisions";

interface SeedDoc {
  id: string;
  data: Record<string, unknown>;
}

const seed = new Map<string, SeedDoc>();
const writes: { op: string; path: string; data: Record<string, unknown> }[] = [];

type Ref = { __path: string };
type Query = { __prefix: string };

async function fakeGetDoc(ref: Ref) {
  const found = seed.get(ref.__path);
  return {
    exists: () => found !== undefined,
    id: found?.id ?? ref.__path,
    data: () => found?.data ?? {},
  };
}

async function fakeGetDocs(q: Query) {
  const prefix = `${q.__prefix}/`;
  return {
    docs: [...seed.entries()]
      .filter(([path]) => path.startsWith(prefix))
      .filter(([path]) => !path.slice(prefix.length).includes("/"))
      .map(([, doc]) => ({ id: doc.id, data: () => doc.data })),
  };
}

function fakeBatch() {
  const pending: { ref: Ref; data: Record<string, unknown> }[] = [];
  return {
    set: (ref: Ref, data: Record<string, unknown>) => {
      pending.push({ ref, data });
    },
    commit: async () => {
      pending.forEach(({ ref, data }) => {
        writes.push({ op: "set", path: ref.__path, data });
      });
    },
  };
}

vi.mock("firebase/firestore", () => ({
  /* Mirrors both SDK overloads: doc(db, ...segments) and doc(collectionRef, id). */
  doc: (first: unknown, ...rest: string[]) => {
    if (first && typeof first === "object" && "__prefix" in first) {
      return { __path: `${(first as Query).__prefix}/${rest.join("/")}` };
    }
    return { __path: rest.join("/") };
  },
  collection: (_db: unknown, ...segments: string[]) => ({
    __prefix: segments.join("/"),
  }),
  getDoc: fakeGetDoc,
  getDocs: fakeGetDocs,
  orderBy: () => ({}),
  query: (ref: Query) => ref,
  setDoc: async (ref: Ref, data: Record<string, unknown>) => {
    writes.push({ op: "set", path: ref.__path, data });
  },
  updateDoc: async (ref: Ref, data: Record<string, unknown>) => {
    writes.push({ op: "update", path: ref.__path, data });
  },
  writeBatch: () => fakeBatch(),
}));

const db = {} as Firestore;

/** Seed the fake store so a project can be read back. */
function seedProject(project: Project) {
  seed.set(`users/u1/projects/${project.id}`, {
    id: project.id,
    data: {
      name: project.name,
      serial: serialFor(project.id),
      activeWorkspaceId: project.activeWorkspaceId,
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-02T00:00:00.000Z",
      workspaceCount: project.workspaces.length,
      revisionCount: 1,
    },
  });
  project.workspaces.forEach((workspace, index) => {
    seed.set(
      `users/u1/projects/${project.id}/workspaces/${workspace.id}`,
      {
        id: workspace.id,
        data: {
          name: workspace.name,
          order: index,
          activeRevisionId: workspace.activeRevisionId,
          viewerCleared: workspace.viewerCleared,
          createdAt: "2026-01-01T00:00:00.000Z",
          updatedAt: "2026-01-01T00:00:00.000Z",
        },
      },
    );
    workspace.revisions.forEach((revision, order) => {
      seed.set(
        `users/u1/projects/${project.id}/workspaces/${workspace.id}/revisions/${revision.id}`,
        {
          id: revision.id,
          data: {
            parentId: revision.parentId,
            kind: revision.kind,
            prompt: revision.prompt,
            response: revision.response,
            createdAt: revision.createdAt,
            order,
          },
        },
      );
    });
  });
}

const RESPONSE = {
  status: "completed",
  request_id: "req-1",
  specification: { document_type: "3d_part", units: "mm", name: "cube" },
  units: "mm",
  generation_time_ms: 10,
  files: {
    step: {
      format: "step",
      filename: "cube.step",
      bytes: 10,
      download_url: "/artifacts/req-1/cube.step",
    },
    stl: {
      format: "stl",
      filename: "cube.stl",
      bytes: 20,
      download_url: "/artifacts/req-1/cube.stl",
    },
  },
} as unknown as GenerateResponse;

beforeEach(() => {
  seed.clear();
  writes.length = 0;
});

describe("serialFor", () => {
  it("is stable and WS-### shaped", () => {
    expect(serialFor("abc-123")).toBe(serialFor("abc-123"));
    expect(serialFor("abc-123")).toMatch(/^WS-\d{3}$/);
  });

  it("differs for different ids", () => {
    expect(serialFor("a")).not.toBe(serialFor("b"));
  });
});

describe("createProjectRecord", () => {
  it("writes the project shell and one workspace doc", async () => {
    const project = createProject("Bench");
    await createProjectRecord(db, "u1", project);

    const paths = writes.map((w) => w.path);
    expect(paths).toContain(`users/u1/projects/${project.id}`);
    expect(paths).toContain(
      `users/u1/projects/${project.id}/workspaces/${project.workspaces[0].id}`,
    );
    const shell = writes.find((w) => w.path === `users/u1/projects/${project.id}`);
    expect(shell?.data.serial).toBe(serialFor(project.id));
  });

  it("keys everything under the caller's uid", async () => {
    await createProjectRecord(db, "user-42", createProject("Bench"));
    expect(writes.every((w) => w.path.startsWith("users/user-42/"))).toBe(true);
  });
});

describe("loadProject", () => {
  it("reassembles the reducer's Project shape", async () => {
    const withRevision = appendRevision(
      createProject("Bench"),
      "generate",
      "a cube",
      RESPONSE,
    );
    seedProject(withRevision);

    const loaded = await loadProject(db, "u1", withRevision.id);
    expect(loaded).not.toBeNull();
    expect(loaded?.name).toBe("Bench");
    expect(loaded?.workspaces).toHaveLength(1);
    expect(loaded?.workspaces[0].revisions).toHaveLength(1);
    expect(loaded?.workspaces[0].revisions[0].kind).toBe("generate");
    expect(loaded?.workspaces[0].revisions[0].response.request_id).toBe("req-1");
    expect(loaded?.activeWorkspaceId).toBe(withRevision.workspaces[0].id);
  });

  it("returns null for a missing project", async () => {
    expect(await loadProject(db, "u1", "nope")).toBeNull();
  });

  it("falls back to the first workspace when the active id is stale", async () => {
    const base = createProject("Bench");
    seedProject(base);
    const doc = seed.get(`users/u1/projects/${base.id}`);
    if (doc) doc.data.activeWorkspaceId = "deleted-ws";

    const loaded = await loadProject(db, "u1", base.id);
    expect(loaded?.activeWorkspaceId).toBe(base.workspaces[0].id);
  });

  it("returns null when the project has no workspaces", async () => {
    const base = createProject("Bench");
    seedProject(base);
    seed.delete(
      `users/u1/projects/${base.id}/workspaces/${base.workspaces[0].id}`,
    );
    expect(await loadProject(db, "u1", base.id)).toBeNull();
  });
});

describe("listProjects", () => {
  it("maps project docs to summaries", async () => {
    const base = createProject("Bench");
    seedProject(base);
    const list = await listProjects(db, "u1");
    expect(list).toHaveLength(1);
    expect(list[0].name).toBe("Bench");
    expect(list[0].serial).toBe(serialFor(base.id));
    expect(list[0].workspaceCount).toBe(1);
  });
});

describe("saveProjectShell", () => {
  it("updates pointers without writing revisions", async () => {
    const project = createProject("Bench");
    await saveProjectShell(db, "u1", project);
    expect(writes.some((w) => w.path.includes("/revisions/"))).toBe(false);
  });

  it("records the newly active workspace", async () => {
    const project = createProject("Bench");
    const second = createWorkspace("Workspace 2");
    const updated: Project = {
      ...project,
      workspaces: [...project.workspaces, second],
      activeWorkspaceId: second.id,
    };
    await saveProjectShell(db, "u1", updated);
    const shell = writes.find((w) => w.path === `users/u1/projects/${updated.id}`);
    expect(shell?.data.activeWorkspaceId).toBe(second.id);
  });
});

describe("appendRevisions", () => {
  it("writes a new revision and reports it", async () => {
    const withRevision = appendRevision(
      createProject("Bench"),
      "generate",
      "a cube",
      RESPONSE,
    );
    const added = await appendRevisions(db, "u1", withRevision, new Set());
    expect(added).toHaveLength(1);
    expect(writes).toHaveLength(1);
    expect(writes[0].path).toContain("/revisions/");
  });

  it("never rewrites an already-persisted revision", async () => {
    const withRevision = appendRevision(
      createProject("Bench"),
      "generate",
      "a cube",
      RESPONSE,
    );
    const existing = new Set([withRevision.workspaces[0].revisions[0]!.id]);
    const added = await appendRevisions(db, "u1", withRevision, existing);
    expect(added).toHaveLength(0);
    expect(writes).toHaveLength(0);
  });

  it("appends only the new revision on a second generate", async () => {
    const first = appendRevision(createProject("Bench"), "generate", "cube", RESPONSE);
    const firstId = first.workspaces[0].revisions[0]!.id;
    const second = appendRevision(first, "modify", "make it round", RESPONSE);

    const added = await appendRevisions(db, "u1", second, new Set([firstId]));
    expect(added).toHaveLength(1);
    expect(writes).toHaveLength(1);
    const written = writes[0].data;
    expect(written.kind).toBe("modify");
    expect(written.prompt).toBe("make it round");
    expect(written.parentId).toBe(firstId);
  });
});
