"use client";

/**
 * WorkspaceHome — calibration bench of engraved workspace nameplates
 * (Precision Bench direction). Each workspace is a metal nameplate with a
 * permanent serial and revision stamp; selecting one enters the editor.
 */
import Image from "next/image";
import { useMemo } from "react";
import type { Project, Workspace } from "@/types/revisions";

interface WorkspaceHomeProps {
  project: Project;
  busy: boolean;
  onOpen: (workspaceId: string) => void;
  onCreate: () => void;
}

function serialFor(ws: Workspace, index: number): string {
  const n = (Math.abs(hash(ws.id)) % 900) + 100 + index;
  return `WS-${String(n).padStart(3, "0")}`;
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}

export function WorkspaceHome({
  project,
  busy,
  onOpen,
  onCreate,
}: WorkspaceHomeProps) {
  const workspaces = useMemo(() => project.workspaces, [project]);

  return (
    <div className="home" data-testid="workspace-home">
      <header className="home-topbar">
        <div className="brand brand-mark">
          <Image
            src="/logo-removebg.png"
            alt="cgen"
            width={56}
            height={56}
            className="brand-logo"
            priority
          />
        </div>
      </header>

      <main className="home-main">
        <div className="home-intro">
          <h1 className="home-title">Open a workspace</h1>
          <p className="home-sub">
            Pick a nameplate to continue a model, or stamp a fresh workspace for a new part.
          </p>
        </div>

        <ul className="tray-grid" aria-label="Workspaces">
          {workspaces.map((ws, index) => {
            const active = ws.id === project.activeWorkspaceId;
            const count = ws.revisions.length;
            return (
              <li key={ws.id}>
                <button
                  type="button"
                  className={`tray-card${active ? " is-active" : ""}`}
                  style={{ animationDelay: `${Math.min(index * 70, 420)}ms` }}
                  onClick={() => onOpen(ws.id)}
                  disabled={busy}
                  data-testid={`tray-${ws.id}`}
                >
                  <span className="tray-body">
                    <span className="tray-meta">
                      <span className="tray-serial">{serialFor(ws, index)}</span>
                      {active ? " · last open" : ""}
                    </span>
                    <span className="tray-title">{ws.name}</span>
                    <span className="tray-rev">
                      {count === 0
                        ? "No revisions"
                        : `Rev ${String(count).padStart(2, "0")}`}
                    </span>
                    <span className="tray-cta">Open workspace →</span>
                  </span>
                </button>
              </li>
            );
          })}
          <li>
            <button
              type="button"
              className="tray-card tray-create"
              onClick={onCreate}
              disabled={busy}
              data-testid="create-workspace"
            >
              <span className="tray-create-mark" aria-hidden="true">
                +
              </span>
              <span className="tray-body">
                <span className="tray-meta">New plate</span>
                <span className="tray-title">Create workspace</span>
                <span className="tray-cta">Start blank →</span>
              </span>
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
