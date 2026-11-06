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
  MotionKey,
  MotionTrack,
  ParamValue,
  SceneAnimation,
  Transform,
} from "@/types/api";
import { centroid, rotatePose, rotatePoint, type Vec3 } from "@/lib/transforms";
import { humanizeName } from "@/lib/spec";

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

/** Lift a single 3d_part response into a one-object assembly, reusing its files. */
export function promoteResponseToAssembly(
  response: GenerateResponse,
): GenerateResponse {
  const spec = response.specification;
  if (isAssemblySpec(spec)) return response;
  const assembly: AssemblySpecification = {
    document_type: "3d_assembly",
    units: "mm",
    name: spec.name,
    schema_version: "4.1",
    components: [
      {
        id: "generated_1",
        component_type: "generated_part",
        name: spec.name,
        parameters: {},
        transform: identityTransform(),
        visible: true,
        instances: [],
        relationships: [],
        generated: spec,
        locked: false,
      },
    ],
    groups: [],
  };
  return {
    ...response,
    specification: assembly,
    component_files: {
      generated_1: {
        step: response.files.step,
        stl: response.files.stl,
      },
      ...response.component_files,
    },
  };
}

/** Commit pose/name/visibility without regenerating meshes. */
export function applyPlacementToResponse(
  response: GenerateResponse,
  componentId: string,
  patch: Partial<
    Pick<ComponentInstance, "transform" | "visible" | "name" | "instances">
  >,
): GenerateResponse | null {
  const promoted = promoteResponseToAssembly(response);
  const spec = promoted.specification;
  if (!isAssemblySpec(spec)) return null;
  if (!spec.components.some((component) => component.id === componentId)) {
    return null;
  }
  return {
    ...promoted,
    specification: {
      ...spec,
      components: spec.components.map((component) =>
        component.id === componentId ? { ...component, ...patch } : component,
      ),
    },
  };
}

/**
 * Bake the scene as displayed into a response: current poses, names, visibility
 * and instance lists, with parameters and groups untouched.
 *
 * Scene-level actions (lock, group, ungroup) commit a specification without a
 * rebuild. If they started from the last *committed* revision, an unsaved drag
 * would be discarded and the object would snap back to its old pose — this is
 * what makes those actions preserve what the user is looking at.
 */
export function bakeDisplayedScene(
  response: GenerateResponse,
  objects: SceneObject[],
): GenerateResponse {
  let next = response;
  for (const object of objects) {
    next =
      applyPlacementToResponse(next, object.id, {
        name: object.name,
        transform: object.transform,
        visible: object.visible,
        instances: object.instances,
      }) ?? next;
  }
  return next;
}

/** Drop one object from the scene. Meshes of the rest stay; combined STEP is stale until remint. */
export function removeComponentFromResponse(
  response: GenerateResponse,
  componentId: string,
): GenerateResponse | null {
  const promoted = promoteResponseToAssembly(response);
  const spec = promoted.specification;
  if (!isAssemblySpec(spec)) return null;
  const remaining = spec.components.filter(
    (component) => component.id !== componentId,
  );
  if (remaining.length === spec.components.length) return null;
  if (remaining.length === 0) return null;
  const remainingIds = new Set(remaining.map((component) => component.id));
  const groups = groupsOf(spec)
    .map((group) => ({
      ...group,
      component_ids: group.component_ids.filter((id) => remainingIds.has(id)),
    }))
    .filter((group) => group.component_ids.length >= 2);
  const componentFiles = { ...(promoted.component_files ?? {}) };
  delete componentFiles[componentId];
  return {
    ...promoted,
    specification: { ...spec, components: remaining, groups },
    component_files: componentFiles,
  };
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

// --- Placement helpers (snap, seat, centre, align, duplicate) ----------------

/** Local mesh bounds in millimetres (geometry centred on its own bbox by the
 *  loader, so `min` is usually the negated half-size). */
export interface ObjectBounds {
  min: Vec3;
  size: Vec3;
}

/**
 * Axis-aligned bounds of a placed object in CAD world space.
 *
 * Rotation is applied to the local box corners first, so a part turned 45°
 * reports the box that actually contains it — which is what "seat on the
 * floor" and "centre" have to use.
 */
export function placedBounds(
  transform: Transform,
  bounds: ObjectBounds,
): { min: Vec3; max: Vec3 } {
  const [sx, sy, sz] = bounds.size;
  const [mx, my, mz] = bounds.min;
  let min: Vec3 = [Infinity, Infinity, Infinity];
  let max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const x of [mx, mx + sx]) {
    for (const y of [my, my + sy]) {
      for (const z of [mz, mz + sz]) {
        const spun = rotatePoint([x, y, z], transform.rotation as Vec3);
        const wx = spun[0] + transform.position[0];
        const wy = spun[1] + transform.position[1];
        const wz = spun[2] + transform.position[2];
        min = [Math.min(min[0], wx), Math.min(min[1], wy), Math.min(min[2], wz)];
        max = [Math.max(max[0], wx), Math.max(max[1], wy), Math.max(max[2], wz)];
      }
    }
  }
  return { min, max };
}

