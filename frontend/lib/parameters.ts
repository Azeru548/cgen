/** M8.1 local parametric model (no React, no I/O).
 *
 *  CADSpec remains the single source of truth. This module derives a small
 *  typed parameter list from a validated spec (Phase 2) and applies edited
 *  values back immutably (Phase 3). Supported in M8.1: box/cylinder build
 *  dimensions, hole diameter (+ blind depth), fillet radius. Everything else
 *  (cones, patterns, grids, chamfer, shell, counts, sides, through flags,
 *  topology) is deliberately unexposed — the extractor is shaped so those
 *  can be added later without changing this contract.
 *
 *  Bounds are UX hints only; POST /rebuild stays authoritative. For feature
 *  parameters on composite builds the client cannot know exact fit, so it
 *  uses conservative ranges and lets the backend validate.
 */
import type {
  BoxOperation,
  CadFeature,
  CadOperation,
  CadSpecification,
  CylinderOperation,
  DocumentSpecification,
  FilletFeature,
  HoleFeature,
} from "@/types/api";

export type ParameterCategory = "dimensions" | "features";

export type BuildField = "width" | "depth" | "height" | "radius";
export type FeatureField = "diameter" | "depth" | "filletRadius";

export type ParameterTarget =
  | { kind: "build"; field: BuildField }
  | { kind: "feature"; index: number; field: FeatureField };

export interface ParameterDescriptor {
  /** Stable key for React + summaries, e.g. "build.width", "feature.0.diameter". */
  key: string;
  /** JSON-style path into the spec (display/debug only). */
  path: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  category: ParameterCategory;
  unit: "mm";
  target: ParameterTarget;
}

/** Step sized to the value magnitude: exact enough for CAD, coarse on drag. */
export function stepFor(value: number): number {
  const v = Math.abs(value);
  if (v >= 100) return 1;
  if (v >= 10) return 0.5;
  if (v >= 1) return 0.1;
  return 0.05;
}

function roundToStep(value: number, step: number): number {
  return Math.round(value / step) * step;
}

/** Conservative UX range around the current value. Schema floor is > 0;
 *  the ceiling stays modest — the backend validates real fit. */
function rangedRange(value: number): { min: number; max: number; step: number } {
  const step = stepFor(value);
  const min = Math.max(step, roundToStep(value / 4, step));
  const max = Math.min(10000, roundToStep(value * 4, step));
  if (!(min < max)) return { min: step, max: value + step, step };
  return { min, max, step };
}

/** Clamp a computed range so the slider never starts in an invalid spot. */
function saneRange(
  value: number,
  min: number,
  max: number,
  step: number,
): { min: number; max: number; step: number } {
  const lo = Math.min(min, value - step);
  const hi = Math.max(max, value + step);
  if (!(lo < hi)) return { min: value - step, max: value + step, step };
  return { min: lo, max: hi, step };
}

/** Analytic XYZ half-knowledge of the build: extents the client CAN know.
 *  Only single primitives (null = composite/unknown, no parameters). */
interface BuildExtents {
  x: number;
  y: number;
  z: number;
}

function buildExtents(op: CadOperation): BuildExtents | null {
  const build = op.type === "part" ? op.build : op;
  if (build.type === "box") {
    return { x: build.width, y: build.depth, z: build.height };
  }
  if (build.type === "cylinder") {
    return { x: build.radius * 2, y: build.radius * 2, z: build.height };
  }
  return null;
}

function buildParams(
  op: CadOperation,
  build: BoxOperation | CylinderOperation,
): ParameterDescriptor[] {
  const out: ParameterDescriptor[] = [];
  const defs: Array<{ field: BuildField; label: string; value: number }> =
    build.type === "box"
      ? [
          { field: "width", label: "Width", value: build.width },
          { field: "depth", label: "Depth", value: build.depth },
          { field: "height", label: "Height", value: build.height },
        ]
      : [
          { field: "radius", label: "Radius", value: build.radius },
          { field: "height", label: "Height", value: build.height },
        ];
  for (const def of defs) {
    const range = rangedRange(def.value);
    out.push({
      key: `build.${def.field}`,
      path: op.type === "part" ? `operation.build.${def.field}` : `operation.${def.field}`,
      label: def.label,
      value: def.value,
      ...range,
      category: "dimensions",
      unit: "mm",
      target: { kind: "build", field: def.field },
    });
  }
  return out;
}

