/** Display helpers derived from the validated CAD specification.
 *  The frontend never computes CAD geometry — only human-readable labels.
 */
import type { CadOperation, OperationType } from "@/types/api";

export const OPERATION_LABELS: Record<OperationType, string> = {
  box: "Box",
  cylinder: "Cylinder",
  cone: "Cone",
  sphere: "Sphere",
  union: "Union",
  cut: "Cut",
};

export function operationLabel(op: CadOperation): string {
  return OPERATION_LABELS[op.type] ?? op.type;
}

/** Compact number formatting: 100 -> "100", 7.5 -> "7.5". */
export function formatMm(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return String(Math.round(value * 1000) / 1000);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/** "shaft_with_center_hole" -> "Shaft With Center Hole". Display only. */
export function humanizeName(name: string): string {
  return name
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export interface DimensionRow {
  label: string;
  value: string;
}

/** One-line summary of a primitive, e.g. "Cylinder · ⌀30 × 120 mm". */
export function summarizePrimitive(op: CadOperation): string {
  switch (op.type) {
    case "box":
      return `Box · ${formatMm(op.width)} × ${formatMm(op.depth)} × ${formatMm(op.height)} mm`;
    case "cylinder":
      return `Cylinder · ⌀${formatMm(op.radius * 2)} × ${formatMm(op.height)} mm`;
    case "cone":
      return `Cone · ⌀${formatMm(op.bottom_radius * 2)} → ⌀${formatMm(op.top_radius * 2)} × ${formatMm(op.height)} mm`;
    case "sphere":
      return `Sphere · ⌀${formatMm(op.radius * 2)} mm`;
    case "union":
    case "cut":
      return `${operationLabel(op)} operation`;
  }
}

/** Dimension rows for the spec panel. Boolean ops list base/tool summaries. */
export function summarizeDimensions(op: CadOperation): DimensionRow[] {
  switch (op.type) {
    case "box":
      return [
        { label: "Width", value: `${formatMm(op.width)} mm` },
        { label: "Depth", value: `${formatMm(op.depth)} mm` },
        { label: "Height", value: `${formatMm(op.height)} mm` },
      ];
    case "cylinder":
      return [
        { label: "Diameter", value: `${formatMm(op.radius * 2)} mm` },
        { label: "Height", value: `${formatMm(op.height)} mm` },
        ...(op.through ? [{ label: "Through", value: "Yes" }] : []),
      ];
    case "cone":
      return [
        { label: "Bottom diameter", value: `${formatMm(op.bottom_radius * 2)} mm` },
        { label: "Top diameter", value: `${formatMm(op.top_radius * 2)} mm` },
        { label: "Height", value: `${formatMm(op.height)} mm` },
      ];
    case "sphere":
      return [{ label: "Diameter", value: `${formatMm(op.radius * 2)} mm` }];
    case "union":
    case "cut":
      return [
        { label: "Base", value: summarizePrimitive(op.base) },
        { label: "Tool", value: summarizePrimitive(op.tool) },
      ];
  }
}

export interface TreeLine {
  depth: number;
  text: string;
}

/** Concise indented operation tree for boolean compositions. */
export function describeTree(op: CadOperation, depth = 0): TreeLine[] {
  if (op.type === "union" || op.type === "cut") {
    const joiner = op.type === "cut" ? "−" : "+";
    return [
      { depth, text: `${operationLabel(op)} (${joiner})` },
      ...describeTree(op.base, depth + 1),
      ...describeTree(op.tool, depth + 1),
    ];
  }
  return [{ depth, text: summarizePrimitive(op) }];
}
