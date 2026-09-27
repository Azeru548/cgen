/** M11: the project <-> Firestore sync hook.
 *
 * React is exercised for real; Firebase and the project store are mocked at
 * the module boundary. What matters here is the behaviour contract:
 * guests are untouched, a signed-in user's project loads once, revisions are
 * appended, and the shell is saved.
 */
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { createProject } from "../lib/revisions";
import type { Project } from "@/types/revisions";

/* vi.mock is hoisted, so the store doubles must be created in vi.hoisted. */
const { projectStore, authState } = vi.hoisted(() => ({
  projectStore: {
    listProjects: vi.fn(),
    loadProject: vi.fn(),
    createProjectRecord: vi.fn(),
    appendRevisions: vi.fn(),
    saveProjectShell: vi.fn(),
  },
  authState: { status: "signed-out" as string, uid: null as string | null },
}));

vi.mock("firebase/firestore", () => ({
  doc: () => ({ __path: "x" }),
  collection: () => ({ __prefix: "x" }),
  getDoc: vi.fn(),
  getDocs: vi.fn(),
  orderBy: () => ({}),
  query: (r: unknown) => r,
  setDoc: vi.fn(),
  updateDoc: vi.fn(),
  writeBatch: () => ({ set: vi.fn(), commit: vi.fn() }),
}));

vi.mock("../lib/projectStore", () => projectStore);

vi.mock("../components/AuthProvider", () => ({
  useAuth: () => ({ status: authState.status, uid: authState.uid }),
}));

import { useProjectSync } from "../hooks/useProjectSync";

const RESPONSE = {
  status: "completed",
  request_id: "r1",
  specification: { document_type: "3d_part", units: "mm", name: "p" },
  units: "mm",
  generation_time_ms: 1,
  files: {
    step: { format: "step", filename: "p.step", bytes: 1, download_url: "/a" },
    stl: { format: "stl", filename: "p.stl", bytes: 1, download_url: "/a" },
  },
} as never;

/* Stable identity: the real `useFirestore()` memoizes its instance, and the
 * hook keys its effects on the db reference. */
const FAKE_DB = {} as never;

/* Stateful harness: `setProject` really applies, exactly as in page.tsx. */
function Harness({ initial }: { initial: Project }) {
  const [project, setProject] = useState<Project>(initial);
  useProjectSync(project, setProject, FAKE_DB);
  return <div data-testid="harness" data-project-id={project.id} />;
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  authState.status = "signed-out";
  authState.uid = null;
  projectStore.listProjects.mockReset().mockResolvedValue([]);
  projectStore.loadProject.mockReset().mockResolvedValue(null);
  projectStore.createProjectRecord.mockReset().mockResolvedValue(undefined);
  projectStore.appendRevisions.mockReset().mockResolvedValue([]);
  projectStore.saveProjectShell.mockReset().mockResolvedValue(undefined);
});

describe("useProjectSync as a guest", () => {
  it("does not touch Firestore when signed out", async () => {
    const project = createProject("Bench");
    render(<Harness initial={project} />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(projectStore.listProjects).not.toHaveBeenCalled();
    expect(projectStore.createProjectRecord).not.toHaveBeenCalled();
    expect(projectStore.saveProjectShell).not.toHaveBeenCalled();
  });
});

describe("useProjectSync when signed in", () => {
  beforeEach(() => {
    authState.status = "signed-in";
    authState.uid = "u1";
  });

  it("creates a first project when the user has none", async () => {
    render(<Harness initial={createProject("Bench")} />);
    await waitFor(() => expect(projectStore.createProjectRecord).toHaveBeenCalled());
    expect(projectStore.createProjectRecord.mock.calls[0]?.[1]).toBe("u1");
    expect(projectStore.loadProject).not.toHaveBeenCalled();
  });

  it("loads the most recent project instead of overwriting it", async () => {
    const existing = { ...createProject("Old"), id: "p-old" };
    projectStore.listProjects.mockResolvedValue([
      { id: "p-old", name: "Old", serial: "WS-001", createdAt: "", updatedAt: "", workspaceCount: 1, revisionCount: 0 },
    ]);
    projectStore.loadProject.mockResolvedValue(existing);

    render(<Harness initial={createProject("New")} />);
    await waitFor(() => expect(projectStore.loadProject).toHaveBeenCalled());
    expect(projectStore.createProjectRecord).not.toHaveBeenCalled();
  });

  it("persists the shell and appends revisions after hydration", async () => {
    const project = createProject("Bench");
    render(<Harness initial={project} />);
    await waitFor(() => expect(projectStore.createProjectRecord).toHaveBeenCalled());
    // Writes are debounced, so allow for the flush timer.
    await waitFor(() => expect(projectStore.appendRevisions).toHaveBeenCalled(), {
      timeout: 3000,
    });
    expect(projectStore.appendRevisions.mock.calls[0]?.[1]).toBe("u1");
    await waitFor(() => expect(projectStore.saveProjectShell).toHaveBeenCalled(), {
      timeout: 3000,
    });
  });

  it("marks loaded revisions as known so history is never rewritten", async () => {
    const loaded = createProject("Old");
    const withRevision = {
      ...loaded,
      workspaces: loaded.workspaces.map((w) => ({
        ...w,
        revisions: [
          {
            id: "rev-1",
            parentId: null,
            kind: "generate" as const,
            prompt: "cube",
            response: RESPONSE,
            createdAt: "2026-01-01T00:00:00.000Z",
          },
        ],
        activeRevisionId: "rev-1",
      })),
    };
    projectStore.listProjects.mockResolvedValue([
      { id: loaded.id, name: "Old", serial: "WS-001", createdAt: "", updatedAt: "", workspaceCount: 1, revisionCount: 1 },
    ]);
    /* A real load builds a new object; returning the same reference would make
     * React bail out of the state update. */
    projectStore.loadProject.mockResolvedValue({
      ...withRevision,
      workspaces: withRevision.workspaces.map((w) => ({ ...w })),
    });

    render(<Harness initial={withRevision} />);
    await waitFor(
      () => expect(projectStore.appendRevisions).toHaveBeenCalled(),
      { timeout: 3000 },
    );
    const known = projectStore.appendRevisions.mock.calls[0]?.[3] as Set<string>;
    expect(known.has("rev-1")).toBe(true);
  });

  it("survives a store failure without throwing", async () => {
    projectStore.listProjects.mockRejectedValue(new Error("offline"));
    render(<Harness initial={createProject("Bench")} />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(screen.getByTestId("harness")).toBeTruthy();
  });
});
