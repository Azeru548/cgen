import Image from "next/image";
import { useCallback, useMemo, useState } from "react";
import { AccountChip } from "@/components/AccountChip";
import type { Project, Workspace } from "@/types/revisions";

interface WorkspaceHomeProps {
  project: Project;
  busy: boolean;
  /** Shown under the intro, e.g. when a removal could not be saved. */
  notice?: string | null;
  onOpen: (workspaceId: string) => void;
  onCreate: () => void;
  onDelete: (workspaceId: string) => void;
}

const MONTHS = [
  "JAN",
  "FEB",
  "MAR",
  "APR",
  "MAY",
  "JUN",
  "JUL",
  "AUG",
  "SEP",
  "OCT",
  "NOV",
  "DEC",
];

/** Day/month stamp straight from the ISO string. Going through `Date` would
 * make the server and the browser disagree across time zones on the same
 * revision.
 */
function stamp(iso: string): string {
  const month = MONTHS[Number(iso.slice(5, 7)) - 1] ?? "";
  return `${iso.slice(8, 10)} ${month}`.trim();
}

function lastStamp(workspace: Workspace): string | null {
  const newest = workspace.revisions.reduce<string | null>(
    (latest, revision) =>
      latest === null || revision.createdAt > latest ? revision.createdAt : latest,
    null,
  );
  return newest === null ? null : stamp(newest);
}

export function WorkspaceHome({
  project,
  busy,
  notice = null,
  onOpen,
  onCreate,
  onDelete,
}: WorkspaceHomeProps) {
  const workspaces = useMemo(() => project.workspaces, [project]);
  /* Two-step delete: the first press arms the plate, the second removes it. */
  const [confirming, setConfirming] = useState<string | null>(null);

  const totals = useMemo(() => {
    let revisions = 0;
    let newest: string | null = null;
    for (const workspace of workspaces) {
      revisions += workspace.revisions.length;
      for (const revision of workspace.revisions) {
        if (newest === null || revision.createdAt > newest) newest = revision.createdAt;
      }
    }
    return { revisions, newest };
  }, [workspaces]);

  const lastPlate = workspaces.length <= 1;

  const handleDelete = useCallback(
    (workspaceId: string) => {
      if (confirming === workspaceId) {
        setConfirming(null);
        onDelete(workspaceId);
        return;
      }
      setConfirming(workspaceId);
    },
    [confirming, onDelete],
  );

  return (
    <div className="home" data-testid="workspace-home">
      <header className="home-topbar">
        <div className="brand brand-mark">
          <Image
            src="/logo-wordmark-light.png"
            alt="cgen"
            width={423}
            height={107}
            className="brand-logo"
            priority
          />
        </div>

        <span className="topbar-spacer" />

        <AccountChip />

        <button
          type="button"
          className="home-new"
          onClick={onCreate}
          disabled={busy}
          data-testid="create-workspace"
        >
          New workspace <span aria-hidden="true">→</span>
        </button>
      </header>

      <main className="home-main">
        <section className="home-hero">
          <p className="home-kicker mono">
            <span className="home-kicker-mark" aria-hidden="true" />
            Bench · Workspace index
          </p>
          <h1 className="home-title">
            Open a workspace<span className="home-dot">.</span>
          </h1>
          <p className="home-sub">
            Every plate holds one part lineage: prompts, revisions and the solids they
            produced. Pick one to keep machining, or stamp a fresh plate and start from a
            sentence.
          </p>

          <dl className="home-facts">
            <div>
              <dt className="mono">Workspaces</dt>
              <dd>{String(workspaces.length).padStart(2, "0")}</dd>
            </div>
            <div>
              <dt className="mono">Revisions</dt>
              <dd>{String(totals.revisions).padStart(2, "0")}</dd>
            </div>
            <div>
              <dt className="mono">Last stamp</dt>
              <dd>{totals.newest === null ? "—" : stamp(totals.newest)}</dd>
            </div>
          </dl>

          {notice === null ? null : (
            <p className="home-notice" role="status">
              {notice}
            </p>
          )}
        </section>

        <ul className="tray-grid" aria-label="Workspaces">
          {workspaces.map((ws, index) => {
            const active = ws.id === project.activeWorkspaceId;
            const stamped = lastStamp(ws);
            const armed = confirming === ws.id;
            return (
              <li key={ws.id} className="tray-slot">
                <article
                  className={`tray-card${active ? " is-active" : ""}`}
                  style={{ animationDelay: `${Math.min(index * 70, 420)}ms` }}
                >
                  <button
                    type="button"
                    className="tray-open"
                    onClick={() => onOpen(ws.id)}
                    disabled={busy}
                    data-testid={`tray-${ws.id}`}
                    aria-label={`Open ${ws.name}`}
                  >
                    <span className="tray-title">{ws.name}</span>

                    <span className="tray-stats">
                      <span className="tray-stat">
                        <span className="tray-stat-k mono">Last stamp</span>
                        <span className="tray-stat-v">{stamped ?? "—"}</span>
                      </span>
                    </span>

                    <span className="tray-cta">
                      Open workspace <span aria-hidden="true">→</span>
                    </span>
                  </button>

                  <button
                    type="button"
                    className={`tray-delete mono${armed ? " is-armed" : ""}`}
                    onClick={() => handleDelete(ws.id)}
                    onBlur={() => setConfirming((current) => (current === ws.id ? null : current))}
                    disabled={busy || lastPlate}
                    title={
                      lastPlate
                        ? "A project keeps at least one workspace"
                        : `Delete ${ws.name} — its revisions go with it`
                    }
                    aria-label={armed ? `Confirm delete ${ws.name}` : `Delete ${ws.name}`}
                    data-testid={`delete-${ws.id}`}
                  >
                    {armed ? "Confirm delete" : "Delete"}
                  </button>
                </article>
              </li>
            );
          })}

          <li className="tray-slot">
            <button
              type="button"
              className="tray-create"
              onClick={onCreate}
              disabled={busy}
              data-testid="create-workspace-plate"
            >
              <span className="tray-create-mark" aria-hidden="true">
                +
              </span>
              <span className="tray-create-k mono">New plate</span>
              <span className="tray-create-title">Create workspace</span>
              <span className="tray-create-cta">Start blank →</span>
            </button>
          </li>
        </ul>
      </main>

      <footer className="home-footer">
        <span>Describe · Preview · Adjust · Download STEP/STL</span>
      </footer>
    </div>
  );
}
