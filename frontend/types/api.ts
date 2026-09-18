/** Strict TypeScript mirrors of the cgen backend contract (schema v3.0, M6).
 *  The frontend never reconstructs CAD geometry from these types —
 *  the specification is display/debug information only.
 *  No `any` anywhere in this file.
 */

export type OperationType =
  | "box"
  | "cylinder"
  | "cone"
  | "sphere"
  | "torus"
  | "polygon_prism"
  | "union"
  | "cut"
  | "intersect"
  | "part";

export interface BoxOperation {
  type: "box";
  width: number;
  depth: number;
  height: number;
}

export interface CylinderOperation {
  type: "cylinder";
  radius: number;
  height: number;
  through: boolean;
}

export interface ConeOperation {
  type: "cone";
  bottom_radius: number;
  top_radius: number;
  height: number;
}

export interface SphereOperation {
  type: "sphere";
  radius: number;
}

export interface TorusOperation {
  type: "torus";
  major_radius: number;
  minor_radius: number;
}

export interface PolygonPrismOperation {
  type: "polygon_prism";
  sides: number;
  circumradius: number;
  height: number;
}

export interface UnionOperation {
  type: "union";
  base: BuildOperation;
  tool: BuildOperation;
}

export interface CutOperation {
  type: "cut";
  base: BuildOperation;
  tool: BuildOperation;
}

export interface IntersectOperation {
  type: "intersect";
  base: BuildOperation;
  tool: BuildOperation;
}

/** M6 engineering features (applied by the engine in its own fixed order). */
export interface HoleFeature {
  type: "hole";
  diameter: number;
  through: boolean;
  depth: number | null;
}

export interface FilletFeature {
  type: "fillet";
  radius: number;
}

export interface ChamferFeature {
  type: "chamfer";
  size: number;
}

export interface ShellFeature {
  type: "shell";
  thickness: number;
}

export type CadFeature =
  | HoleFeature
  | FilletFeature
  | ChamferFeature
  | ShellFeature;

/** A built solid plus deterministic engineering features. */
export interface PartOperation {
  type: "part";
  build: BuildOperation;
  features: CadFeature[];
}

/** Anything that can appear inside a composition or as a part build. */
export type BuildOperation =
  | BoxOperation
  | CylinderOperation
  | ConeOperation
  | SphereOperation
  | TorusOperation
  | PolygonPrismOperation
  | UnionOperation
  | CutOperation
  | IntersectOperation;

export type CadOperation = BuildOperation | PartOperation;

export interface CadSpecification {
  document_type: "3d_part";
  units: "mm";
  name: string;
  operation: CadOperation;
}

export type CadFileFormat = "step" | "stl";

export interface FileMetadata {
  format: CadFileFormat;
  filename: string;
  bytes: number;
  download_url: string;
}

export interface GenerateResponse {
  status: "completed";
  request_id: string;
  specification: CadSpecification;
  units: string;
  generation_time_ms: number;
  files: {
    step: FileMetadata;
    stl: FileMetadata;
  };
}

export interface BackendHealth {
  status: string;
  service: string;
  cadquery_available: boolean;
  cadquery_version: string | null;
}
