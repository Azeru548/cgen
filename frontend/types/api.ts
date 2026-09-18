/** Strict TypeScript mirrors of the cgen M4 backend contract.
 *  The frontend never reconstructs CAD geometry from these types —
 *  the specification is display/debug information only.
 *  No `any` anywhere in this file.
 */

export type OperationType =
  | "box"
  | "cylinder"
  | "cone"
  | "sphere"
  | "union"
  | "cut";

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

export interface UnionOperation {
  type: "union";
  base: CadOperation;
  tool: CadOperation;
}

export interface CutOperation {
  type: "cut";
  base: CadOperation;
  tool: CadOperation;
}

export type CadOperation =
  | BoxOperation
  | CylinderOperation
  | ConeOperation
  | SphereOperation
  | UnionOperation
  | CutOperation;

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