/** Move components (and their instance poses) by a world-space delta. */
export function translateSelection(
  spec: AssemblySpecification,
  componentIds: string[],
  delta: Vec3,
): AssemblySpecification | null {
  const selected = new Set(componentIds);
  if (selected.size === 0) return null;
  if (delta[0] === 0 && delta[1] === 0 && delta[2] === 0) return null;
  const shift = (pose: Transform): Transform => ({
    position: [
      pose.position[0] + delta[0],
      pose.position[1] + delta[1],
      pose.position[2] + delta[2],
    ],
    rotation: pose.rotation,
  });
  let changed = false;
  const components = spec.components.map((component) => {
    if (!selected.has(component.id)) return component;
    changed = true;
    return {
      ...component,
      transform: shift(component.transform),
      instances: component.instances.map(shift),
    };
  });
  if (!changed) return null;
  return { ...spec, components };
}

/**
 * Copy a component into the same assembly. The copy keeps the source's
 * parameters, nested part and STL (one definition, two placements), starts
 * unlocked, and is offset so it is not hidden inside the original.
 */
export function duplicateComponent(
  spec: AssemblySpecification,
  componentId: string,
  offset: Vec3 = [20, 0, 0],
): { specification: AssemblySpecification; id: string } | null {
  const source = spec.components.find((component) => component.id === componentId);
  if (!source) return null;
  if (spec.components.length >= 24) return null;
  const taken = new Set(spec.components.map((component) => component.id));
  const stem = source.component_type.slice(0, 30) || "part";
  let n = 1;
  while (taken.has(`${stem}_${n}`)) n += 1;
  const id = `${stem}_${n}`;
  const shift = (pose: Transform): Transform => ({
    position: [
      pose.position[0] + offset[0],
      pose.position[1] + offset[1],
      pose.position[2] + offset[2],
    ],
    rotation: pose.rotation,
  });
  const copy: ComponentInstance = {
    ...source,
    id,
    name: `${source.name} copy`.slice(0, 80),
    transform: shift(source.transform),
    instances: source.instances.map(shift),
    relationships: [],
    locked: false,
  };
  return {
    specification: { ...spec, components: [...spec.components, copy] },
    id,
  };
}

// --- Bill of materials -------------------------------------------------------

export interface BomRow {
  type: string;
  label: string;
  /** Physical parts: instances count once per pose, not once per component. */
  quantity: number;
  /** How many component entries use this type. */
  components: number;
}

/** Group an assembly's components by registry type and count the parts. */
export function bomRows(spec: DocumentSpecification): BomRow[] {
  if (!isAssemblySpec(spec)) return [];
  const rows = new Map<string, BomRow>();
  for (const component of spec.components) {
    const quantity = component.instances.length > 0 ? component.instances.length : 1;
    const existing = rows.get(component.component_type);
    if (existing) {
      existing.quantity += quantity;
      existing.components += 1;
    } else {
      rows.set(component.component_type, {
        type: component.component_type,
        label: humanizeName(component.component_type),
        quantity,
        components: 1,
      });
    }
  }
  return [...rows.values()].sort((a, b) =>
    b.quantity - a.quantity || a.type.localeCompare(b.type),
  );
}

// --- Motion (viewer metadata) -------------------------------------------------

export const MAX_MOTION_KEYS = 24;
export const MAX_MOTION_TRACKS = 24;
export const DEFAULT_MOTION_DURATION = 4;

