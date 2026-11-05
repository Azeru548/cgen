/** Pure assembly / scene helpers. No React, no I/O.

 *  A 3d_part is treated as a one-object scene so the viewer, tree and
 *  inspector share one model. Selection and draft transforms live in the UI
 *  and never write a revision until an explicit commit.
 */
import type {
  AssemblyGroup,
  AssemblySpecification,
  CadSpecification,
  CatalogComponent,
  ComponentInstance,
  DocumentSpecification,
  GenerateResponse,
  ParamValue,
  Transform,
} from "@/types/api";
import { centroid, rotatePose, type Vec3 } from "@/lib/transforms";

export interface SceneObject {
  id: string;
  componentType: string;
  name: string;
  parameters: Record<string, ParamValue>;
  transform: Transform;
  visible: boolean;
  instances: Transform[];
  stlUrl: string | null;
  parameterized: boolean;
  locked: boolean;
}

export function isPartSpec(spec: DocumentSpecification): spec is CadSpecification {
  return spec.document_type === "3d_part";
}

export function isAssemblySpec(
  spec: DocumentSpecification,
): spec is AssemblySpecification {
  return spec.document_type === "3d_assembly";
}

export function identityTransform(): Transform {
  return { position: [0, 0, 0], rotation: [0, 0, 0] };
}

export function posesOf(component: ComponentInstance): Transform[] {
  if (component.instances.length > 0) return component.instances;
  return [component.transform];
}

export function sceneObjects(
  response: GenerateResponse,
  resolveUrl: (path: string) => string,
  catalog: CatalogComponent[],
): SceneObject[] {
  const spec = response.specification;
  if (isPartSpec(spec)) {
    return [
      {
        id: "generated_1",
        componentType: "generated_part",
        name: spec.name,
        parameters: {},
        transform: identityTransform(),
        visible: true,
        instances: [],
        stlUrl: resolveUrl(response.files.stl.download_url),
        parameterized: true,
        locked: false,
      },
    ];
  }
  const byType = new Map(catalog.map((c) => [c.type, c]));
  return spec.components.map((component) => {
    const files = response.component_files?.[component.id];
    const stlPath = files?.stl.download_url ?? null;
    const def = byType.get(component.component_type);
    return {
      id: component.id,
      componentType: component.component_type,
      name: component.name,
      parameters: component.parameters,
      transform: component.transform,
      visible: component.visible,
      instances: component.instances,
      stlUrl: stlPath ? resolveUrl(stlPath) : null,
      parameterized: def?.parameterized ?? Object.keys(component.parameters).length > 0,
      locked: component.locked === true,
    };
  });
}

export function selectedComponent(
  spec: DocumentSpecification,
  selectedId: string | null,
): ComponentInstance | CadSpecification | null {
  if (selectedId === null) return null;
  if (isPartSpec(spec)) {
    return selectedId === "generated_1" ? spec : null;
  }
  return spec.components.find((c) => c.id === selectedId) ?? null;
}

export function assemblyName(spec: DocumentSpecification): string {
  return spec.name;
}

export function componentCount(spec: DocumentSpecification): number {
  if (isPartSpec(spec)) return 1;
  return spec.components.length;
}

/** Draft overlay: replace one component's pose/visibility/name without a revision. */
export function withComponentPatch(
  spec: AssemblySpecification,
  componentId: string,
  patch: Partial<Pick<ComponentInstance, "transform" | "visible" | "name" | "parameters">>,
): AssemblySpecification {
  return {
    ...spec,
    components: spec.components.map((c) =>
      c.id === componentId ? { ...c, ...patch } : c,
    ),
  };
}

// --- Groups (schema 4.1) -----------------------------------------------------

/** Groups on an assembly; a single-part document has none. */
export function groupsOf(spec: DocumentSpecification): AssemblyGroup[] {
  if (!isAssemblySpec(spec)) return [];
  return spec.groups ?? [];
}

/** The group a component belongs to (groups are flat, one group max). */
export function groupForComponent(
  spec: DocumentSpecification,
  componentId: string,
): AssemblyGroup | null {
  return (
    groupsOf(spec).find((group) => group.component_ids.includes(componentId)) ??
    null
  );
}

/** Replace a document's groups without touching components or transforms. */
export function withGroups(
  spec: AssemblySpecification,
  groups: AssemblyGroup[],
): AssemblySpecification {
  return { ...spec, groups };
}

/** Deterministic `group_N` id that does not collide with existing groups. */
export function allocateGroupId(groups: AssemblyGroup[]): string {
  const taken = new Set(groups.map((group) => group.id));
  let n = 1;
  while (taken.has(`group_${n}`)) n += 1;
  return `group_${n}`;
}

