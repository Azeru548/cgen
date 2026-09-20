import { describe, expect, it } from "vitest";
import type { CadOperation, CadFeature } from "../types/api";
import {
  describeTree,
  formatBytes,
  formatMm,
  humanizeName,
  operationLabel,
  sortFeatures,
  summarizeDimensions,
  summarizeFeature,
  summarizePrimitive,
} from "../lib/spec";

describe("operationLabel", () => {
  it("labels all six operation types", () => {
    const cases: Array<[CadOperation, string]> = [
      [{ type: "box", width: 1, depth: 2, height: 3 }, "Box"],
      [{ type: "cylinder", radius: 1, height: 2, through: false }, "Cylinder"],
      [{ type: "cone", bottom_radius: 2, top_radius: 1, height: 3 }, "Cone"],
      [{ type: "sphere", radius: 5 }, "Sphere"],
      [
        {
          type: "union",
          base: { type: "box", width: 1, depth: 1, height: 1 },
          tool: { type: "sphere", radius: 1 },
        },
        "Union",
      ],
      [
        {
          type: "cut",
          base: { type: "box", width: 1, depth: 1, height: 1 },
          tool: { type: "box", width: 1, depth: 1, height: 1 },
        },
        "Cut",
      ],
      [
        { type: "torus", major_radius: 30, minor_radius: 8 },
        "Torus",
      ],
      [
        { type: "polygon_prism", sides: 6, circumradius: 10, height: 8 },
        "Polygon Prism",
      ],
      [
        {
          type: "intersect",
          base: { type: "box", width: 50, depth: 50, height: 10 },
          tool: { type: "sphere", radius: 60 },
        },
        "Intersect",
      ],
      [
        {
          type: "part",
          build: { type: "box", width: 100, depth: 60, height: 10 },
          features: [{ type: "hole", diameter: 8, through: true, depth: null }],
        },
        "Part",
      ],
    ];
    for (const [op, label] of cases) expect(operationLabel(op)).toBe(label);
  });
});

describe("summarizeDimensions", () => {
  it("lists box width/depth/height", () => {
    expect(
      summarizeDimensions({ type: "box", width: 100, depth: 60, height: 30 }),
    ).toEqual([
      { label: "Width", value: "100 mm" },
      { label: "Depth", value: "60 mm" },
      { label: "Height", value: "30 mm" },
    ]);
  });

  it("converts cylinder radius to diameter", () => {
    const rows = summarizeDimensions({
      type: "cylinder",
      radius: 15,
      height: 120,
      through: false,
    });
    expect(rows[0]).toEqual({ label: "Diameter", value: "30 mm" });
    expect(rows).toHaveLength(2);
  });

  it("shows cone diameters and sphere diameter", () => {
    const cone = summarizeDimensions({
      type: "cone",
      bottom_radius: 20,
      top_radius: 10,
      height: 50,
    });
    expect(cone[0].value).toBe("40 mm");
    expect(cone[1].value).toBe("20 mm");
    expect(
      summarizeDimensions({ type: "sphere", radius: 25 })[0].value,
    ).toBe("50 mm");
  });

  it("summarizes torus, prism and part primitives", () => {
    expect(
      summarizePrimitive({ type: "torus", major_radius: 30, minor_radius: 8 }),
    ).toBe("Torus · ⌀60 ring × ⌀16 tube mm");
    expect(
      summarizePrimitive({
        type: "polygon_prism",
        sides: 6,
        circumradius: 10,
        height: 8,
      }),
    ).toBe("Prism · 6-gon · ⌀20 across corners × 8 mm");
    expect(
      summarizePrimitive({
        type: "part",
        build: { type: "box", width: 100, depth: 60, height: 10 },
        features: [
          { type: "hole", diameter: 8, through: true, depth: null },
          { type: "fillet", radius: 2 },
        ],
      }),
    ).toBe("Box · 100 × 60 × 10 mm + 2 features");
    expect(
      summarizePrimitive({
        type: "part",
        build: { type: "sphere", radius: 25 },
        features: [],
      }),
    ).toBe("Sphere · ⌀50 mm");
  });

  it("summarizes boolean base and tool without inventing numbers", () => {
    const rows = summarizeDimensions({
      type: "cut",
      base: { type: "cylinder", radius: 15, height: 120, through: false },
      tool: { type: "cylinder", radius: 7.5, height: 120, through: true },
    });
    expect(rows[0].label).toBe("Base");
    expect(rows[0].value).toContain("⌀30");
    expect(rows[1].label).toBe("Tool");
    expect(rows[1].value).toContain("⌀15");
  });

  it("lists torus ring and tube diameters", () => {
    const rows = summarizeDimensions({
      type: "torus",
      major_radius: 30,
      minor_radius: 8,
    });
    expect(rows).toEqual([
      { label: "Ring diameter", value: "60 mm" },
      { label: "Tube diameter", value: "16 mm" },
    ]);
  });

  it("lists polygon prism sides, across-corners and height", () => {
    const rows = summarizeDimensions({
      type: "polygon_prism",
      sides: 6,
      circumradius: 10,
      height: 8,
    });
    expect(rows).toEqual([
      { label: "Sides", value: "6" },
      { label: "Across corners", value: "20 mm" },
      { label: "Height", value: "8 mm" },
    ]
    );
  });

  it("lists the part build plus features in engine order", () => {
    const rows = summarizeDimensions({
      type: "part",
      build: { type: "box", width: 100, depth: 60, height: 10 },
      features: [
        { type: "fillet", radius: 2 },
        { type: "hole", diameter: 8, through: true, depth: null },
        { type: "shell", thickness: 2 },
      ],
    });
    expect(rows[0]).toEqual({
      label: "Build",
      value: "Box · 100 × 60 × 10 mm",
    });
    expect(rows.map((r) => r.value)).toEqual([
      "Box · 100 × 60 × 10 mm",
      "Hole ⌀8 through",
      "Wall 2",
      "Fillet r2",
    ]);
  });
});

