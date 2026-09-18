"use client";

import type { GenerateResponse } from "@/types/api";
import {
  describeTree,
  humanizeName,
  operationLabel,
  summarizeDimensions,
} from "@/lib/spec";

interface SpecPanelProps {
  result: GenerateResponse;
}

export function SpecPanel({ result }: SpecPanelProps) {
  const spec = result.specification;
  const op = spec.operation;
  const dimensions = summarizeDimensions(op);
  const tree = op.type === "union" || op.type === "cut" ? describeTree(op) : null;

  return (
    <section className="panel" aria-labelledby="spec-heading" data-testid="spec-panel">
      <h2 id="spec-heading" className="panel-title">
        Specification
      </h2>
      <p className="spec-name">{humanizeName(spec.name)}</p>
      <dl className="spec-grid">
        <div className="spec-row">
          <dt>Type</dt>
          <dd>3D Part</dd>
        </div>
        <div className="spec-row">
          <dt>Units</dt>
          <dd>{result.units}</dd>
        </div>
        <div className="spec-row">
          <dt>Operation</dt>
          <dd>{operationLabel(op)}</dd>
        </div>
        <div className="spec-row">
          <dt>Generated</dt>
          <dd>{result.generation_time_ms} ms</dd>
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
    </section>
  );
}
