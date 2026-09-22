"use client";

/**
 * ParametricPanel - compact M8.1 direct-adjustment controls.
 *
 * Presentational only: sliders/inputs emit transient previews; commits are
 * explicit (Apply / Enter) so releasing a dial never rewrites the session.
 * All rebuild/revision orchestration lives in the page. Renders nothing
 * when the current spec exposes no parameters.
 */
import type { ParameterDescriptor } from "@/lib/parameters";

interface ParametricPanelProps {
  params: ParameterDescriptor[];
  values: Record<string, number>;
  busy: boolean;
  previewing: boolean;
  error: string | null;
  canCommit: boolean;
  onPreview: (key: string, value: number) => void;
  onCommit: () => void;
}

function displayValue(param: ParameterDescriptor, values: Record<string, number>): number {
  return values[param.key] ?? param.value;
}

function clampInput(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function ParametricPanel({
  params,
  values,
  busy,
  previewing,
  error,
  canCommit,
  onPreview,
  onCommit,
}: ParametricPanelProps) {
  if (params.length === 0) return null;

  const renderRow = (param: ParameterDescriptor) => {
    const shown = displayValue(param, values);
    return (
      <div className="param-row" key={param.key}>
        <div className="param-head">
          <label className="param-label" htmlFor={`param-${param.key}`}>
            {param.label}
          </label>
          <span className="param-value">
            <input
              id={`param-${param.key}`}
              className="param-input"
              type="number"
              min={param.min}
              max={param.max}
              step={param.step}
              value={shown}
              disabled={busy}
              aria-label={`${param.label} exact value in millimeters`}
              onChange={(e) => {
                const next = clampInput(e.target.value);
                if (next !== null) onPreview(param.key, next);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  onCommit();
                }
              }}
            />
            <span className="param-unit" aria-hidden="true">
              {param.unit}
            </span>
          </span>
        </div>
        <input
          className="param-slider"
          type="range"
          min={Math.min(param.min, shown)}
          max={Math.max(param.max, shown)}
          step={param.step}
          value={shown}
          disabled={busy}
          aria-label={`${param.label} slider in millimeters`}
          onChange={(e) => onPreview(param.key, Number(e.target.value))}
        />
      </div>
    );
  };

  const dimensions = params.filter((p) => p.category === "dimensions");
  const features = params.filter((p) => p.category === "features");

  return (
    <div className="inspector-section" aria-label="Parametric adjustment">
      <div className="inspector-label">Parameters · local, no AI</div>
      {dimensions.length > 0 ? (
        <>
          <div className="param-group">Dimensions</div>
          {dimensions.map(renderRow)}
        </>
      ) : null}
      {features.length > 0 ? (
        <>
          <div className="param-group">Features</div>
          {features.map(renderRow)}
        </>
      ) : null}
      {error ? (
        <div className="param-error" role="alert">
          {error}
        </div>
      ) : null}
      {previewing && !error ? (
        <div className="param-hint" role="status">
          Updating preview…
        </div>
      ) : null}
      <button
        className="param-apply"
        onClick={onCommit}
        disabled={!canCommit || busy}
        title="Commit the current values as one new revision"
      >
        {busy ? "Applying…" : previewing ? "Updating…" : "Apply adjustment"}
      </button>
    </div>
  );
}
