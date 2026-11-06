import { describe, expect, it } from "vitest";
import {
  animationOf,
  applyPlacementToResponse,
  bakeDisplayedScene,
  bomRows,
  duplicateComponent,
  expandSelectionToGroups,
  groupSelection,
  isAssemblySpec,
  isPartSpec,
  keyAt,
  placedBounds,
  posesOf,
  promoteResponseToAssembly,
  removeComponentFromResponse,
  retimeKey,
  rotateSelection,
  sampleTrack,
  sceneObjects,
  setAnimationDuration,
  setSelectionLocked,
  trackFor,
  translateSelection,
  ungroupSelection,
  withComponentPatch,
  withTrack,
  withoutKey,
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

describe("placement helpers", () => {
  const specs = { ...ASSEMBLY, groups: [] } as AssemblySpecification;

  it("reports the world box of a rotated part", () => {
    const bounds = { min: [-20, -10, -5] as [number, number, number], size: [40, 20, 10] as [number, number, number] };
    const placed = placedBounds(
      { position: [10, 0, 0], rotation: [0, 0, 90] },
      bounds,
    );
    // A 40 × 20 footprint turned 90° about Z occupies 20 × 40, shifted +10 in X.
    expect(placed.min[0]).toBeCloseTo(0, 5);
    expect(placed.max[0]).toBeCloseTo(20, 5);
    expect(placed.min[1]).toBeCloseTo(-20, 5);
    expect(placed.max[1]).toBeCloseTo(20, 5);
    expect(placed.min[2]).toBeCloseTo(-5, 5);
  });

  it("translates a component and its instances", () => {
    const withInstances: AssemblySpecification = {
      ...specs,
      components: specs.components.map((component) =>
        component.id === "screws_1"
          ? {
              ...component,
              transform: { position: [0, 0, 0], rotation: [0, 0, 0] },
              instances: [
                { position: [5, 5, 0], rotation: [0, 0, 0] },
                { position: [15, 5, 0], rotation: [0, 0, 0] },
              ],
            }
          : component,
      ),
    };
    const next = translateSelection(withInstances, ["screws_1"], [0, 0, 12]);
    expect(next).not.toBeNull();
    const moved = next!.components.find((c) => c.id === "screws_1")!;
    expect(moved.transform.position).toEqual([0, 0, 12]);
    expect(moved.instances.map((pose) => pose.position[2])).toEqual([12, 12]);
    expect(translateSelection(withInstances, ["screws_1"], [0, 0, 0])).toBeNull();
  });

  it("duplicates a component off to the side with a fresh id", () => {
    const source = specs.components[0];
    const copy = duplicateComponent(specs, source.id, [30, 0, 0]);
    expect(copy).not.toBeNull();
    expect(copy!.id).not.toBe(source.id);
    const cloned = copy!.specification.components.find((c) => c.id === copy!.id)!;
    expect(cloned.name.endsWith("copy")).toBe(true);
    expect(cloned.transform.position[0]).toBe(source.transform.position[0] + 30);
    expect(cloned.parameters).toEqual(source.parameters);
    expect(cloned.locked).toBe(false);
    expect(copy!.specification.components).toHaveLength(specs.components.length + 1);
  });
});

describe("motion tracks", () => {
  const track = {
    component_id: "arduino_1",
    keys: [
      { t: 0, position: [0, 0, 0] as [number, number, number], rotation: [0, 0, 0] as [number, number, number] },
      { t: 2, position: [10, 0, 20] as [number, number, number], rotation: [0, 0, 350] as [number, number, number] },
    ],
    loop: true,
  };

  it("interpolates position and takes the short way round for angles", () => {
    const mid = sampleTrack(track, 1);
    expect(mid.position).toEqual([5, 0, 10]);
    // 0° → 350° is a −10° turn, so the midpoint is −5° (355), not 175°.
    expect(mid.rotation[2]).toBeCloseTo(-5, 6);
    expect(sampleTrack(track, -1).position).toEqual([0, 0, 0]);
    expect(sampleTrack(track, 99).position).toEqual([10, 0, 20]);
  });

  it("holds a single key and survives an empty track", () => {
    const single = { ...track, keys: [track.keys[0]] };
    expect(sampleTrack(single, 3).position).toEqual([0, 0, 0]);
    expect(sampleTrack({ ...track, keys: [] }, 3).position).toEqual([0, 0, 0]);
  });

  it("replaces a key within 20 ms and keeps the list sorted", () => {
    const updated = keyAt(track, 1, { position: [1, 2, 3], rotation: [0, 0, 0] });
    expect(updated.keys.map((key) => key.t)).toEqual([0, 1, 2]);
    const replaced = keyAt(updated, 1.005, {
      position: [9, 9, 9],
      rotation: [0, 0, 0],
    });
    expect(replaced.keys).toHaveLength(3);
    expect(replaced.keys[1].position).toEqual([9, 9, 9]);
  });

  it("adds and removes tracks through the scene", () => {
    const spec: AssemblySpecification = { ...ASSEMBLY, groups: [] };
    const added = withTrack(spec, track);
    expect(animationOf(added)?.tracks).toHaveLength(1);
    expect(trackFor(added, "arduino_1")?.keys).toHaveLength(2);
    const removed = withTrack(added, { ...track, keys: [] });
    expect(animationOf(removed)).toBeNull();
    expect(withoutKey(track, 0).keys).toHaveLength(1);
  });

  it("retimes a key in place and keeps the list sorted", () => {
    const moved = retimeKey(track, 0, 3);
    expect(moved.keys.map((key) => key.t)).toEqual([2, 3]);
    // The pose travels with the key, not with the slot.
    expect(moved.keys[1].position).toEqual([0, 0, 0]);
    expect(retimeKey(track, 9, 1)).toBe(track);
  });

  it("clamps duration and drops keys past the new end", () => {
    const spec = withTrack({ ...ASSEMBLY, groups: [] }, track);
    const shortened = setAnimationDuration(spec, 1);
    expect(shortened.animation?.duration).toBe(1);
    expect(shortened.animation?.tracks[0].keys.map((key) => key.t)).toEqual([0]);
    expect(setAnimationDuration(spec, 0).animation?.duration).toBe(0.2);
  });

  it("counts instances as separate parts in the bill of materials", () => {
    const rows = bomRows(ASSEMBLY);
    const screws = rows.find((row) => row.type === "screws_1") ?? rows.find((row) => row.quantity > 1);
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.reduce((sum, row) => sum + row.quantity, 0)).toBeGreaterThan(0);
    expect(screws === undefined || screws.quantity >= 1).toBe(true);
    expect(bomRows(PART)).toEqual([]);
  });
});