/**
 * Bundle the given components into one new group. Returns null when the
 * selection cannot form a group (fewer than two objects, unknown ids, or an
 * object that already belongs to a different group).
 */
export function groupSelection(
  spec: DocumentSpecification,
  componentIds: string[],
  name: string,
): AssemblySpecification | null {
  if (!isAssemblySpec(spec)) return null;
  const ids = [...new Set(componentIds)];
  if (ids.length < 2) return null;
  const known = new Set(spec.components.map((c) => c.id));
  if (ids.some((id) => !known.has(id))) return null;
  const existing = groupsOf(spec);
  if (ids.some((id) => groupForComponent(spec, id) !== null)) return null;
  const group: AssemblyGroup = {
    id: allocateGroupId(existing),
    name: name.trim() || `Group ${existing.length + 1}`,
    component_ids: ids,
  };
  return { ...withGroups(spec, [...existing, group]), schema_version: "4.1" };
}

/** Drop every group that overlaps the selection. */
export function ungroupSelection(
  spec: DocumentSpecification,
  componentIds: string[],
): AssemblySpecification | null {
  if (!isAssemblySpec(spec)) return null;
  const selected = new Set(componentIds);
  const existing = groupsOf(spec);
  const remaining = existing.filter(
    (group) => !group.component_ids.some((id) => selected.has(id)),
  );
  if (remaining.length === existing.length) return null;
  return withGroups(spec, remaining);
}

/** Pivot for a group/selection rotation: the centroid of its components. */
export function selectionPivot(
  spec: DocumentSpecification,
  componentIds: string[],
): Vec3 {
  if (!isAssemblySpec(spec)) return [0, 0, 0];
  const selected = new Set(componentIds);
  const points = spec.components
    .filter((component) => selected.has(component.id))
    .map((component) => component.transform.position as Vec3);
  return centroid(points);
}

/**
 * Rotate the selected components about their shared pivot.
 *
 * Positions orbit the pivot and each component's own orientation picks up the
 * same delta, so a group turns rigidly instead of every part spinning about
 * its own centre. Explicit instance poses are rotated too — they are world
 * poses, not offsets.
 */
export function rotateSelection(
  spec: DocumentSpecification,
  componentIds: string[],
  delta: Vec3,
): AssemblySpecification | null {
  if (!isAssemblySpec(spec)) return null;
  const selected = new Set(componentIds);
  if (selected.size === 0) return null;
  if (delta[0] === 0 && delta[1] === 0 && delta[2] === 0) return null;
  const pivot = selectionPivot(spec, componentIds);
  let changed = false;
  const components = spec.components.map((component) => {
    if (!selected.has(component.id)) return component;
    changed = true;
    const transform = rotatePose(
      {
        position: component.transform.position as Vec3,
        rotation: component.transform.rotation as Vec3,
      },
      delta,
      pivot,
    );
    const instances = component.instances.map((pose) =>
      rotatePose(
        { position: pose.position as Vec3, rotation: pose.rotation as Vec3 },
        delta,
        pivot,
      ),
    );
    return {
      ...component,
      transform,
      instances,
    } as ComponentInstance;
  });
  if (!changed) return null;
  return { ...spec, components };
}

/** Expand a selection to include every member of any group it touches. */
export function expandSelectionToGroups(
  spec: DocumentSpecification,
  componentIds: string[],
): string[] {
  const ids = new Set(componentIds);
  for (const id of componentIds) {
    const group = groupForComponent(spec, id);
    if (group) group.component_ids.forEach((member) => ids.add(member));
  }
  return [...ids];
}

/** Persist lock/unlock on the given components. */
export function setSelectionLocked(
  spec: DocumentSpecification,
  componentIds: string[],
  locked: boolean,
): AssemblySpecification | null {
  if (!isAssemblySpec(spec)) return null;
  const selected = new Set(componentIds);
  if (selected.size === 0) return null;
  let changed = false;
  const components = spec.components.map((component) => {
    if (!selected.has(component.id) || Boolean(component.locked) === locked) {
      return component;
    }
    changed = true;
    return { ...component, locked };
  });
  if (!changed) return null;
  return {
    ...spec,
    schema_version: spec.schema_version === "4.0" ? "4.1" : spec.schema_version,
    components,
  };
}

export function transformsEqual(a: Transform, b: Transform): boolean {
  return (
    a.position[0] === b.position[0] &&
    a.position[1] === b.position[1] &&
    a.position[2] === b.position[2] &&
    a.rotation[0] === b.rotation[0] &&
    a.rotation[1] === b.rotation[1] &&
    a.rotation[2] === b.rotation[2]
  );
}