function holeParams(
  feature: HoleFeature,
  index: number,
  extents: BuildExtents | null,
  seen: number,
): ParameterDescriptor[] {
  const out: ParameterDescriptor[] = [];
  const tag = seen > 1 ? ` ${index + 1}` : "";
  // A centered hole must fit the smallest face: conservative cap with a
  // 1mm wall margin per side. Unknown builds fall back to a wide range.
  const faceMin = extents === null ? null : Math.min(extents.x, extents.y);
  const diaStep = stepFor(feature.diameter);
  const diaMax =
    faceMin === null
      ? Math.min(10000, feature.diameter * 4)
      : Math.max(feature.diameter + diaStep, faceMin - 2);
  out.push({
    key: `feature.${index}.diameter`,
    path: `operation.features.${index}.diameter`,
    label: `Hole Ø${tag}`,
    value: feature.diameter,
    ...saneRange(feature.diameter, diaStep, diaMax, diaStep),
    category: "features",
    unit: "mm",
    target: { kind: "feature", index, field: "diameter" },
  });
  if (!feature.through && feature.depth !== null) {
    // Blind depth cannot usefully exceed the part height; fall back wide
    // when the build is composite (unknown here — M8.1 only reaches this
    // branch for box/cylinder builds, whose z extent is known).
    const zMax = extents === null ? feature.depth * 4 : Math.max(feature.depth, extents.z - 1);
    const depStep = stepFor(feature.depth);
    out.push({
      key: `feature.${index}.depth`,
      path: `operation.features.${index}.depth`,
      label: `Hole depth${tag}`,
      value: feature.depth,
      ...saneRange(feature.depth, depStep, Math.min(10000, zMax), depStep),
      category: "features",
      unit: "mm",
      target: { kind: "feature", index, field: "depth" },
    });
  }
  return out;
}

function filletParams(
  feature: FilletFeature,
  index: number,
  extents: BuildExtents | null,
  seen: number,
): ParameterDescriptor[] {
  const tag = seen > 1 ? ` ${index + 1}` : "";
  const step = stepFor(feature.radius);
  // A fillet must stay well under half the thinnest wall; unknown builds
  // fall back to a wide range and let /rebuild decide.
  const thin = extents === null ? null : Math.min(extents.x, extents.y, extents.z);
  const cap = thin === null ? feature.radius * 4 : Math.max(feature.radius + step, thin / 2 - 0.5);
  return [
    {
      key: `feature.${index}.filletRadius`,
      path: `operation.features.${index}.radius`,
      label: `Fillet R${tag}`,
      value: feature.radius,
      ...saneRange(feature.radius, step, Math.min(10000, cap), step),
      category: "features",
      unit: "mm",
      target: { kind: "feature", index, field: "filletRadius" },
    },
  ];
}

/** Derive the M8.1 parameter list. Empty = not parametrically adjustable
 *  (composite builds, unsupported ops/features) and the panel stays hidden. */
export function extractParameters(spec: DocumentSpecification): ParameterDescriptor[] {
  if (spec.document_type !== "3d_part") return [];
  const op = spec.operation;
  const build = op.type === "part" ? op.build : op;
  if (build.type !== "box" && build.type !== "cylinder") return [];
  const extents = buildExtents(op);
  const out: ParameterDescriptor[] = [...buildParams(op, build)];
  if (op.type !== "part") return out;
  const holes = op.features.filter(
    (f): f is HoleFeature => f.type === "hole",
  );
  const fillets = op.features.filter(
    (f): f is FilletFeature => f.type === "fillet",
  );
  op.features.forEach((feature: CadFeature, index: number) => {
    if (feature.type === "hole") {
      out.push(...holeParams(feature, index, extents, holes.length));
    } else if (feature.type === "fillet") {
      out.push(...filletParams(feature, index, extents, fillets.length));
    }
  });
  return out;
}

function cloneSpec(spec: CadSpecification): CadSpecification {
  return JSON.parse(JSON.stringify(spec)) as CadSpecification;
}

