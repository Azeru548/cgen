import { describe, expect, it } from "vitest";
import {
  isAssemblySpec,
  isPartSpec,
  posesOf,
  sceneObjects,
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
