"use client";

import type { GenerateResponse } from "@/types/api";
import {
  formatBytes,
  humanizeName,
  operationLabel,
  sortFeatures,
  summarizeDimensions,
  summarizeFeature,
  describeTree,
} from "@/lib/spec";

interface SpecPanelProps {
  result: GenerateResponse;
}

export function SpecPanel({ result }: SpecPanelProps) {
  const spec = result.specification;
  const op = spec.operation;
  const dimensions = summarizeDimensions(op);
  const tree =
    op.type === "union" || op.type === "cut" || op.type === "intersect"
      ? describeTree(op)
      : null;
  const features =
    op.type === "part" ? sortFeatures(op.features) : null;
  const totalBytes = result.files.step.bytes + result.files.stl.bytes;

  return (
    <section
      className="panel"
      aria-labelledby="spec-heading"
      data-testid="spec-panel"
    >
      <h2 id="spec-heading" className="kicker">
        <span className="kicker-index">02</span>
        <span className="kicker-label">Specification</span>
        <span className="kicker-rule" aria-hidden="true" />
      </h2>

      <p className="spec-name">{humanizeName(spec.name)}</p>

      <dl className="spec-grid">
        <div className="spec-row">
          <dt>Type</dt>
          <dd>{operationLabel(op)}</dd>
        </div>
        <div className="spec-row">
          <dt>Units</dt>
          <dd>{result.units}</dd>
        </div>
        <div className="spec-row">
          <dt>Generated</dt>
          <dd className="mono">{result.generation_time_ms} ms</dd>
        </div>
        <div className="spec-row">
          <dt>Request</dt>
          <dd className="mono">{result.request_id.slice(0, 12)}…</dd>
        </div>
      </dl>

      <h3 className="spec-subtitle">Dimensions</h3>
      <dl className="spec-grid">
        {dimensions.map((row) => (
          <div className="spec-row" key={row.label}>
            <dt>{row.label}</dt>
            <dd className="mono">{row.value}</dd>
          </div>
        ))}
      </dl>

      {features && features.length > 0 ? (
        <>
          <h3 className="spec-subtitle">Features</h3>
          <ul className="op-tree">
            {features.map((feature, index) => (
              <li key={`${feature.type}-${index}`}>
                <span className="mono">{summarizeFeature(feature)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {tree ? (
        <>
          <h3 className="spec-subtitle">Operation tree</h3>
          <ul className="op-tree">
            {tree.map((line, index) => (
              <li
                key={`${line.depth}-${line.text}-${index}`}
                style={{ paddingLeft: `${line.depth * 1.1}rem` }}
              >
                <span className="mono">{line.text}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <div className="build-row">
        <span className="build-check" aria-hidden="true">
          ✓
        </span>
        <span>BUILD · CGEN M6</span>
        <span className="mono">
          STEP+STL {formatBytes(totalBytes)} · VALIDATED
        </span>
      </div>
    </section>
  );
}
