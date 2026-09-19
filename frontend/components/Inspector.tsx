"use client";

/**
 * Inspector - persistent right-hand sidebar showing part specification,
 * features, output files, and validation. Replaces the old SpecPanel +
 * Downloads combo with a denser, CAD-inspector-style layout.
 */
import { Downloads } from "./Downloads";
import { SpecPanel } from "./SpecPanel";
import type { GenerateResponse } from "@/types/api";

interface InspectorProps {
  result: GenerateResponse | null;
  status: string;
}

export function Inspector({ result, status }: InspectorProps) {
  return (
    <>
      <div className="inspector-header">Inspector</div>
      <div className="inspector-body">
        {result && status === "ready" ? (
          <SpecPanel result={result} />
        ) : (
          <div className="inspector-empty">
            {status === "generating"
              ? "Generating model..."
              : "No specification yet. Describe a part and click Generate."}
          </div>
        )}
        {result && status === "ready" ? <Downloads result={result} /> : null}
      </div>
    </>
  );
}