/** Apply one descriptor value immutably. Only descriptor-produced targets
 *  are settable — there is no generic path setter. Throws on mismatch so
 *  a stale descriptor can never corrupt a spec. */
export function applyParameter(
  spec: DocumentSpecification,
  target: ParameterTarget,
  value: number,
): DocumentSpecification {
  if (spec.document_type !== "3d_part") {
    throw new Error("Part parameters only apply to a single generated part.");
  }
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("Parameter value must be a positive number.");
  }
  const next = cloneSpec(spec);
  const op = next.operation;
  const build = op.type === "part" ? op.build : op;
  if (target.kind === "build") {
    if (build.type !== "box" && build.type !== "cylinder") {
      throw new Error("Build parameters need a box or cylinder build.");
    }
    if (target.field === "width" || target.field === "depth") {
      if (build.type !== "box") throw new Error(`No ${target.field} on this build.`);
      build[target.field] = value;
      return next;
    }
    if (target.field === "height") {
      build.height = value;
      return next;
    }
    if (build.type !== "cylinder") throw new Error("No radius on this build.");
    build.radius = value;
    return next;
  }
  if (op.type !== "part") throw new Error("Feature parameters need a part.");
  const feature = op.features[target.index];
  if (feature === undefined) throw new Error("Feature index out of range.");
  if (target.field === "diameter") {
    if (feature.type !== "hole") throw new Error("Diameter needs a hole feature.");
    feature.diameter = value;
    return next;
  }
  if (target.field === "depth") {
    if (feature.type !== "hole" || feature.through || feature.depth === null) {
      throw new Error("Depth needs a blind hole feature.");
    }
    feature.depth = value;
    return next;
  }
  if (feature.type !== "fillet") throw new Error("Radius needs a fillet feature.");
  feature.radius = value;
  return next;
}

/** "Adjusted width 100 → 120 mm" / multi-change joined with commas. */
export function summarizeAdjustments(
  descriptors: ParameterDescriptor[],
  editedValues: Record<string, number>,
): string {
  const parts: string[] = [];
  for (const d of descriptors) {
    const next = editedValues[d.key];
    if (next === undefined || next === d.value) continue;
    parts.push(`${d.label.toLowerCase()} ${fmt(d.value)} → ${fmt(next)} mm`);
  }
  return parts.length > 0 ? `Adjusted ${parts.join(", ")}` : "Adjusted parameters";
}

function fmt(value: number): string {
  return String(Math.round(value * 1000) / 1000);
}

/** Structural equality for preview reuse (Phase 7): same JSON, same spec. */
export function specsEqualJson(
  a: DocumentSpecification,
  b: DocumentSpecification,
): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function buildOf(spec: DocumentSpecification): BoxOperation | CylinderOperation | null {
  if (spec.document_type !== "3d_part") return null;
  const build = spec.operation.type === "part" ? spec.operation.build : spec.operation;
  return build.type === "box" || build.type === "cylinder" ? build : null;
}

/**
 * Client-side live scale from the displayed mesh's spec to the edited spec.
 * Lets box/cylinder dial drags update the mesh immediately (no roundtrip);
 * feature-only edits return identity/null until the debounced rebuild lands.
 */
export function computeLiveScale(
  from: DocumentSpecification,
  to: DocumentSpecification,
): [number, number, number] | null {
  const a = buildOf(from);
  const b = buildOf(to);
  if (a === null || b === null || a.type !== b.type) return null;
  if (a.type === "box" && b.type === "box") {
    if (a.width <= 0 || a.depth <= 0 || a.height <= 0) return null;
    const scale: [number, number, number] = [
      b.width / a.width,
      b.depth / a.depth,
      b.height / a.height,
    ];
    return isNearlyOne(scale) ? null : scale;
  }
  if (a.type === "cylinder" && b.type === "cylinder") {
    if (a.radius <= 0 || a.height <= 0) return null;
    const scale: [number, number, number] = [
      b.radius / a.radius,
      b.radius / a.radius,
      b.height / a.height,
    ];
    return isNearlyOne(scale) ? null : scale;
  }
  return null;
}

function isNearlyOne(scale: [number, number, number]): boolean {
  return scale.every((s) => Math.abs(s - 1) < 1e-6);
}
