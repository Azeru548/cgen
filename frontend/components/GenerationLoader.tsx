"use client";

/**
 * Generation loader — the compact walking machine plus an honest pipeline
 * readout. The browser only knows that a request is in flight, so no stage
 * is ever marked complete: every row keeps a "pending" ring, and a pure-CSS
 * staggered emphasis cycles down the ladder to show the pipeline is being
 * worked. No fake percentages, no claimed completion.
 */
import { WalkingMachine } from "./WalkingMachine";

const PIPELINE_STAGES = [
  "INTERPRETING REQUEST",
  "BUILDING CAD SPEC",
  "VALIDATING GEOMETRY",
  "GENERATING SOLID",
  "EXPORTING MODEL",
] as const;

export function GenerationLoader() {
  return (
    <div
      className="generation-loader"
      role="status"
      aria-label="Generating model"
      data-testid="generation-loader"
    >
      <div className="pipeline-title">GENERATING PROJECTION</div>
      <div className="generation-loader-machine">
        <WalkingMachine scale={0.45} />
      </div>
      <ol className="pipeline">
        {PIPELINE_STAGES.map((stage, index) => (
          <li
            key={stage}
            className="pipeline-step"
            style={{ animationDelay: `${index * 0.42}s` }}
            data-testid={`pipeline-stage-${index}`}
          >
            <span className="step-mark" aria-hidden="true">
              ○
            </span>
            {stage}
          </li>
        ))}
      </ol>
    </div>
  );
}
