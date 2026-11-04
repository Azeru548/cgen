import { describe, expect, it } from "vitest";
import {
  DEFAULT_MATERIAL_ID,
  MATERIALS,
  isMaterialId,
  materialById,
} from "../lib/materials";

describe("viewport materials", () => {
  it("exposes three distinct presets with a stable default", () => {
    expect(MATERIALS).toHaveLength(3);
    expect(MATERIALS.map((m) => m.id)).toEqual(["alloy", "anodised", "polymer"]);
    expect(MATERIALS.map((m) => m.label)).toEqual(["Alloy", "Anodised", "Polymer"]);
    expect(materialById(DEFAULT_MATERIAL_ID).id).toBe("alloy");
  });

  it("describes metal as metal and polymer as plastic", () => {
    const alloy = materialById("alloy");
    const polymer = materialById("polymer");
    expect(alloy.metalness).toBeGreaterThan(0.6);
    expect(alloy.roughness).toBeLessThan(0.45);
    expect(polymer.metalness).toBeLessThan(0.2);
    expect(polymer.roughness).toBeGreaterThan(0.5);
  });

  it("falls back to the default for unknown or missing values", () => {
    for (const value of [null, undefined, "", "chrome", "ALLOY"]) {
      expect(materialById(value).id).toBe(DEFAULT_MATERIAL_ID);
      expect(isMaterialId(value)).toBe(false);
    }
    expect(isMaterialId("polymer")).toBe(true);
  });
});
