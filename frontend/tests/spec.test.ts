import { describe, expect, it } from "vitest";
import type { CadOperation } from "../types/api";
import {
  describeTree,
  formatBytes,
  formatMm,
  humanizeName,
  operationLabel,
  summarizeDimensions,
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
