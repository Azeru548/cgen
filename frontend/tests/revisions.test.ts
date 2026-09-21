import { describe, expect, it } from "vitest";
import {
  addWorkspace,
  appendRevision,
  clearViewer,
  createProject,
  getActiveWorkspace,
  selectRevision,
  visibleRevision,
} from "../lib/revisions";
import type { GenerateResponse } from "../types/api";

function response(name: string, requestId: string): GenerateResponse {
  return {
    status: "completed",
    request_id: requestId,
    specification: {
      document_type: "3d_part",
      units: "mm",
      name,
      operation: { type: "box", width: 100, depth: 60, height: 20 },
    },
    units: "mm",
    generation_time_ms: 5,
    files: {
      step: {
        format: "step",
        filename: `${name}.step`,
        bytes: 100,
        download_url: `/download/${requestId}?format=step`,
      },
      stl: {
        format: "stl",
        filename: `${name}.stl`,
        bytes: 200,
        download_url: `/download/${requestId}?format=stl`,
      },
    },
  };
}

describe("adjust revisions", () => {
  it("appends an adjust revision parented to the active revision", () => {
    let project = createProject("Bracket");
    project = appendRevision(project, "generate", "box", response("box", "r1"));
    project = appendRevision(project, "adjust", "Adjusted width 100 → 120 mm", response("box", "r2"));
    const workspace = getActiveWorkspace(project);
    expect(workspace.revisions.map((r) => r.kind)).toEqual(["generate", "adjust"]);
    expect(workspace.revisions[1].parentId).toBe(workspace.revisions[0].id);
    expect(workspace.activeRevisionId).toBe(workspace.revisions[1].id);
    expect(visibleRevision(workspace)?.response.request_id).toBe("r2");
  });

  it("branches an adjustment off an older revision without touching siblings", () => {
    let project = createProject("Bracket");
    project = appendRevision(project, "generate", "box", response("box", "r1"));
    project = appendRevision(project, "modify", "taller", response("box", "r2"));
    project = appendRevision(project, "modify", "wider", response("box", "r3"));
    const workspace = getActiveWorkspace(project);
    project = selectRevision(project, workspace.revisions[0].id);
    project = appendRevision(project, "adjust", "Adjusted width 100 → 120 mm", response("box", "r4"));
    const next = getActiveWorkspace(project);
    expect(next.revisions).toHaveLength(4);
    expect(next.revisions[3].parentId).toBe(next.revisions[0].id);
    expect(next.revisions[1].response.request_id).toBe("r2");
    expect(next.revisions[2].response.request_id).toBe("r3");
  });

  it("clearViewer preserves every revision", () => {
    let project = createProject("Bracket");
    project = appendRevision(project, "generate", "box", response("box", "r1"));
    project = appendRevision(project, "adjust", "Adjusted width 100 → 120 mm", response("box", "r2"));
    project = clearViewer(project);
    const workspace = getActiveWorkspace(project);
    expect(workspace.revisions).toHaveLength(2);
    expect(visibleRevision(workspace)).toBeNull();
  });

  it("new workspaces start empty while history survives elsewhere", () => {
    let project = createProject("Bracket");
    project = appendRevision(project, "generate", "box", response("box", "r1"));
    project = addWorkspace(project, "Workspace 2");
    expect(getActiveWorkspace(project).revisions).toHaveLength(0);
    expect(project.workspaces[0].revisions).toHaveLength(1);
  });
});
