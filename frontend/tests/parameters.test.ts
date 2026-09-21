import { describe, expect, it } from "vitest";
import {
  applyParameter,
  extractParameters,
  specsEqualJson,
  stepFor,
  summarizeAdjustments,
} from "../lib/parameters";
import type { CadSpecification } from "../types/api";

const BOX: CadSpecification = {
  document_type: "3d_part",
  units: "mm",
  name: "plate",
  operation: { type: "box", width: 100, depth: 60, height: 20 },
};

const CYLINDER: CadSpecification = {
  document_type: "3d_part",
  units: "mm",
  name: "shaft",
  operation: { type: "cylinder", radius: 15, height: 120, through: false },
};

const PART_HOLE_FILLET: CadSpecification = {
  document_type: "3d_part",
  units: "mm",
  name: "plate_with_hole",
  operation: {
    type: "part",
    build: { type: "box", width: 100, depth: 60, height: 20 },
    features: [
      { type: "hole", diameter: 10, through: true, depth: null },
      { type: "fillet", radius: 2 },
    ],
  },
};

const PART_BLIND: CadSpecification = {
  document_type: "3d_part",
  units: "mm",
  name: "blind_plate",
  operation: {
    type: "part",
    build: { type: "box", width: 100, depth: 60, height: 20 },
    features: [{ type: "hole", diameter: 10, through: false, depth: 8 }],
  },
};

describe("extractParameters", () => {
  it("extracts box dimensions", () => {
    const params = extractParameters(BOX);
    expect(params.map((p) => p.key)).toEqual([
      "build.width",
      "build.depth",
      "build.height",
    ]);
    expect(params[0]).toMatchObject({
      path: "operation.width",
      label: "Width",
      value: 100,
      category: "dimensions",
      unit: "mm",
      target: { kind: "build", field: "width" },
    });
    for (const p of params) {
      expect(p.min).toBeLessThan(p.value);
      expect(p.max).toBeGreaterThan(p.value);
      expect(p.step).toBeGreaterThan(0);
    }
  });

  it("extracts cylinder radius and height", () => {
    const params = extractParameters(CYLINDER);
    expect(params.map((p) => p.key)).toEqual(["build.radius", "build.height"]);
    expect(params[0].label).toBe("Radius");
  });

  it("extracts hole diameter and fillet radius with feature paths", () => {
    const params = extractParameters(PART_HOLE_FILLET);
    const keys = params.map((p) => p.key);
    expect(keys).toContain("feature.0.diameter");
    expect(keys).toContain("feature.1.filletRadius");
    // Through hole: no depth parameter.
    expect(keys).not.toContain("feature.0.depth");
    const hole = params.find((p) => p.key === "feature.0.diameter");
    expect(hole?.path).toBe("operation.features.0.diameter");
    expect(hole?.max).toBeLessThanOrEqual(100);
  });

  it("extracts blind-hole depth", () => {
    const params = extractParameters(PART_BLIND);
    const depth = params.find((p) => p.key === "feature.0.depth");
    expect(depth?.value).toBe(8);
  });

  it("exposes nothing unsupported", () => {
    const cone: CadSpecification = {
      ...BOX,
      operation: { type: "cone", bottom_radius: 20, top_radius: 10, height: 50 },
    };
    expect(extractParameters(cone)).toEqual([]);
    const union: CadSpecification = {
      ...BOX,
      operation: {
        type: "union",
        base: { type: "box", width: 10, depth: 10, height: 10 },
        tool: { type: "box", width: 5, depth: 5, height: 5 },
      },
    };
    expect(extractParameters(union)).toEqual([]);
    // Unsupported FEATURES contribute no parameters, but the box build
    // underneath still exposes its own dimensions.
    const patterned: CadSpecification = {
      ...PART_HOLE_FILLET,
      operation: {
        type: "part",
        build: { type: "box", width: 100, depth: 100, height: 10 },
        features: [
          { type: "hole_pattern", diameter: 8, count: 4, circle_diameter: 60, through: true, depth: null },
          { type: "shell", thickness: 2 },
          { type: "chamfer", size: 1 },
        ],
      },
    };
    const patternedParams = extractParameters(patterned);
    expect(patternedParams.map((p) => p.key)).toEqual([
      "build.width",
      "build.depth",
      "build.height",
    ]);
  });
});

describe("applyParameter", () => {
  it("returns a new spec without mutating the original", () => {
    const before = JSON.parse(JSON.stringify(BOX));
    const next = applyParameter(BOX, { kind: "build", field: "width" }, 120);
    expect(next.operation).toMatchObject({ type: "box", width: 120 });
    expect(BOX).toEqual(before);
    expect(next).not.toBe(BOX);
  });

  it("applies multiple changes by chaining", () => {
    let next = applyParameter(PART_HOLE_FILLET, { kind: "build", field: "height" }, 25);
    next = applyParameter(next, { kind: "feature", index: 0, field: "diameter" }, 14);
    next = applyParameter(next, { kind: "feature", index: 1, field: "filletRadius" }, 5);
    expect(next.operation).toMatchObject({ type: "part" });
    if (next.operation.type !== "part") throw new Error("unreachable");
    expect(next.operation.build).toMatchObject({ height: 25 });
    expect(next.operation.features[0]).toMatchObject({ diameter: 14 });
    expect(next.operation.features[1]).toMatchObject({ radius: 5 });
  });

  it("rejects stale or mismatched targets", () => {
    expect(() =>
      applyParameter(BOX, { kind: "feature", index: 0, field: "diameter" }, 12),
    ).toThrow();
    expect(() =>
      applyParameter(PART_HOLE_FILLET, { kind: "feature", index: 9, field: "diameter" }, 12),
    ).toThrow();
    expect(() =>
      applyParameter(PART_HOLE_FILLET, { kind: "feature", index: 1, field: "diameter" }, 12),
    ).toThrow();
    expect(() =>
      applyParameter(PART_HOLE_FILLET, { kind: "build", field: "radius" }, 12),
    ).toThrow();
    expect(() => applyParameter(BOX, { kind: "build", field: "width" }, -4)).toThrow();
  });
});

describe("summarizeAdjustments", () => {
  it("summarizes single and multiple changes", () => {
    const params = extractParameters(BOX);
    expect(summarizeAdjustments(params, { "build.width": 120 })).toBe(
      "Adjusted width 100 → 120 mm",
    );
    expect(
      summarizeAdjustments(params, { "build.width": 120, "build.height": 25 }),
    ).toBe("Adjusted width 100 → 120 mm, height 20 → 25 mm");
    expect(summarizeAdjustments(params, {})).toBe("Adjusted parameters");
  });
});

describe("specsEqualJson", () => {
  it("compares structurally", () => {
    expect(specsEqualJson(BOX, JSON.parse(JSON.stringify(BOX)))).toBe(true);
    expect(specsEqualJson(BOX, { ...BOX, name: "other" })).toBe(false);
  });
});

describe("stepFor", () => {
  it("scales step to magnitude", () => {
    expect(stepFor(100)).toBe(1);
    expect(stepFor(10)).toBe(0.5);
    expect(stepFor(1)).toBe(0.1);
  });
});