function poseOf(key: MotionKey): { position: Vec3; rotation: Vec3 } {
  return {
    position: [key.position[0], key.position[1], key.position[2]],
    rotation: [key.rotation[0], key.rotation[1], key.rotation[2]],
  };
}

/** Shortest-path interpolation so 350° → 10° turns 20°, not 340°. */
function lerpAngle(from: number, to: number, u: number): number {
  const delta = ((((to - from) % 360) + 540) % 360) - 180;
  return from + delta * u;
}

/** Pose of a track at `time`. Holds the end poses outside the key range. */
export function sampleTrack(
  track: MotionTrack,
  time: number,
): { position: Vec3; rotation: Vec3 } {
  const keys = track.keys;
  if (keys.length === 0) return { position: [0, 0, 0], rotation: [0, 0, 0] };
  if (keys.length === 1 || time <= keys[0].t) return poseOf(keys[0]);
  const last = keys[keys.length - 1];
  if (time >= last.t) return poseOf(last);
  for (let i = 0; i < keys.length - 1; i += 1) {
    const a = keys[i];
    const b = keys[i + 1];
    if (time >= a.t && time <= b.t) {
      const span = b.t - a.t;
      const u = span <= 0 ? 0 : (time - a.t) / span;
      return {
        position: [
          a.position[0] + (b.position[0] - a.position[0]) * u,
          a.position[1] + (b.position[1] - a.position[1]) * u,
          a.position[2] + (b.position[2] - a.position[2]) * u,
        ],
        rotation: [
          lerpAngle(a.rotation[0], b.rotation[0], u),
          lerpAngle(a.rotation[1], b.rotation[1], u),
          lerpAngle(a.rotation[2], b.rotation[2], u),
        ],
      };
    }
  }
  return poseOf(last);
}

export function animationOf(spec: DocumentSpecification): SceneAnimation | null {
  if (!isAssemblySpec(spec)) return null;
  const animation = spec.animation;
  if (!animation || animation.tracks.length === 0) return null;
  return animation;
}

export function trackFor(
  spec: DocumentSpecification,
  componentId: string,
): MotionTrack | null {
  return (
    animationOf(spec)?.tracks.find(
      (track) => track.component_id === componentId,
    ) ?? null
  );
}

/** Add or replace the key at `time` (within 20 ms) and keep keys time-sorted. */
export function keyAt(
  track: MotionTrack,
  time: number,
  pose: { position: Vec3; rotation: Vec3 },
): MotionTrack {
  const key: MotionKey = {
    t: Math.max(0, time),
    position: [pose.position[0], pose.position[1], pose.position[2]],
    rotation: [pose.rotation[0], pose.rotation[1], pose.rotation[2]],
  };
  const kept = track.keys.filter((existing) => Math.abs(existing.t - key.t) > 0.02);
  const keys = [...kept, key]
    .sort((a, b) => a.t - b.t)
    .slice(0, MAX_MOTION_KEYS);
  return { ...track, keys };
}

export function withoutKey(track: MotionTrack, index: number): MotionTrack {
  return { ...track, keys: track.keys.filter((_, i) => i !== index) };
}

/** Write one track into the scene (an empty key list removes the track). */
export function withTrack(
  spec: AssemblySpecification,
  track: MotionTrack | null,
): AssemblySpecification {
  const current = spec.animation ?? {
    duration: DEFAULT_MOTION_DURATION,
    tracks: [],
  };
  const others = current.tracks.filter(
    (item) => item.component_id !== track?.component_id,
  );
  const tracks =
    track === null || track.keys.length === 0 ? others : [...others, track];
  return {
    ...spec,
    animation: { duration: current.duration, tracks },
  };
}

export function setAnimationDuration(
  spec: AssemblySpecification,
  duration: number,
): AssemblySpecification {
  const current = spec.animation ?? { duration: DEFAULT_MOTION_DURATION, tracks: [] };
  const next = Math.max(0.2, Math.min(120, duration));
  return {
    ...spec,
    animation: {
      duration: next,
      tracks: current.tracks.map((track) => ({
        ...track,
        keys: track.keys.filter((key) => key.t <= next),
      })),
    },
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
