"use client";

import type { CatalogComponent, ParamValue } from "@/types/api";
import type { SceneObject } from "@/lib/assembly";
import { formatMm } from "@/lib/spec";

interface ObjectInspectorProps {
  object: SceneObject | null;
  catalog: CatalogComponent[];
  draftName: string;
  draftPosition: [number, number, number];
  draftRotation: [number, number, number];
  draftParams: Record<string, ParamValue>;
  placementDirty: boolean;
  paramsDirty: boolean;
  busy: boolean;
  onName: (value: string) => void;
  onPosition: (axis: 0 | 1 | 2, value: number) => void;
  onRotation: (axis: 0 | 1 | 2, value: number) => void;
  onParam: (key: string, value: ParamValue) => void;
  onApplyPlacement: () => void;
  onApplyParams: () => void;
}

export function ObjectInspector({
  object,
  catalog,
  draftName,
  draftPosition,
  draftRotation,
  draftParams,
  placementDirty,
  paramsDirty,
  busy,
  onName,
  onPosition,
  onRotation,
  onParam,
  onApplyPlacement,
  onApplyParams,
}: ObjectInspectorProps) {
  if (object === null) {
    return (
      <section className="inspector-section" data-testid="object-inspector">
        <div className="inspector-label">Object</div>
        <p className="inspector-empty-inline">Select an object in the tree or viewport.</p>
      </section>
    );
  }
  const def = catalog.find((c) => c.type === object.componentType);
  return (
    <section className="inspector-section" data-testid="object-inspector">
      <div className="inspector-label">Object</div>
      <label className="object-field">
        <span>Name</span>
        <input
          className="object-input"
          value={draftName}
          onChange={(e) => onName(e.target.value)}
          disabled={busy}
        />
      </label>
      <p className="object-type mono">{object.componentType}</p>
      <h3 className="spec-subtitle">Placement</h3>
      <div className="object-xyz">
        {(["X", "Y", "Z"] as const).map((label, i) => (
          <label key={label} className="object-field">
            <span>{label} mm</span>
            <input
              className="object-input mono"
              type="number"
              step={0.5}
              value={draftPosition[i]}
              onChange={(e) => onPosition(i as 0 | 1 | 2, Number(e.target.value))}
              disabled={busy}
            />
          </label>
        ))}
      </div>
      <div className="object-xyz">
        {(["RX", "RY", "RZ"] as const).map((label, i) => (
          <label key={label} className="object-field">
            <span>{label} °</span>
            <input
              className="object-input mono"
              type="number"
              step={1}
              value={draftRotation[i]}
              onChange={(e) => onRotation(i as 0 | 1 | 2, Number(e.target.value))}
              disabled={busy}
            />
          </label>
        ))}
      </div>
      <button
        type="button"
        className="object-apply"
        disabled={busy || !placementDirty}
        onClick={onApplyPlacement}
      >
        Apply placement
      </button>
      {def && def.parameters.length > 0 ? (
        <>
          <h3 className="spec-subtitle">Parameters</h3>
          {def.parameters.map((param) => {
            const value = draftParams[param.key] ?? param.default;
            if (param.kind === "flag") {
              return (
                <label key={param.key} className="object-check">
                  <input
                    type="checkbox"
                    checked={value === true}
                    disabled={busy}
                    onChange={(e) => onParam(param.key, e.target.checked)}
                  />
                  {param.label}
                </label>
              );
            }
            if (param.kind === "choice" && param.options) {
              return (
                <label key={param.key} className="object-field">
                  <span>{param.label}</span>
                  <select
                    className="object-input"
                    value={String(value)}
                    disabled={busy}
                    onChange={(e) => onParam(param.key, e.target.value)}
                  >
                    {param.options.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </label>
              );
            }
            return (
              <label key={param.key} className="object-field">
                <span>
                  {param.label}
                  {param.unit ? ` (${param.unit})` : ""}
                </span>
                <input
                  className="object-input mono"
                  type="number"
                  step={param.kind === "count" ? 1 : 0.5}
                  min={param.min ?? undefined}
                  max={param.max ?? undefined}
                  value={typeof value === "number" ? value : Number(value)}
                  disabled={busy}
                  onChange={(e) =>
                    onParam(
                      param.key,
                      param.kind === "count"
                        ? Number.parseInt(e.target.value, 10)
                        : Number(e.target.value),
                    )
                  }
                />
              </label>
            );
          })}
          <button
            type="button"
            className="object-apply mint"
            disabled={busy || !paramsDirty}
            onClick={onApplyParams}
          >
            Apply parameters
          </button>
        </>
      ) : (
        <p className="inspector-empty-inline">
          {object.componentType === "generated_part"
            ? "Use Adjust below for this generated part."
            : "This component has no numeric parameters."}
        </p>
      )}
      <p className="object-meta mono">
        {object.instances.length > 1
          ? `${object.instances.length} instances`
          : `pos ${formatMm(draftPosition[0])}, ${formatMm(draftPosition[1])}, ${formatMm(draftPosition[2])}`}
      </p>
    </section>
  );
}
