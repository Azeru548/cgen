"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BootScreen, type BootChecks } from "@/components/BootScreen";
import { CadViewport } from "@/components/cad/CadViewport";
import type { PreviewState } from "@/components/cad/StlModel";
import { Inspector } from "@/components/Inspector";
import { ParametricPanel } from "@/components/ParametricPanel";
import { WorkspaceHome } from "@/components/WorkspaceHome";
import {
  checkBackendHealth,
  generatePart,
  humanizeApiError,
  modifyPart,
  resolveFileUrl,
  type ApiError,
} from "@/lib/api";
import { useParametricSession } from "@/lib/useParametricSession";
import {
  addWorkspace,
  appendRevision,
  clearViewer,
  createProject,
  getActiveWorkspace,
  selectRevision,
  switchWorkspace,
  visibleRevision,
} from "@/lib/revisions";
import { computeLiveScale } from "@/lib/parameters";
import type { BackendHealth } from "@/types/api";
import type { Project } from "@/types/revisions";

type PageStatus = "idle" | "generating" | "ready" | "error";
type EngineState = "ready" | "processing" | "error" | "unknown";
type AppView = "home" | "workspace";

const SCHEMA_VERSION = "SCHEMA 3.2";
const MAX_PROMPT_LENGTH = 2000;

function detectWebgl(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(
      canvas.getContext("webgl2") ??
        canvas.getContext("webgl") ??
        canvas.getContext("experimental-webgl"),
    );
  } catch {
    return false;
  }
}

