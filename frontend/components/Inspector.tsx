"use client";

/**
 * Inspector - persistent right-hand sidebar showing part specification,
 * features, output files, and validation. Replaces the old SpecPanel +
 * Downloads combo with a denser, CAD-inspector-style layout.
 */
import { Downloads } from "./Downloads";
import { RevisionHistory } from "./RevisionHistory";
import { SpecPanel } from "./SpecPanel";
import type { GenerateResponse } from "@/types/api";
import type { Workspace } from "@/types/revisions";

interface InspectorProps {
  result: GenerateResponse | null;
  status: string;
  workspace: Workspace;
  onSelectRevision: (revisionId: string) => void;
}

export function Inspector({
  result,
  status,
  workspace,
  onSelectRevision,
}: InspectorProps) {
  return (
    <>
      <div className="inspector-header">Inspector</div>
      <div className="inspector-body">
        <RevisionHistory workspace={workspace} onSelect={onSelectRevision} />
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
