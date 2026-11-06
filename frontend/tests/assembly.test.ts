import { describe, expect, it } from "vitest";
import {
  applyPlacementToResponse,
  bakeDisplayedScene,
  expandSelectionToGroups,
  groupSelection,
  isAssemblySpec,
  isPartSpec,
  posesOf,
  promoteResponseToAssembly,
  removeComponentFromResponse,
  rotateSelection,
  sceneObjects,
  setSelectionLocked,
  ungroupSelection,
  withComponentPatch,
} from "../lib/assembly";
import type {
  AssemblySpecification,
  CadSpecification,
  CatalogComponent,
  GenerateResponse,
} from "../types/api";

const PART: CadSpecification = {
  document_type: "3d_part",
  units: "mm",
  name: "block",
  operation: { type: "box", width: 100, depth: 60, height: 30 },
};

const ASSEMBLY: AssemblySpecification = {
  document_type: "3d_assembly",
  units: "mm",
  name: "arduino_enclosure",
  schema_version: "4.0",
  components: [
    {
      id: "arduino_1",
      component_type: "arduino_uno",
      name: "Arduino Uno",
      parameters: {},
      transform: { position: [0, 0, 8], rotation: [0, 0, 0] },
      visible: true,
      instances: [],
      relationships: [],
    },
    {
      id: "screws_1",
      component_type: "m3_screw",
      name: "M3 screws",
      parameters: { length: 12 },
      transform: { position: [0, 0, 0], rotation: [0, 0, 0] },
      visible: true,
      instances: [
        { position: [-19, 24, 0.8], rotation: [0, 0, 0] },
        { position: [31, 8, 0.8], rotation: [0, 0, 0] },
        { position: [31, -19, 0.8], rotation: [0, 0, 0] },
        { position: [-20, -24, 0.8], rotation: [0, 0, 0] },
      ],
      relationships: [{ type: "mounted_on", target_id: "arduino_1" }],
    },
  ],
};

const CATALOG: CatalogComponent[] = [
  {
    type: "arduino_uno",
    category: "electronics",
    display_name: "Arduino Uno",
    description: "",
    insertable: true,
    parameterized: false,
    has_mounting_points: true,
    parameters: [],
  },
  {
    type: "m3_screw",
    category: "fasteners",
    display_name: "M3 Screw",
    description: "",
    insertable: true,
    parameterized: true,
    has_mounting_points: false,
    parameters: [
      {
        key: "length",
        label: "Length",
        kind: "length",
        default: 12,
        min: 4,
        max: 80,
        options: null,
        unit: "mm",
        description: "",
      },
    ],
  },
];

function response(spec: CadSpecification | AssemblySpecification): GenerateResponse {
  return {
    status: "completed",
    request_id: "r1",
    specification: spec,
    units: "mm",
    generation_time_ms: 10,
    files: {
      step: { format: "step", filename: "a.step", bytes: 1, download_url: "/download/t?format=step" },
      stl: { format: "stl", filename: "a.stl", bytes: 2, download_url: "/download/t?format=stl" },
    },
    component_files: isAssemblySpec(spec)
      ? {
          arduino_1: {
            step: { format: "step", filename: "a.step", bytes: 1, download_url: "/download/a?format=step" },
            stl: { format: "stl", filename: "a.stl", bytes: 2, download_url: "/download/a?format=stl" },
          },
          screws_1: {
            step: { format: "step", filename: "s.step", bytes: 1, download_url: "/download/s?format=step" },
            stl: { format: "stl", filename: "s.stl", bytes: 2, download_url: "/download/s?format=stl" },
          },
        }
      : undefined,
  };
}

describe("assembly scene", () => {
  it("wraps a single part as one scene object", () => {
    const objects = sceneObjects(response(PART), (u) => `http://x${u}`, []);
    expect(objects).toHaveLength(1);
    expect(objects[0].id).toBe("generated_1");
    expect(objects[0].stlUrl).toContain("/download/t");
  });

  it("keeps assembly objects separately selectable", () => {
    const objects = sceneObjects(response(ASSEMBLY), (u) => `http://x${u}`, CATALOG);
    expect(objects.map((o) => o.id)).toEqual(["arduino_1", "screws_1"]);
    expect(objects[1].instances).toHaveLength(4);
    expect(objects[0].stlUrl).toContain("/download/a");
  });

  it("one definition yields multiple instance poses", () => {
    expect(posesOf(ASSEMBLY.components[1])).toHaveLength(4);
    expect(posesOf(ASSEMBLY.components[0])).toHaveLength(1);
  });

  it("draft visibility does not rewrite the committed spec until patched", () => {
    const next = withComponentPatch(ASSEMBLY, "arduino_1", { visible: false });
    expect(ASSEMBLY.components[0].visible).toBe(true);
    expect(next.components[0].visible).toBe(false);
    expect(next.components[1].visible).toBe(true);
  });

  it("distinguishes part and assembly documents", () => {
    expect(isPartSpec(PART)).toBe(true);
    expect(isAssemblySpec(ASSEMBLY)).toBe(true);
    expect(isPartSpec(ASSEMBLY)).toBe(false);
  });
});

