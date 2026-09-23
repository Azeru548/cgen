"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BootScreen, type BootChecks } from "@/components/BootScreen";
import { CadViewport } from "@/components/cad/CadViewport";
import type { PreviewState } from "@/components/cad/StlModel";
import { AssemblyTree } from "@/components/AssemblyTree";
import { ComponentBrowser } from "@/components/ComponentBrowser";
import { Inspector } from "@/components/Inspector";
import { ObjectInspector } from "@/components/ObjectInspector";
import { ParametricPanel } from "@/components/ParametricPanel";
import { WorkspaceHome } from "@/components/WorkspaceHome";
import {
  addAssemblyComponent,
  checkBackendHealth,
  fetchComponentCatalog,
  generatePart,
  humanizeApiError,
  modifyPart,
  removeAssemblyComponent,
  resolveFileUrl,
  updateAssemblyComponent,
  type ApiError,
} from "@/lib/api";
import {
  isPartSpec,
  sceneObjects,
  type SceneObject,
} from "@/lib/assembly";
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
import type {
  CatalogComponent,
  GenerateResponse,
  ParamValue,
} from "@/types/api";
import type { Project } from "@/types/revisions";

type PageStatus = "idle" | "generating" | "ready" | "error";
type AppView = "home" | "workspace";

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
  const [booting, setBooting] = useState(true);
  const [bootChecks, setBootChecks] = useState<BootChecks>({
    schema: false,
    renderer: false,
    engine: false,
  });
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [catalog, setCatalog] = useState<CatalogComponent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [visibilityDraft, setVisibilityDraft] = useState<Record<string, boolean>>(
    {},
  );
  const [draftName, setDraftName] = useState("");
  const [draftPosition, setDraftPosition] = useState<[number, number, number]>([
    0, 0, 0,
  ]);
  const [draftRotation, setDraftRotation] = useState<[number, number, number]>([
    0, 0, 0,
  ]);
  const [draftParams, setDraftParams] = useState<Record<string, ParamValue>>({});
  const [draftInstances, setDraftInstances] = useState<
    Array<{ position: [number, number, number]; rotation: [number, number, number] }>
  >([]);
  const [moving, setMoving] = useState(false);
  const [moveOrigin, setMoveOrigin] = useState<{
    position: [number, number, number];
    instances: Array<{
      position: [number, number, number];
      rotation: [number, number, number];
    }>;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchComponentCatalog()
      .then((data) => {
        if (!cancelled) setCatalog(data.components);
      })
      .catch(() => {
        if (!cancelled) setCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    checkBackendHealth().then((info) => {
      if (cancelled) return;
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
  const objects: SceneObject[] = useMemo(() => {
    if (!displayResult) return [];
    const base = sceneObjects(displayResult, resolveFileUrl, catalog);
    return base.map((object) => {
      const vis = visibilityDraft[object.id];
      if (vis === undefined) return object;
      return { ...object, visible: vis };
    });
  }, [displayResult, catalog, visibilityDraft]);

  const activeSelectedId =
    selectedId !== null && objects.some((o) => o.id === selectedId)
      ? selectedId
      : null;
  const selectedObject = useMemo(
    () => objects.find((o) => o.id === activeSelectedId) ?? null,
    [objects, activeSelectedId],
  );

  const instancesDirty = useMemo(() => {
    if (selectedObject === null) return false;
    if (draftInstances.length === 0 && selectedObject.instances.length === 0) {
      return false;
    }
    return JSON.stringify(draftInstances) !== JSON.stringify(selectedObject.instances);
  }, [selectedObject, draftInstances]);

  const placementDirty = useMemo(() => {
    if (selectedObject === null) return false;
    const visChanged = Object.prototype.hasOwnProperty.call(
      visibilityDraft,
      selectedObject.id,
    );
    return (
      draftName !== selectedObject.name ||
      draftPosition[0] !== selectedObject.transform.position[0] ||
      draftPosition[1] !== selectedObject.transform.position[1] ||
      draftPosition[2] !== selectedObject.transform.position[2] ||
      draftRotation[0] !== selectedObject.transform.rotation[0] ||
      draftRotation[1] !== selectedObject.transform.rotation[1] ||
      draftRotation[2] !== selectedObject.transform.rotation[2] ||
      instancesDirty ||
      visChanged
    );
  }, [
    selectedObject,
    draftName,
    draftPosition,
    draftRotation,
    instancesDirty,
    visibilityDraft,
  ]);

  const paramsDirty = useMemo(() => {
    if (selectedObject === null) return false;
    return JSON.stringify(draftParams) !== JSON.stringify(selectedObject.parameters);
  }, [selectedObject, draftParams]);

  const handleMoveStart = useCallback(() => {
    if (selectedObject === null) return;
    setMoving(true);
    setMoveOrigin({
      position: [...draftPosition] as [number, number, number],
      instances: draftInstances.map((inst) => ({
        position: [...inst.position] as [number, number, number],
        rotation: [...inst.rotation] as [number, number, number],
      })),
    });
  }, [selectedObject, draftPosition, draftInstances]);

  const handleMoveDelta = useCallback(
    (delta: [number, number, number]) => {
      if (moveOrigin === null) return;
      setDraftPosition([
        moveOrigin.position[0] + delta[0],
        moveOrigin.position[1] + delta[1],
        moveOrigin.position[2] + delta[2],
      ]);
      if (moveOrigin.instances.length > 0) {
        setDraftInstances(
          moveOrigin.instances.map((inst) => ({
            position: [
              inst.position[0] + delta[0],
              inst.position[1] + delta[1],
              inst.position[2] + delta[2],
            ] as [number, number, number],
            rotation: inst.rotation,
          })),
        );
      }
    },
    [moveOrigin],
  );

  const handleMoveEnd = useCallback(() => {
    setMoving(false);
    setMoveOrigin(null);
  }, []);

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

  const hydrateDrafts = useCallback((object: SceneObject) => {
    setMoving(false);
    setMoveOrigin(null);
    setDraftName(object.name);
    setDraftPosition([
      object.transform.position[0],
      object.transform.position[1],
      object.transform.position[2],
    ]);
    setDraftRotation([
      object.transform.rotation[0],
      object.transform.rotation[1],
      object.transform.rotation[2],
    ]);
    setDraftParams({ ...object.parameters });
    setDraftInstances(
      object.instances.map((inst) => ({
        position: [...inst.position] as [number, number, number],
        rotation: [...inst.rotation] as [number, number, number],
      })),
    );
  }, []);

  const handleSelectObject = useCallback(
    (id: string | null) => {
      setSelectedId(id);
      if (id === null) return;
      const object = objects.find((item) => item.id === id);
      if (object) hydrateDrafts(object);
    },
    [objects, hydrateDrafts],
  );

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

  const specRecord = useCallback((): Record<string, unknown> | null => {
    if (visible === null) return null;
    return visible.response.specification as unknown as Record<string, unknown>;
  }, [visible]);

  const commitAssembly = useCallback(
    async (label: string, work: () => Promise<GenerateResponse>) => {
      if (status === "generating") return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setStatus("generating");
      setGenerateError(null);
      try {
        const response = await work();
        setProject((p) => appendRevision(p, "assemble", label, response));
        setStatus("ready");
        setVisibilityDraft({});
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setGenerateError(humanizeApiError(err as ApiError));
        setStatus("error");
      }
    },
    [status],
  );

  const handleAddComponent = useCallback(
    (type: string, count = 1) => {
      void commitAssembly(`Add ${type}`, () =>
        addAssemblyComponent(specRecord(), type, { count }, abortRef.current?.signal),
      );
    },
    [commitAssembly, specRecord],
  );

  const handleRemoveComponent = useCallback(
    (id: string) => {
      const spec = specRecord();
      if (spec === null) return;
      void commitAssembly(`Remove ${id}`, () =>
        removeAssemblyComponent(spec, id, abortRef.current?.signal),
      );
    },
    [commitAssembly, specRecord],
  );

  const handleToggleVisible = useCallback((id: string) => {
    setVisibilityDraft((prev) => {
      const current = objects.find((o) => o.id === id);
      const shown = Object.prototype.hasOwnProperty.call(prev, id)
        ? prev[id]
        : (current?.visible ?? true);
      return { ...prev, [id]: !shown };
    });
  }, [objects]);

  const handleApplyPlacement = useCallback(() => {
    const spec = specRecord();
    if (spec === null || activeSelectedId === null) return;
    const vis = Object.prototype.hasOwnProperty.call(visibilityDraft, activeSelectedId)
      ? visibilityDraft[activeSelectedId]
      : selectedObject?.visible;
    void commitAssembly(`Place ${activeSelectedId}`, () =>
      updateAssemblyComponent(
        spec,
        activeSelectedId,
        {
          name: draftName,
          transform: { position: draftPosition, rotation: draftRotation },
          visible: vis,
          ...(draftInstances.length > 0 ? { instances: draftInstances } : {}),
        },
        abortRef.current?.signal,
      ),
    );
  }, [
    specRecord,
    activeSelectedId,
    selectedObject,
    draftName,
    draftPosition,
    draftRotation,
    draftInstances,
    visibilityDraft,
    commitAssembly,
  ]);

  const handleApplyParams = useCallback(() => {
    const spec = specRecord();
    if (spec === null || activeSelectedId === null) return;
    void commitAssembly(`Edit ${activeSelectedId}`, () =>
      updateAssemblyComponent(
        spec,
        activeSelectedId,
        { parameters: draftParams },
        abortRef.current?.signal,
      ),
    );
  }, [specRecord, activeSelectedId, draftParams, commitAssembly]);

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

  if (view === "home") {
    return (
      <>
        {booting ? (
          <BootScreen checks={bootChecks} onDone={handleBootDone} />
        ) : null}
        <WorkspaceHome
          project={project}
          busy={busy}
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
          title="Back to workspace shelf"
          aria-label="Back to workspace shelf"
        >
          <Image
            src="/logo-removebg.png"
            alt="cgen"
            width={48}
            height={48}
            className="brand-logo"
            priority
          />
        </button>

        <div className="topbar-library">
          <ComponentBrowser
            catalog={catalog}
            busy={busy}
            onAdd={handleAddComponent}
          />
        </div>

        <span className="topbar-spacer" />

        <button
          className="session-action"
          onClick={handleGoHome}
          disabled={busy}
          title="Back to the workspace shelf"
        >
          Workspace
        </button>
        <button
          className="session-action"
          onClick={handleClearViewer}
          disabled={busy || visible === null}
          title="Remove the displayed result; project, workspace and revisions are kept"
        >
          Clear viewer
        </button>
      </header>

      <main className="layout">
        <div className="workspace-main">
          <CadViewport
            objects={objects.map((object) => {
              const isSel = object.id === activeSelectedId;
              if (!isSel) {
                return {
                  id: object.id,
                  url: object.stlUrl ?? "",
                  position: object.transform.position,
                  rotation: object.transform.rotation,
                  visible: object.visible && Boolean(object.stlUrl),
                  selected: false,
                  instances: object.instances,
                  recenter:
                    displayResult !== null &&
                    isPartSpec(displayResult.specification),
                };
              }
              if (moving && moveOrigin !== null) {
                  return {
                    id: object.id,
                    url: object.stlUrl ?? "",
                    position: moveOrigin.position,
                    rotation: draftRotation,
                    visible: object.visible && Boolean(object.stlUrl),
                    selected: true,
                    instances: moveOrigin.instances,
                    recenter:
                      displayResult !== null &&
                      isPartSpec(displayResult.specification),
                  };
                }
              return {
                id: object.id,
                url: object.stlUrl ?? "",
                position: draftPosition,
                rotation: draftRotation,
                visible: object.visible && Boolean(object.stlUrl),
                selected: true,
                instances: draftInstances,
                recenter:
                  displayResult !== null &&
                  isPartSpec(displayResult.specification),
              };
            })}
            busy={busy}
            previewError={previewError}
            onPreviewStatus={handlePreviewStatus}
            onSelectExample={setPrompt}
            onSelectObject={handleSelectObject}
            liveScale={liveScale}
            canDrag={!busy && activeSelectedId !== null}
            onMoveStart={handleMoveStart}
            onMoveDelta={handleMoveDelta}
            onMoveEnd={handleMoveEnd}
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
                {busy
                  ? visible !== null
                    ? "Modifying…"
                    : "Generating…"
                  : `Ctrl+Enter to ${visible !== null ? "modify" : "generate"}`}
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
            assembly={
              <>
                <AssemblyTree
                  name={
                    displayResult
                      ? displayResult.specification.name
                      : activeWorkspace.name
                  }
                  objects={objects}
                  selectedId={activeSelectedId}
                  onSelect={handleSelectObject}
                  onToggleVisible={handleToggleVisible}
                  onRemove={handleRemoveComponent}
                  busy={busy}
                />
                <ObjectInspector
                  object={selectedObject}
                  catalog={catalog}
                  draftName={draftName}
                  draftPosition={draftPosition}
                  draftRotation={draftRotation}
                  draftParams={draftParams}
                  placementDirty={placementDirty}
                  paramsDirty={paramsDirty}
                  busy={busy}
                  onName={setDraftName}
                  onPosition={(axis, value) =>
                    setDraftPosition((prev) => {
                      const next: [number, number, number] = [...prev];
                      next[axis] = value;
                      return next;
                    })
                  }
                  onRotation={(axis, value) =>
                    setDraftRotation((prev) => {
                      const next: [number, number, number] = [...prev];
                      next[axis] = value;
                      return next;
                    })
                  }
                  onParam={(key, value) =>
                    setDraftParams((prev) => ({ ...prev, [key]: value }))
                  }
                  onApplyPlacement={handleApplyPlacement}
                  onApplyParams={handleApplyParams}
                />
              </>
            }
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
