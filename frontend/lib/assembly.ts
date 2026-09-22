/** Pure assembly / scene helpers. No React, no I/O.

 *  A 3d_part is treated as a one-object scene so the viewer, tree and
 *  inspector share one model. Selection and draft transforms live in the UI
 *  and never write a revision until an explicit commit.
 */
import type {
  AssemblySpecification,
  CadSpecification,
  CatalogComponent,
  ComponentInstance,
  DocumentSpecification,
  GenerateResponse,
  ParamValue,
  Transform,
} from "@/types/api";

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
