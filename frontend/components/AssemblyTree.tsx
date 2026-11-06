"use client";

import type { AssemblyGroup } from "@/types/api";
import type { SceneObject } from "@/lib/assembly";

interface AssemblyTreeProps {
  name: string;
  objects: SceneObject[];
  groups: AssemblyGroup[];
  selectedId: string | null;
  /** Every selected object id (multi-select, superset of `selectedId`). */
  selectedIds: string[];
  onSelect: (id: string, additive: boolean) => void;
  onSelectGroup: (group: AssemblyGroup) => void;
  onToggleVisible: (id: string) => void;
  onRemove: (id: string) => void;
  onGroup: () => void;
  onUngroup: () => void;
  onLock: () => void;
  onDuplicate: () => void;
  onFocus?: (id: string) => void;
  busy: boolean;
}

export function AssemblyTree({
  name,
  objects,
  groups,
  selectedId,
  selectedIds,
  onSelect,
  onSelectGroup,
  onToggleVisible,
  onRemove,
  onGroup,
  onUngroup,
  onLock,
  onDuplicate,
  busy,
}: AssemblyTreeProps) {
  const selected = new Set(selectedIds);
  const groupedIds = new Set(groups.flatMap((group) => group.component_ids));
  const loose = objects.filter((object) => !groupedIds.has(object.id));
  const byId = new Map(objects.map((object) => [object.id, object]));
  const canGroup =
    selectedIds.length >= 2 && selectedIds.every((id) => !groupedIds.has(id));
  const canUngroup = groups.some((group) =>
    group.component_ids.some((id) => selected.has(id)),
  );
  const selectedObjects = objects.filter((object) => selected.has(object.id));
  const allLocked =
    selectedObjects.length > 0 && selectedObjects.every((object) => object.locked);
  const renderObject = (object: SceneObject, indent: boolean) => {
    const extra =
      object.instances.length > 1 ? ` × ${object.instances.length}` : "";
    const isSelected = object.id === selectedId;
    const inSelection = selected.has(object.id);
    return (
      <li key={object.id} className={indent ? "assembly-member" : undefined}>
        <button
          type="button"
          className={`assembly-tick${inSelection ? " is-on" : ""}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(object.id, true);
          }}
          disabled={busy}
          aria-pressed={inSelection}
          aria-label={
            inSelection
              ? `Remove ${object.name} from selection`
              : `Add ${object.name} to selection`
          }
          title={inSelection ? "Remove from selection" : "Add to selection"}
        />
        <button
          type="button"
          className={`assembly-item${isSelected ? " selected" : ""}${
            inSelection && !isSelected ? " co-selected" : ""
          }`}
          onClick={() => onSelect(object.id, false)}
          disabled={busy}
          aria-current={isSelected ? "true" : undefined}
          aria-pressed={inSelection}
          title="Select this part"
        >
          <span className="assembly-item-name">
            {object.name}
            {extra}
            {object.locked ? " · locked" : ""}
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
  };

  return (
    <section className="inspector-section" data-testid="assembly-tree">
      <div className="inspector-label">Assembly</div>
      <p className="assembly-root">{name}</p>
      {objects.length === 0 ? (
        <p className="inspector-empty-inline">No objects yet. Add a component or generate.</p>
      ) : (
        <ul className="assembly-list">
          {groups.map((group) => {
            const members = group.component_ids
              .map((id) => byId.get(id))
              .filter((object): object is SceneObject => object !== undefined);
            if (members.length === 0) return null;
            const groupSelected = group.component_ids.every((id) => selected.has(id));
            return (
              <li key={group.id} className="assembly-group">
                <button
                  type="button"
                  className={`assembly-group-head${groupSelected ? " selected" : ""}`}
                  onClick={() => onSelectGroup(group)}
                  disabled={busy}
                  title="Select every object in this group"
                  aria-pressed={groupSelected}
                >
                  <span className="assembly-group-mark" aria-hidden="true">
                    ▣
                  </span>
                  <span className="assembly-item-name">{group.name}</span>
                  <span className="assembly-item-type">{members.length} grouped</span>
                </button>
                <ul className="assembly-list">
                  {members.map((object) => renderObject(object, true))}
                </ul>
              </li>
            );
          })}
          {loose.map((object) => renderObject(object, false))}
        </ul>
      )}

      {objects.length > 1 ? (
        <div className="assembly-bulk" data-testid="assembly-bulk">
          <p className="assembly-bulk-count mono">
            {selectedIds.length < 2
              ? "Tick two or more parts, then Group"
              : `${selectedIds.length} selected`}
          </p>
          <div className="assembly-bulk-row">
            <button
              type="button"
              className="assembly-bulk-button"
              onClick={onGroup}
              disabled={busy || !canGroup}
              title={
                canGroup
                  ? "Group the ticked parts so they move and rotate together"
                  : "Tick two or more ungrouped parts first"
              }
            >
              Group
            </button>
            <button
              type="button"
              className="assembly-bulk-button"
              onClick={onUngroup}
              disabled={busy || !canUngroup}
              title="Ungroup the selected objects"
            >
              Ungroup
            </button>
            <button
              type="button"
              className="assembly-bulk-button"
              onClick={onLock}
              disabled={busy || selectedIds.length === 0}
              title={
                allLocked
                  ? "Unlock the selected objects"
                  : "Lock the selected objects in place"
              }
            >
              {allLocked ? "Unlock" : "Lock"}
            </button>
            <button
              type="button"
              className="assembly-bulk-button"
              onClick={onDuplicate}
              disabled={busy || selectedId === null}
              title="Copy the selected part beside itself"
            >
              Duplicate
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