describe("groups and rotation", () => {
  it("groups two loose components and refuses a second membership", () => {
    const grouped = groupSelection(ASSEMBLY, ["arduino_1", "screws_1"], "Board");
    expect(grouped).not.toBeNull();
    expect(grouped?.schema_version).toBe("4.1");
    expect(grouped?.groups).toEqual([
      {
        id: "group_1",
        name: "Board",
        component_ids: ["arduino_1", "screws_1"],
      },
    ]);
    expect(groupSelection(grouped!, ["arduino_1", "screws_1"], "Again")).toBeNull();
  });

  it("ungroups by overlapping selection", () => {
    const grouped = groupSelection(ASSEMBLY, ["arduino_1", "screws_1"], "Board");
    const next = ungroupSelection(grouped!, ["screws_1"]);
    expect(next?.groups).toEqual([]);
  });

  it("rotates a pair about their centroid", () => {
    const pair: AssemblySpecification = {
      ...ASSEMBLY,
      components: [
        {
          ...ASSEMBLY.components[0],
          transform: { position: [10, 0, 0], rotation: [0, 0, 0] },
        },
        {
          ...ASSEMBLY.components[1],
          transform: { position: [-10, 0, 0], rotation: [0, 0, 0] },
          instances: [],
        },
      ],
    };
    const next = rotateSelection(pair, ["arduino_1", "screws_1"], [0, 0, 90]);
    expect(next).not.toBeNull();
    expect(next?.components[0].transform.position).toEqual([0, 10, 0]);
    expect(next?.components[1].transform.position).toEqual([0, -10, 0]);
    expect(next?.components[0].transform.rotation[2]).toBe(90);
    expect(next?.components[1].transform.rotation[2]).toBe(90);
  });

  it("locks the scene as displayed instead of snapping to the committed pose", () => {
    // The user drags the board but has not pressed Apply yet.
    const committed = response(ASSEMBLY);
    const dragged = applyPlacementToResponse(committed, "arduino_1", {
      transform: { position: [40, -12, 9], rotation: [0, 0, 30] },
    })!;
    const displayed = sceneObjects(dragged, (path) => path, []);

    const baked = bakeDisplayedScene(committed, displayed);
    const spec = baked.specification;
    if (!isAssemblySpec(spec)) throw new Error("expected an assembly");
    const locked = setSelectionLocked(spec, ["arduino_1"], true)!;
    const board = locked.components.find((c) => c.id === "arduino_1")!;

    expect(board.locked).toBe(true);
    // The whole point: locking keeps the pose the user is looking at.
    expect(board.transform.position).toEqual([40, -12, 9]);
    expect(board.transform.rotation).toEqual([0, 0, 30]);
    // No rebuild: mesh URLs survive the scene commit.
    expect(baked.component_files?.arduino_1.stl.download_url).toBe(
      committed.component_files?.arduino_1.stl.download_url,
    );
  });

  it("bakes every displayed pose, not just the locked one", () => {
    const committed = response(ASSEMBLY);
    const displayed = sceneObjects(
      committed,
      (path) => path,
      [],
    ).map((object) =>
      object.id === "screws_1"
        ? { ...object, transform: { position: [7, 3, 1] as [number, number, number], rotation: [0, 0, 0] as [number, number, number] } }
        : object,
    );
    const baked = bakeDisplayedScene(committed, displayed);
    if (!isAssemblySpec(baked.specification)) throw new Error("expected an assembly");
    const screws = baked.specification.components.find((c) => c.id === "screws_1")!;
    expect(screws.transform.position).toEqual([7, 3, 1]);
    expect(screws.parameters).toEqual({ length: 12 });
  });

  it("locks selected components and expands a group selection", () => {
    const grouped = groupSelection(ASSEMBLY, ["arduino_1", "screws_1"], "Board")!;
    const locked = setSelectionLocked(grouped, ["arduino_1"], true)!;
    expect(locked.components[0].locked).toBe(true);
    expect(locked.components[1].locked).toBeFalsy();
    expect(expandSelectionToGroups(grouped, ["arduino_1"])).toEqual([
      "arduino_1",
      "screws_1",
    ]);
  });
});

describe("incremental scene commits", () => {
  it("applies placement without changing mesh URLs", () => {
    const before = response(ASSEMBLY);
    const next = applyPlacementToResponse(before, "arduino_1", {
      transform: { position: [12, 0, 8], rotation: [0, 0, 45] },
      name: "Board",
    });
    expect(next).not.toBeNull();
    expect(next?.component_files?.arduino_1.stl.download_url).toBe(
      before.component_files?.arduino_1.stl.download_url,
    );
    expect(next?.component_files?.screws_1.stl.download_url).toBe(
      before.component_files?.screws_1.stl.download_url,
    );
    const moved = isAssemblySpec(next!.specification)
      ? next!.specification.components[0]
      : null;
    expect(moved?.transform.position).toEqual([12, 0, 8]);
    expect(moved?.name).toBe("Board");
  });

  it("promotes a part then keeps its files when placing", () => {
    const before = response(PART);
    const next = applyPlacementToResponse(before, "generated_1", {
      transform: { position: [5, 0, 0], rotation: [0, 0, 0] },
    });
    const promoted = promoteResponseToAssembly(before);
    expect(next?.component_files?.generated_1.stl.download_url).toBe(
      promoted.component_files?.generated_1.stl.download_url,
    );
    expect(isAssemblySpec(next!.specification)).toBe(true);
  });

  it("removes one object and keeps the other mesh URL", () => {
    const before = response(ASSEMBLY);
    const next = removeComponentFromResponse(before, "screws_1");
    expect(next).not.toBeNull();
    expect(isAssemblySpec(next!.specification)).toBe(true);
    if (!isAssemblySpec(next!.specification)) return;
    expect(next!.specification.components.map((c) => c.id)).toEqual(["arduino_1"]);
    expect(next!.component_files?.arduino_1.stl.download_url).toBe(
      before.component_files?.arduino_1.stl.download_url,
    );
    expect(next!.component_files?.screws_1).toBeUndefined();
  });

  it("refuses to remove the last object", () => {
    const only = {
      ...ASSEMBLY,
      components: [ASSEMBLY.components[0]],
    };
    expect(removeComponentFromResponse(response(only), "arduino_1")).toBeNull();
  });
});
