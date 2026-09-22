"use client";

import type { SceneObject } from "@/lib/assembly";

interface AssemblyTreeProps {
  name: string;
  objects: SceneObject[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onToggleVisible: (id: string) => void;
  onRemove: (id: string) => void;
  onFocus?: (id: string) => void;
  busy: boolean;
}

export function AssemblyTree({
  name,
  objects,
  selectedId,
  onSelect,
  onToggleVisible,
  onRemove,
  busy,
}: AssemblyTreeProps) {
  return (
    <section className="inspector-section" data-testid="assembly-tree">
      <div className="inspector-label">Assembly</div>
      <p className="assembly-root">{name}</p>
      {objects.length === 0 ? (
        <p className="inspector-empty-inline">No objects yet. Add a component or generate.</p>
      ) : (
        <ul className="assembly-list">
          {objects.map((object) => {
            const extra =
              object.instances.length > 1 ? ` × ${object.instances.length}` : "";
            const selected = object.id === selectedId;
            return (
              <li key={object.id}>
                <button
                  type="button"
                  className={`assembly-item${selected ? " selected" : ""}`}
                  onClick={() => onSelect(object.id)}
                  disabled={busy}
                  aria-current={selected ? "true" : undefined}
                >
                  <span className="assembly-item-name">
                    {object.name}
                    {extra}
                  </span>
                  <span className="assembly-item-type">{object.componentType}</span>
                </button>
                <button
                  type="button"
                  className="assembly-icon"
                  onClick={() => onToggleVisible(object.id)}
                  disabled={busy}
                  aria-label={object.visible ? `Hide ${object.name}` : `Show ${object.name}`}
                  title={object.visible ? "Hide" : "Show"}
                >
                  {object.visible ? "●" : "○"}
                </button>
                <button
                  type="button"
                  className="assembly-icon danger"
                  onClick={() => onRemove(object.id)}
                  disabled={busy || objects.length < 2}
                  aria-label={`Remove ${object.name}`}
                  title="Remove"
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
