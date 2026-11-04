/**
 * Viewport material presets.
 *
 * The same STL is a different part depending on how it is surfaced: a machined
 * alloy reads as metal, an anodised part as a product, a printed part as
 * polymer. These are display-only — they never touch the exported STEP/STL.
 */

export type MaterialId = "alloy" | "anodised" | "polymer";

export interface MaterialPreset {
  id: MaterialId;
  label: string;
  /** Base colour when the object is not selected. */
  color: string;
  metalness: number;
  roughness: number;
}

export const MATERIALS: readonly MaterialPreset[] = [
  {
    id: "alloy",
    label: "Alloy",
    color: "#b7bec8",
    metalness: 0.82,
    roughness: 0.3,
  },
  {
    id: "anodised",
    label: "Anodised",
    color: "#2f353d",
    metalness: 0.55,
    roughness: 0.44,
  },
  {
    id: "polymer",
    label: "Polymer",
    color: "#cdd1d7",
    metalness: 0.05,
    roughness: 0.62,
  },
] as const;

export const DEFAULT_MATERIAL_ID: MaterialId = "alloy";

/** Unknown or stale values fall back to the default instead of throwing. */
export function materialById(id: string | null | undefined): MaterialPreset {
  return MATERIALS.find((m) => m.id === id) ?? MATERIALS[0];
}

export function isMaterialId(value: unknown): value is MaterialId {
  return (
    typeof value === "string" && MATERIALS.some((m) => m.id === value)
  );
}
