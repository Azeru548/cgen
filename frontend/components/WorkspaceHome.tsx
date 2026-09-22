"use client";

/**
 * WorkspaceHome — landing shelf of project trays (Open Kit direction).
 * Each workspace is a rounded tray card with a soft blurred color field
 * and title; selecting one enters the editor. Create starts a new tray.
 */
import Image from "next/image";
import { useMemo } from "react";
import type { Project, Workspace } from "@/types/revisions";

interface WorkspaceHomeProps {
  project: Project;
  busy: boolean;
  engineReady: boolean;
  onOpen: (workspaceId: string) => void;
  onCreate: () => void;
}

function hueFrom(id: string, name: string): number {
  const s = `${id}:${name}`;
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 360;
}

function coverStyle(ws: Workspace): React.CSSProperties {
  const h = hueFrom(ws.id, ws.name);
  const h2 = (h + 48) % 360;
  const h3 = (h + 12) % 360;
  return {
    ["--tray-h" as string]: String(h),
    background: `linear-gradient(145deg, hsl(${h} 68% 58%), hsl(${h2} 72% 42%) 55%, hsl(${h3} 55% 30%))`,
  };
}

export function WorkspaceHome({
  project,
  busy,
  engineReady,
  onOpen,
  onCreate,
}: WorkspaceHomeProps) {
  const workspaces = useMemo(() => project.workspaces, [project]);

  return (
    <div className="home" data-testid="workspace-home">
      <header className="home-topbar">
        <div className="brand">
          <Image
            src="/logo-removebg.png"
            alt="cgen logo"
            width={36}
            height={36}
            className="brand-logo"
            priority
          />
          <span className="brand-text">
            <strong>cgen</strong>
            <small>AI CAD generator</small>
          </span>
        </div>
        <div
          className={`engine-pill ${engineReady ? "ready" : "unknown"}`}
          role="status"
        >
          <span className="engine-dot" aria-hidden="true" />
          {engineReady ? "ENGINE READY" : "ENGINE STANDBY"}
        </div>
      </header>

      <main className="home-main">
        <div className="home-intro">
          <p className="home-eyebrow">{project.name}</p>
          <h1 className="home-title">Open a workspace</h1>
          <p className="home-sub">
            Pick a tray to continue a model, or start a fresh workspace for a new part.
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
                  style={{
                    ...coverStyle(ws),
                    animationDelay: `${Math.min(index * 70, 420)}ms`,
                  }}
                  onClick={() => onOpen(ws.id)}
                  disabled={busy}
                  data-testid={`tray-${ws.id}`}
                >
                  <span className="tray-blur" aria-hidden="true" />
                  <span className="tray-scrim" aria-hidden="true" />
                  <span className="tray-body">
                    <span className="tray-meta">
                      {count === 0
                        ? "Empty tray"
                        : `${count} revision${count === 1 ? "" : "s"}`}
                      {active ? " · last open" : ""}
                    </span>
                    <span className="tray-title">{ws.name}</span>
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
                <span className="tray-meta">New</span>
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
