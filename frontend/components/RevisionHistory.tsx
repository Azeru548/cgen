"use client";

/**
 * RevisionHistory - append-only list of a workspace's revisions.
 * Selecting an entry re-views it (read-only time travel); the next
 * generate/modify branches a new child revision off it. Nothing is
 * ever overwritten or deleted here.
 */
import type { Workspace } from "@/types/revisions";

interface RevisionHistoryProps {
  workspace: Workspace;
  onSelect: (revisionId: string) => void;
}

function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function RevisionHistory({ workspace, onSelect }: RevisionHistoryProps) {
  if (workspace.revisions.length === 0) return null;
  return (
    <div className="inspector-section">
      <div className="inspector-label">
        Revisions · {workspace.name} ({workspace.revisions.length})
      </div>
      <div className="rev-list" role="list" aria-label="Revision history">
        {workspace.revisions.map((rev, index) => {
          const active = rev.id === workspace.activeRevisionId;
          return (
            <button
              key={rev.id}
              role="listitem"
              className={`rev-item${active ? " active" : ""}`}
              onClick={() => onSelect(rev.id)}
              title={`${rev.kind} · ${rev.createdAt}${rev.parentId ? ` · parent r${workspace.revisions.findIndex((r) => r.id === rev.parentId) + 1}` : " · root"}`}
              aria-current={active ? "true" : undefined}
            >
              <span className="rev-item-title">
                R{index + 1} · {rev.kind}
                {shortTime(rev.createdAt) ? ` · ${shortTime(rev.createdAt)}` : ""}
              </span>
              <span className="rev-item-prompt">{rev.prompt}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
