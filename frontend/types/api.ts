/** Strict TypeScript mirrors of the cgen backend contract (schema v3.2).
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

/** v3.1: N identical holes on a deterministic bolt circle (one feature). */
export interface HolePatternFeature {
  type: "hole_pattern";
  diameter: number;
  count: number;
  circle_diameter: number;
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

/** v3.2: rows×cols identical holes on a deterministic centered grid.
 *  The spacing on a single-hole axis is null (1×N row: spacing_y null). */
export interface HoleGridFeature {
  type: "hole_grid";
  diameter: number;
  rows: number;
  cols: number;
  spacing_x: number | null;
  spacing_y: number | null;
  through: boolean;
  depth: number | null;
}

export type CadFeature =
  | HoleFeature
  | HolePatternFeature
  | HoleGridFeature
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

export type RelationshipType =
  | "positioned_at"
  | "attached_to"
  | "aligned_with"
  | "repeated_from"
  | "mounted_on"
  | "centered_on";

export interface Transform {
  position: [number, number, number];
  rotation: [number, number, number];
}

export interface Relationship {
  type: RelationshipType;
  target_id: string;
}

export type ParamValue = number | boolean | string;

export interface ComponentInstance {
  id: string;
  component_type: string;
  name: string;
  parameters: Record<string, ParamValue>;
  transform: Transform;
  visible: boolean;
  instances: Transform[];
  relationships: Relationship[];
  generated?: CadSpecification | null;
}

export interface AssemblySpecification {
  document_type: "3d_assembly";
  units: "mm";
  name: string;
  schema_version: "4.0";
  components: ComponentInstance[];
}

export type DocumentSpecification = CadSpecification | AssemblySpecification;

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
  specification: DocumentSpecification;
  units: string;
  generation_time_ms: number;
  files: {
    step: FileMetadata;
    stl: FileMetadata;
  };
  component_files?: Record<string, { step: FileMetadata; stl: FileMetadata }>;
}

export type ComponentCategory =
  | "geometry"
  | "fasteners"
  | "mechanical"
  | "electronics"
  | "robotics"
  | "templates";

export interface CatalogParam {
  key: string;
  label: string;
  kind: "length" | "count" | "choice" | "flag";
  default: ParamValue;
  min: number | null;
  max: number | null;
  options: string[] | null;
  unit: string | null;
  description: string;
}

export interface CatalogComponent {
  type: string;
  category: ComponentCategory;
  display_name: string;
  description: string;
  insertable: boolean;
  parameterized: boolean;
  has_mounting_points: boolean;
  parameters: CatalogParam[];
}

export interface ComponentsCatalog {
  schema_version: string;
  components: CatalogComponent[];
}

export interface BackendHealth {
  status: string;
  service: string;
  cadquery_available: boolean;
  cadquery_version: string | null;
}