export default function Home() {
  const [view, setView] = useState<AppView>("home");
  const [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState<PageStatus>("idle");
  // Project → Workspace → Revision model: revisions are append-only, so a
  // generate/modify never destroys previous specs. The viewer shows the
  // visible (active, non-cleared) revision of the active workspace.
  const [project, setProject] = useState<Project>(() =>
    createProject("Mechanical Bracket"),
  );
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [booting, setBooting] = useState(true);
  const [bootChecks, setBootChecks] = useState<BootChecks>({
    schema: false,
    renderer: false,
    engine: false,
  });
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    checkBackendHealth().then((info) => {
      if (cancelled) return;
      setHealth(info);
      setBootChecks({
        schema: true,
        renderer: detectWebgl(),
        engine: info !== null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const activeWorkspace = useMemo(() => getActiveWorkspace(project), [project]);
  const visible = useMemo(
    () => visibleRevision(activeWorkspace),
    [activeWorkspace],
  );
  const result = visible?.response ?? null;
  const baseSpec = visible?.response.specification ?? null;

  // M8.1 parametric session: edits are transient UI values; preview is the
  // last successful rebuild (never a revision); committing appends exactly
  // one revision. Everything resets when the visible revision changes.
  const paramSession = useParametricSession(baseSpec);
  const {
    descriptors: paramDescriptors,
    edits: paramEdits,
    editedSpec,
    preview,
    previewCurrent,
    editsActive,
    paramError,
    previewBusy,
    committing,
  } = paramSession;

  // Viewer: committed result by default; a current preview takes over; while
  // stale/invalid the last good preview (or base) stays — never a jump.
  const displayResult =
    !editsActive
      ? result
      : previewCurrent && preview !== null
        ? preview.response
        : (preview?.response ?? result);
  const stlUrl = displayResult ? resolveFileUrl(displayResult.files.stl.download_url) : null;

  // Instant dial feedback: scale the currently displayed mesh toward the
  // edited spec while a rebuild is pending. Cleared when the preview lands
  // (geometry already matches) so the authoritative mesh is unscaled.
  const liveScale = useMemo(() => {
    if (!editsActive || editedSpec === null || displayResult === null) return null;
    return computeLiveScale(displayResult.specification, editedSpec);
  }, [editsActive, editedSpec, displayResult]);

  const sessionKey = visible?.response.request_id ?? `empty:${activeWorkspace.id}`;
  const resetParamSession = paramSession.reset;
  useEffect(() => {
    resetParamSession();
  }, [sessionKey, resetParamSession]);

  const handleGenerate = useCallback(async () => {
    if (status === "generating") return;
    if (prompt.trim().length === 0) {
      setGenerateError("Describe the part first \u2014 the prompt is empty.");
      setStatus("error");
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("generating");
    setGenerateError(null);
    setPreviewError(null);
    try {
      const text = prompt.trim();
      const response = await generatePart(text, controller.signal);
      setProject((p) => appendRevision(p, "generate", text, response));
      setStatus("ready");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setGenerateError(humanizeApiError(err as ApiError));
      setStatus("error");
    }
  }, [prompt, status]);

  const handleModify = useCallback(async () => {
    if (status === "generating" || visible === null) return;
    if (prompt.trim().length === 0) {
      setGenerateError("Describe the modification \u2014 the prompt is empty.");
      setStatus("error");
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("generating");
    setGenerateError(null);
    setPreviewError(null);
    try {
      const text = prompt.trim();
      const response = await modifyPart(
        visible.response.specification as unknown as Record<string, unknown>,
        text,
        controller.signal,
      );
      setProject((p) => appendRevision(p, "modify", text, response));
      setStatus("ready");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setGenerateError(humanizeApiError(err as ApiError));
      setStatus("error");
    }
  }, [prompt, status, visible]);

  const handleParamCommit = useCallback(async () => {
    if (status === "generating") return;
    const done = await paramSession.commit();
    if (done !== null) {
      setProject((p) => appendRevision(p, "adjust", done.summary, done.response));
    }
  }, [paramSession, status]);

  const handleNewWorkspace = useCallback(() => {
    setProject((p) => addWorkspace(p, `Workspace ${p.workspaces.length + 1}`));
    setPrompt("");
    setGenerateError(null);
    setPreviewError(null);
    setStatus("idle");
    setView("workspace");
  }, []);

  const handleOpenWorkspace = useCallback((workspaceId: string) => {
    setProject((p) => {
      const next = switchWorkspace(p, workspaceId);
      const target = getActiveWorkspace(next);
      setGenerateError(null);
      setPreviewError(null);
      setStatus(visibleRevision(target) === null ? "idle" : "ready");
      return next;
    });
    setView("workspace");
  }, []);

  const handleGoHome = useCallback(() => {
    abortRef.current?.abort();
    setView("home");
    setGenerateError(null);
    setPreviewError(null);
  }, []);

  const handleClearViewer = useCallback(() => {
    abortRef.current?.abort();
    setProject((p) => clearViewer(p));
    setGenerateError(null);
    setPreviewError(null);
    setStatus("idle");
  }, []);

  const handleSelectWorkspace = useCallback(
    (workspaceId: string) => {
      setProject((p) => {
        const next = switchWorkspace(p, workspaceId);
        const target = getActiveWorkspace(next);
        setGenerateError(null);
        setPreviewError(null);
        setStatus(visibleRevision(target) === null ? "idle" : "ready");
        return next;
      });
    },
    [],
  );

  const handleSelectRevision = useCallback((revisionId: string) => {
    setProject((p) => selectRevision(p, revisionId));
    setGenerateError(null);
    setPreviewError(null);
    setStatus("ready");
  }, []);

  const handlePreviewStatus = useCallback(
    (state: PreviewState, message?: string) => {
      if (state === "error") {
        setPreviewError(
          message ?? "The preview mesh could not be loaded. Downloads still work.",
        );
      } else if (state === "loading") {
        setPreviewError(null);
      }
    },
    [],
  );

  const handleBootDone = useCallback(() => setBooting(false), []);

  const handlePromptKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        if (visible !== null) {
          handleModify();
        } else {
          handleGenerate();
        }
      }
    },
    [handleGenerate, handleModify, visible],
  );

  const busy = status === "generating";

  const engineState: EngineState = busy
    ? "processing"
    : status === "error"
      ? "error"
      : health === null
        ? "unknown"
        : health.cadquery_available
          ? "ready"
          : "error";

  const engineLabel = useMemo(() => {
    switch (engineState) {
      case "ready":
        return "ENGINE READY";
      case "processing":
        return "ENGINE PROCESSING";
      case "error":
        return "ENGINE ERROR";
      default:
        return "ENGINE STANDBY";
    }
  }, [engineState]);

  const engineTitle = health
    ? `Backend ${health.status} \u00b7 CadQuery ${health.cadquery_version ?? "unknown"}`
    : "Backend status unknown";

  const engineReady = health !== null && health.cadquery_available;

  if (view === "home") {
    return (
      <>
        {booting ? (
          <BootScreen checks={bootChecks} onDone={handleBootDone} />
        ) : null}
        <WorkspaceHome
          project={project}
          busy={busy}
          engineReady={engineReady}
          onOpen={handleOpenWorkspace}
          onCreate={handleNewWorkspace}
        />
      </>
    );
  }

  return (
    <div className="workspace">
      {booting ? (
        <BootScreen checks={bootChecks} onDone={handleBootDone} />
      ) : null}

      <header className="topbar">
        <button
          type="button"
          className="brand"
          onClick={handleGoHome}
          title="Back to workspaces"
          aria-label="Back to workspace shelf"
        >
          <Image
            src="/logo-removebg.png"
            alt=""
            width={32}
            height={32}
            className="brand-logo"
            priority
          />
          <span className="brand-text">
            <strong>cgen</strong>
            <small>← Workspaces</small>
          </span>
        </button>
        <div className="topbar-actions">
          <button
            type="button"
            className="session-action"
            onClick={handleGoHome}
            disabled={busy}
          >
            All workspaces
          </button>
          <div
            className={`engine-pill ${engineState}`}
            title={engineTitle}
            role="status"
          >
            <span className="engine-dot" aria-hidden="true" />
            {engineLabel}
          </div>
        </div>
      </header>

      <div className="session-bar" role="toolbar" aria-label="Project workspaces">
        <span className="session-project" title="Active project">
          {project.name}
        </span>
        <div className="session-tabs" role="tablist" aria-label="Workspaces">
          {project.workspaces.map((w) => (
            <button
              key={w.id}
              role="tab"
              aria-selected={w.id === activeWorkspace.id}
              className={`session-tab${w.id === activeWorkspace.id ? " active" : ""}`}
              onClick={() => handleSelectWorkspace(w.id)}
              disabled={busy}
              title={`${w.name} · ${w.revisions.length} revision${w.revisions.length === 1 ? "" : "s"}`}
            >
              {w.name} ({w.revisions.length})
            </button>
          ))}
        </div>
        <span className="session-spacer" />
        <button
          className="session-action"
          onClick={handleClearViewer}
          disabled={busy || visible === null}
          title="Remove the displayed result; project, workspace and revisions are kept"
        >
          Clear viewer
        </button>
        <button
          className="session-action"
          onClick={handleNewWorkspace}
          disabled={busy}
          title="Start a fresh empty workspace without affecting existing ones"
        >
          + New workspace
        </button>
        <button
          className="session-action"
          onClick={handleGoHome}
          disabled={busy}
          title="Return to the workspace shelf"
        >
          ← Shelf
        </button>
      </div>

      <main className="layout">
        <div className="workspace-main">
          <CadViewport
            stlUrl={stlUrl}
            busy={busy}
            previewError={previewError}
            onPreviewStatus={handlePreviewStatus}
            onSelectExample={setPrompt}
            schemaVersion={SCHEMA_VERSION}
            liveScale={liveScale}
          />

          <div className="prompt-bar">
            {status === "error" && generateError ? (
              <div className="error-box">
                <div className="error-title">
                  {visible !== null ? "Modification failed" : "Generation failed"}
                </div>
                <div className="error-text">{generateError}</div>
              </div>
            ) : null}
            <div className="prompt-bar-inner">
              <textarea
                ref={textareaRef}
                className="prompt-input"
                placeholder={
                  visible !== null
                    ? "Describe how to modify this part..."
                    : "Describe the part you want to build..."
                }
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={handlePromptKeyDown}
                disabled={busy}
                rows={2}
                maxLength={MAX_PROMPT_LENGTH}
                aria-label={visible !== null ? "Modification instruction" : "Part description"}
              />
              <button
                className="generate-button"
                onClick={visible !== null ? handleModify : handleGenerate}
                disabled={busy || prompt.trim().length === 0}
                aria-label={visible !== null ? "Modify CAD model" : "Generate CAD model"}
              >
                {busy ? "Working..." : visible !== null ? "Modify" : "Generate"}
              </button>
            </div>
            <div className="prompt-footer">
              <span className="char-count">
                {prompt.length} / {MAX_PROMPT_LENGTH}
              </span>
              <span className="char-count">
                Ctrl+Enter to {visible !== null ? "modify" : "generate"}
              </span>
            </div>
          </div>
        </div>

        <aside className="inspector">
          <Inspector
            result={result}
            status={status}
            workspace={activeWorkspace}
            onSelectRevision={handleSelectRevision}
            parametric={
              visible !== null && paramDescriptors.length > 0 ? (
                <ParametricPanel
                  params={paramDescriptors}
                  values={paramEdits}
                  busy={committing || busy}
                  previewing={previewBusy}
                  error={paramError}
                  canCommit={paramSession.canCommit}
                  onPreview={paramSession.previewValue}
                  onCommit={handleParamCommit}
                />
              ) : undefined
            }
          />
        </aside>
      </main>
    </div>
  );
}