describe("summarizeFeature", () => {
  it("describes every feature kind", () => {
    const features: CadFeature[] = [
      { type: "hole", diameter: 8, through: true, depth: null },
      { type: "hole", diameter: 8, through: false, depth: 12 },
      {
        type: "hole_pattern",
        diameter: 8,
        count: 4,
        circle_diameter: 60,
        through: true,
        depth: null,
      },
      {
        type: "hole_pattern",
        diameter: 8,
        count: 6,
        circle_diameter: 80,
        through: false,
        depth: 10,
      },
      {
        type: "hole_grid",
        diameter: 8,
        rows: 2,
        cols: 2,
        spacing_x: 100,
        spacing_y: 60,
        through: true,
        depth: null,
      },
      {
        type: "hole_grid",
        diameter: 6,
        rows: 1,
        cols: 3,
        spacing_x: 40,
        spacing_y: 40,
        through: false,
        depth: 5,
      },
      { type: "fillet", radius: 2 },
      { type: "chamfer", size: 1.5 },
      { type: "shell", thickness: 3 },
    ];
    expect(features.map(summarizeFeature)).toEqual([
      "Hole ⌀8 through",
      "Hole ⌀8 × 12 deep",
      "Hole Pattern ⌀8 · 4× · ⌀60 circle",
      "Hole Pattern ⌀8 · 6× · ⌀80 circle × 10 deep",
      "Hole Grid ⌀8 · 2×2 · 100×60 pitch",
      "Hole Grid ⌀6 · 1×3 · 40×40 pitch × 5 deep",
      "Fillet r2",
      "Chamfer 1.5",
      "Wall 3",
    ]);
  });

  it("sorts features into engine application order", () => {
    const sorted = sortFeatures([
      { type: "fillet", radius: 2 },
      { type: "shell", thickness: 2 },
      { type: "chamfer", size: 1 },
      { type: "hole", diameter: 8, through: true, depth: null },
    ]);
    expect(sorted.map((f) => f.type)).toEqual([
      "hole",
      "shell",
      "chamfer",
      "fillet",
    ]);
  });

  it("places hole_grid at the same index as hole", () => {
    const sorted = sortFeatures([
      { type: "fillet", radius: 2 },
      {
        type: "hole_grid",
        diameter: 8,
        rows: 2,
        cols: 2,
        spacing_x: 100,
        spacing_y: 60,
        through: true,
        depth: null,
      },
      { type: "shell", thickness: 2 },
    ]);
    expect(sorted.map((f) => f.type)).toEqual([
      "hole_grid",
      "shell",
      "fillet",
    ]);
  });

  it("places hole_pattern at the same index as hole", () => {
    const sorted = sortFeatures([
      { type: "fillet", radius: 2 },
      { type: "shell", thickness: 2 },
      {
        type: "hole_pattern",
        diameter: 8,
        count: 4,
        circle_diameter: 60,
        through: true,
        depth: null,
      },
    ]);
    expect(sorted.map((f) => f.type)).toEqual([
      "hole_pattern",
      "shell",
      "fillet",
    ]);
  });
});

describe("describeTree", () => {
  it("renders a concise indented tree", () => {
    const lines = describeTree({
      type: "cut",
      base: { type: "cylinder", radius: 15, height: 120, through: false },
      tool: { type: "cylinder", radius: 7.5, height: 120, through: true },
    });
    expect(lines[0]).toEqual({ depth: 0, text: "Cut (−)" });
    expect(lines).toHaveLength(3);
    expect(lines[1].depth).toBe(1);
  });

  it("uses the intersection joiner for intersect nodes", () => {
    const lines = describeTree({
      type: "intersect",
      base: { type: "box", width: 50, depth: 50, height: 10 },
      tool: { type: "sphere", radius: 60 },
    });
    expect(lines[0]).toEqual({ depth: 0, text: "Intersect (∩)" });
    expect(lines).toHaveLength(3);
  });

  it("renders a part node as its build subtree", () => {
    const lines = describeTree({
      type: "part",
      build: {
        type: "union",
        base: { type: "box", width: 10, depth: 10, height: 10 },
        tool: { type: "sphere", radius: 8 },
      },
      features: [{ type: "fillet", radius: 2 }],
    });
    expect(lines[0]).toEqual({ depth: 0, text: "Union (+)" });
    expect(lines).toHaveLength(3);
  });

  it("is a single line for primitives", () => {
    expect(
      summarizePrimitive({ type: "sphere", radius: 25 }),
    ).toBe("Sphere · ⌀50 mm");
  });
});

describe("formatters", () => {
  it("formats numbers, names, and byte counts", () => {
    expect(formatMm(100)).toBe("100");
    expect(formatMm(7.5)).toBe("7.5");
    expect(humanizeName("shaft_with_center_hole")).toBe("Shaft With Center Hole");
    expect(formatBytes(9338)).toBe("9.1 KB");
    expect(formatBytes(400)).toBe("400 B");
  });
});
