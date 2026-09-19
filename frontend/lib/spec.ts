/** Display helpers derived from the validated CAD specification.
 *  The frontend never computes CAD geometry — only human-readable labels.
 */
import type {
  CadFeature,
  CadOperation,
  OperationType,
} from "@/types/api";

export const OPERATION_LABELS: Record<OperationType, string> = {
  box: "Box",
  cylinder: "Cylinder",
  cone: "Cone",
  sphere: "Sphere",
  torus: "Torus",
  polygon_prism: "Polygon Prism",
  union: "Union",
  cut: "Cut",
  intersect: "Intersect",
  part: "Part",
};

/** Engine feature application order (mirrors backend feature_summary).
 *  Keep in sync: holes and hole patterns -> shell -> chamfer -> fillet. */
const FEATURE_ORDER: Record<CadFeature["type"], number> = {
  hole: 0,
  hole_pattern: 0,
  shell: 1,
  chamfer: 2,
  fillet: 3,
};

export function sortFeatures(features: CadFeature[]): CadFeature[] {
  return [...features].sort(
    (a, b) => FEATURE_ORDER[a.type] - FEATURE_ORDER[b.type],
  );
}

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
    case "torus":
      return `Torus · ⌀${formatMm(op.major_radius * 2)} ring × ⌀${formatMm(op.minor_radius * 2)} tube mm`;
    case "polygon_prism":
      return `Prism · ${op.sides}-gon · ⌀${formatMm(op.circumradius * 2)} across corners × ${formatMm(op.height)} mm`;
    case "union":
    case "cut":
    case "intersect":
      return `${operationLabel(op)} operation`;
    case "part": {
      const n = op.features.length;
      return `${summarizePrimitive(op.build)}${n > 0 ? ` + ${n} feature${n === 1 ? "" : "s"}` : ""}`;
    }
  }
}

/** One-line human summary of a single feature, e.g. "Hole ⌀8 through". */
export function summarizeFeature(feature: CadFeature): string {
  switch (feature.type) {
    case "hole":
      return feature.through
        ? `Hole ⌀${formatMm(feature.diameter)} through`
        : `Hole ⌀${formatMm(feature.diameter)} × ${formatMm(feature.depth ?? 0)} deep`;
    case "hole_pattern": {
      const base =
        `Hole Pattern ⌀${formatMm(feature.diameter)} · ` +
        `${feature.count}× · ⌀${formatMm(feature.circle_diameter)} circle`;
      return feature.through ? base : `${base} × ${formatMm(feature.depth ?? 0)} deep`;
    }
    case "fillet":
      return `Fillet r${formatMm(feature.radius)}`;
    case "chamfer":
      return `Chamfer ${formatMm(feature.size)}`;
    case "shell":
      return `Wall ${formatMm(feature.thickness)}`;
  }
}

/** Dimension rows for the spec panel. Boolean ops list base/tool summaries;
 *  part nodes list the build plus engine-ordered feature rows. */
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
    case "torus":
      return [
        { label: "Ring diameter", value: `${formatMm(op.major_radius * 2)} mm` },
        { label: "Tube diameter", value: `${formatMm(op.minor_radius * 2)} mm` },
      ];
    case "polygon_prism":
      return [
        { label: "Sides", value: String(op.sides) },
        { label: "Across corners", value: `${formatMm(op.circumradius * 2)} mm` },
        { label: "Height", value: `${formatMm(op.height)} mm` },
      ];
    case "union":
    case "cut":
    case "intersect":
      return [
        { label: "Base", value: summarizePrimitive(op.base) },
        { label: "Tool", value: summarizePrimitive(op.tool) },
      ];
    case "part":
      return [
        { label: "Build", value: summarizePrimitive(op.build) },
        ...sortFeatures(op.features).map((feature) => ({
          label: "Feature",
          value: summarizeFeature(feature),
        })),
      ];
  }
}

export interface TreeLine {
  depth: number;
  text: string;
}

/** Concise indented operation tree for boolean compositions.
 *  Part nodes render as their build subtree; features are shown in the
 *  dimension rows instead. */
export function describeTree(op: CadOperation, depth = 0): TreeLine[] {
  if (op.type === "union" || op.type === "cut" || op.type === "intersect") {
    const joiner = op.type === "cut" ? "−" : op.type === "intersect" ? "∩" : "+";
    return [
      { depth, text: `${operationLabel(op)} (${joiner})` },
      ...describeTree(op.base, depth + 1),
      ...describeTree(op.tool, depth + 1),
    ];
  }
  if (op.type === "part") {
    return describeTree(op.build, depth);
  }
  return [{ depth, text: summarizePrimitive(op) }];
}
