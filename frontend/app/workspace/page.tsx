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
import { AccountChip } from "@/components/AccountChip";
import { useFirestore } from "@/components/AuthProvider";
import { useExpiredFileRevival } from "@/hooks/useExpiredFileRevival";
import { track } from "@/lib/telemetry";
import { useProjectSync } from "@/hooks/useProjectSync";
import {
  addAssemblyComponent,
  checkBackendHealth,
  fetchComponentCatalog,
  generatePart,
  humanizeApiError,
  modifyPart,
  remintFiles,
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

interface PlacementDraft {
  name: string;
  position: [number, number, number];
  rotation: [number, number, number];
  instances: Array<{
    position: [number, number, number];
    rotation: [number, number, number];
  }>;
}

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
  const [project, setProject] = useState<Project>(() => ({
    id: "project-initial",
    name: "Mechanical Bracket",
    workspaces: [
      {
        id: "workspace-initial",
        name: "Workspace 1",
        revisions: [],
        activeRevisionId: null,
        viewerCleared: false,
      },
    ],
    activeWorkspaceId: "workspace-initial",
  }));
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
  const [selectedInstance, setSelectedInstance] = useState(-1);
  const [visibilityDraft, setVisibilityDraft] = useState<Record<string, boolean>>(
    {},
  );
  // Placement is a draft until Apply. Keeping it per object is what makes a
  // moved object stay put when the selection changes (or is cleared).
  const [placementDrafts, setPlacementDrafts] = useState<
    Record<string, PlacementDraft>
  >({});
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
  // Gizmo callbacks fire within one animation frame, before React commits the
  // `moveOrigin` state update. The ref is the synchronous read path so the
  // final delta of a drag is never dropped and the object never snaps back.
  const moveOriginRef = useRef(moveOrigin);
  useEffect(() => {
    moveOriginRef.current = moveOrigin;
  }, [moveOrigin]);
  const selectedInstanceRef = useRef(selectedInstance);
  useEffect(() => {
    selectedInstanceRef.current = selectedInstance;
  }, [selectedInstance]);

  const clearDrafts = useCallback(() => {
    setPlacementDrafts({});
    setVisibilityDraft({});
  }, []);

  // M11: mirror the project into Firestore for signed-in users. Guests keep
  // the previous in-memory behaviour, so accounts never gate the CAD work.
  const firestoreDb = useFirestore();
  useProjectSync(project, setProject, firestoreDb, clearDrafts);

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

  // One "workspace opened" per visit: the denominator for launch-day funnels.
  useEffect(() => {
    track("workspace_open");
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
  const baseObjects: SceneObject[] = useMemo(() => {
    if (!displayResult) return [];
    return sceneObjects(displayResult, resolveFileUrl, catalog);
  }, [displayResult, catalog]);

  // Displayed scene = committed spec + every object's uncommitted placement
  // and visibility draft. Drafts are no longer tied to the current selection.
  const objects: SceneObject[] = useMemo(() => {
    return baseObjects.map((object) => {
      const placement = placementDrafts[object.id];
      const vis = visibilityDraft[object.id];
      if (placement === undefined && vis === undefined) return object;
      return {
        ...object,
        ...(placement === undefined
          ? {}
          : {
              name: placement.name,
              transform: {
                position: placement.position,
                rotation: placement.rotation,
              },
              instances: placement.instances,
            }),
        ...(vis === undefined ? {} : { visible: vis }),
      };
    });
  }, [baseObjects, placementDrafts, visibilityDraft]);

  const activeSelectedId =
    selectedId !== null && objects.some((o) => o.id === selectedId)
      ? selectedId
      : null;
  // Dirty checks compare the draft against the committed object; the inspector
  // renders the draft-overlaid one.
  const selectedBase = useMemo(
    () => baseObjects.find((o) => o.id === activeSelectedId) ?? null,
    [baseObjects, activeSelectedId],
  );
  const selectedObject = useMemo(
    () => objects.find((o) => o.id === activeSelectedId) ?? null,
    [objects, activeSelectedId],
  );

  const instancesDirty = useMemo(() => {
    if (selectedBase === null) return false;
    if (draftInstances.length === 0 && selectedBase.instances.length === 0) {
      return false;
    }
    return JSON.stringify(draftInstances) !== JSON.stringify(selectedBase.instances);
  }, [selectedBase, draftInstances]);

  const placementDirty = useMemo(() => {
    if (selectedBase === null) return false;
    const visChanged = Object.prototype.hasOwnProperty.call(
      visibilityDraft,
      selectedBase.id,
    );
    return (
      draftName !== selectedBase.name ||
      draftPosition[0] !== selectedBase.transform.position[0] ||
      draftPosition[1] !== selectedBase.transform.position[1] ||
      draftPosition[2] !== selectedBase.transform.position[2] ||
      draftRotation[0] !== selectedBase.transform.rotation[0] ||
      draftRotation[1] !== selectedBase.transform.rotation[1] ||
      draftRotation[2] !== selectedBase.transform.rotation[2] ||
      instancesDirty ||
      visChanged
    );
  }, [
    selectedBase,
    draftName,
    draftPosition,
    draftRotation,
    instancesDirty,
    visibilityDraft,
  ]);

  const paramsDirty = useMemo(() => {
    if (selectedBase === null) return false;
    return JSON.stringify(draftParams) !== JSON.stringify(selectedBase.parameters);
  }, [selectedBase, draftParams]);

  /** Keep the scene-level draft in sync with an edit to the selected object. */
  const rememberPlacement = useCallback(
    (id: string, patch: Partial<PlacementDraft>) => {
      setPlacementDrafts((prev) => {
        const shown = objects.find((object) => object.id === id);
        if (shown === undefined) return prev;
        const current: PlacementDraft = prev[id] ?? {
          name: shown.name,
          position: shown.transform.position,
          rotation: shown.transform.rotation,
          instances: shown.instances,
        };
        return { ...prev, [id]: { ...current, ...patch } };
      });
    },
    [objects],
  );

  const forgetDraft = useCallback((id: string) => {
    setPlacementDrafts((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setVisibilityDraft((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const handleMoveStart = useCallback(() => {
    if (selectedObject === null) return;
    setMoving(true);
    const origin = {
      position: [...draftPosition] as [number, number, number],
      instances: draftInstances.map((inst) => ({
        position: [...inst.position] as [number, number, number],
        rotation: [...inst.rotation] as [number, number, number],
      })),
    };
    moveOriginRef.current = origin;
    setMoveOrigin(origin);
  }, [selectedObject, draftPosition, draftInstances]);

  const handleMoveDelta = useCallback(
    (delta: [number, number, number]) => {
      const origin = moveOriginRef.current;
      if (origin === null) return;
      const active = selectedInstanceRef.current;
      const activeId = activeSelectedId;
      // A specific instance of a repeated component moves alone; otherwise the
      // whole component (its transform plus every instance) moves as one.
      if (active >= 0) {
        const index = Math.min(active, origin.instances.length - 1);
        if (index < 0) return;
        const nextInstances = origin.instances.map((inst, i) =>
          i === index
            ? {
                position: [
                  inst.position[0] + delta[0],
                  inst.position[1] + delta[1],
                  inst.position[2] + delta[2],
                ] as [number, number, number],
                rotation: inst.rotation,
              }
            : inst,
        );
        setDraftInstances(nextInstances);
        if (activeId !== null) {
          rememberPlacement(activeId, { instances: nextInstances });
        }
        return;
      }
      const nextPosition: [number, number, number] = [
        origin.position[0] + delta[0],
        origin.position[1] + delta[1],
        origin.position[2] + delta[2],
      ];
      setDraftPosition(nextPosition);
      const nextInstances =
        origin.instances.length > 0
          ? origin.instances.map((inst) => ({
              position: [
                inst.position[0] + delta[0],
                inst.position[1] + delta[1],
                inst.position[2] + delta[2],
              ] as [number, number, number],
              rotation: inst.rotation,
            }))
          : [];
      if (nextInstances.length > 0) setDraftInstances(nextInstances);
      if (activeId !== null) {
        rememberPlacement(activeId, {
          position: nextPosition,
          ...(nextInstances.length > 0 ? { instances: nextInstances } : {}),
        });
      }
    },
    [activeSelectedId, rememberPlacement],
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
    (id: string | null, instanceIndex = -1) => {
      setSelectedId(id);
      setSelectedInstance(id === null ? -1 : instanceIndex);
      if (id === null || id === selectedId) return;
      const object = objects.find((item) => item.id === id);
      if (object) hydrateDrafts(object);
    },
    [objects, hydrateDrafts, selectedId],
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
    track("generate_started");
    try {
      const text = prompt.trim();
      const response = await generatePart(text, controller.signal);
      setProject((p) => appendRevision(p, "generate", text, response));
      setStatus("ready");
      clearDrafts();
      track("generate_completed");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      track("generate_failed");
      setGenerateError(humanizeApiError(err as ApiError));
      setStatus("error");
    }
  }, [prompt, status, clearDrafts]);

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
    track("modify_started");
    try {
      const text = prompt.trim();
      const response = await modifyPart(
        visible.response.specification as unknown as Record<string, unknown>,
        text,
        controller.signal,
      );
      setProject((p) => appendRevision(p, "modify", text, response));
      setStatus("ready");
      clearDrafts();
      track("modify_completed");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      track("modify_failed");
      setGenerateError(humanizeApiError(err as ApiError));
      setStatus("error");
    }
  }, [prompt, status, visible, clearDrafts]);

  const handleParamCommit = useCallback(async () => {
    if (status === "generating") return;
    const done = await paramSession.commit();
    if (done !== null) {
      setProject((p) => appendRevision(p, "adjust", done.summary, done.response));
    }
  }, [paramSession, status]);

  // One-click file revival: an old revision's spec is re-exported as-is for
  // fresh download links. No AI, no edits — the new revision keeps the same
  // spec with new file URLs, so history stays append-only and honest.
  const handleRemint = useCallback(async () => {
    if (status === "generating" || visible === null) return;
    const spec = visible.response.specification as unknown as Record<
      string,
      unknown
    >;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("generating");
    setGenerateError(null);
    setPreviewError(null);
    try {
      const response = await remintFiles(spec, controller.signal);
      setProject((p) => appendRevision(p, "remint", "Re-mint files", response));
      setStatus("ready");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setGenerateError(humanizeApiError(err as ApiError));
      setStatus("error");
    }
  }, [status, visible]);

  // Expired-file revival: a saved revision can reference files whose delivery
  // is gone (backend restart, another deployment), so opening it 404s. The
  // spec is authoritative, so re-mint fresh files once per workspace instead
  // of leaving the viewer dead on the overlay.
  useExpiredFileRevival(
    previewError,
    visible !== null && status !== "generating",
    activeWorkspace.id,
    handleRemint,
  );

  const specRecord = useCallback((): Record<string, unknown> | null => {
    if (visible === null) return null;
    return visible.response.specification as unknown as Record<string, unknown>;
  }, [visible]);

  const commitAssembly = useCallback(
    async (label: string, work: () => Promise<GenerateResponse>): Promise<boolean> => {
      if (status === "generating") return false;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setStatus("generating");
      setGenerateError(null);
      try {
        const response = await work();
        setProject((p) => appendRevision(p, "assemble", label, response));
        setStatus("ready");
        return true;
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return false;
        setGenerateError(humanizeApiError(err as ApiError));
        setStatus("error");
        return false;
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

  // Inspector XYZ targets the selected instance when one is active, so the
  // fields and the gizmo always manipulate the same thing.
  const editPosition = draftInstances[selectedInstance]?.position;
  const shownPosition: [number, number, number] =
    selectedInstance >= 0 && editPosition ? editPosition : draftPosition;

  const handleEditPosition = useCallback(
    (axis: 0 | 1 | 2, value: number) => {
      const active = selectedInstanceRef.current;
      const activeId = activeSelectedId;
      if (active >= 0) {
        const nextInstances = draftInstances.map((inst, i) =>
          i === active
            ? {
                position: [
                  inst.position[0],
                  inst.position[1],
                  inst.position[2],
                ].map((v, ax) => (ax === axis ? value : v)) as [
                  number,
                  number,
                  number,
                ],
                rotation: inst.rotation,
              }
            : inst,
        );
        setDraftInstances(nextInstances);
        if (activeId !== null) {
          rememberPlacement(activeId, { instances: nextInstances });
        }
        return;
      }
      const next: [number, number, number] = [...draftPosition];
      next[axis] = value;
      setDraftPosition(next);
      if (activeId !== null) rememberPlacement(activeId, { position: next });
    },
    [activeSelectedId, draftInstances, draftPosition, rememberPlacement],
  );

  const handleEditRotation = useCallback(
    (axis: 0 | 1 | 2, value: number) => {
      const next: [number, number, number] = [...draftRotation];
      next[axis] = value;
      setDraftRotation(next);
      if (activeSelectedId !== null) {
        rememberPlacement(activeSelectedId, { rotation: next });
      }
    },
    [activeSelectedId, draftRotation, rememberPlacement],
  );

  const handleNameChange = useCallback(
    (value: string) => {
      setDraftName(value);
      if (activeSelectedId !== null) {
        rememberPlacement(activeSelectedId, { name: value });
      }
    },
    [activeSelectedId, rememberPlacement],
  );

  const handleApplyPlacement = useCallback(() => {
    const spec = specRecord();
    if (spec === null || activeSelectedId === null) return;
    const id = activeSelectedId;
    const vis = Object.prototype.hasOwnProperty.call(visibilityDraft, id)
      ? visibilityDraft[id]
      : selectedObject?.visible;
    void commitAssembly(`Place ${id}`, () =>
      updateAssemblyComponent(
        spec,
        id,
        {
          name: draftName,
          transform: { position: draftPosition, rotation: draftRotation },
          visible: vis,
          ...(draftInstances.length > 0 ? { instances: draftInstances } : {}),
          // Apply is one explicit commit: include the parameter draft too.
          ...(paramsDirty ? { parameters: draftParams } : {}),
        },
        abortRef.current?.signal,
      ),
    ).then((ok) => {
      if (ok) forgetDraft(id);
    });
  }, [
    specRecord,
    activeSelectedId,
    selectedObject,
    draftName,
    draftPosition,
    draftRotation,
    draftInstances,
    paramsDirty,
    draftParams,
    visibilityDraft,
    commitAssembly,
    forgetDraft,
  ]);

  const handleApplyParams = useCallback(() => {
    const spec = specRecord();
    if (spec === null || activeSelectedId === null) return;
    const id = activeSelectedId;
    const vis = Object.prototype.hasOwnProperty.call(visibilityDraft, id)
      ? visibilityDraft[id]
      : selectedObject?.visible;
    void commitAssembly(`Edit ${id}`, () =>
      updateAssemblyComponent(
        spec,
        id,
        {
          parameters: draftParams,
          // Commit the visible placement too, so applying parameters cannot
          // silently discard an unsaved move.
          name: draftName,
          transform: { position: draftPosition, rotation: draftRotation },
          visible: vis,
          ...(draftInstances.length > 0 ? { instances: draftInstances } : {}),
        },
        abortRef.current?.signal,
      ),
    ).then((ok) => {
      if (ok) forgetDraft(id);
    });
  }, [
    specRecord,
    activeSelectedId,
    selectedObject,
    draftName,
    draftPosition,
    draftRotation,
    draftInstances,
    draftParams,
    visibilityDraft,
    commitAssembly,
    forgetDraft,
  ]);

  const handleNewWorkspace = useCallback(() => {
    setProject((p) => addWorkspace(p, `Workspace ${p.workspaces.length + 1}`));
    setPrompt("");
    setGenerateError(null);
    setPreviewError(null);
    setStatus("idle");
    clearDrafts();
    setView("workspace");
  }, [clearDrafts]);

  const handleOpenWorkspace = useCallback(
    (workspaceId: string) => {
      // Compute outside the state updater: updaters must stay pure, and React
      // may run them twice in development.
      const next = switchWorkspace(project, workspaceId);
      const target = getActiveWorkspace(next);
      setProject(next);
      setGenerateError(null);
      setPreviewError(null);
      setStatus(visibleRevision(target) === null ? "idle" : "ready");
      clearDrafts();
      setView("workspace");
    },
    [project, clearDrafts],
  );

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
    clearDrafts();
  }, [clearDrafts]);

  const handleSelectRevision = useCallback(
    (revisionId: string) => {
      setProject((p) => selectRevision(p, revisionId));
      setGenerateError(null);
      setPreviewError(null);
      setStatus("ready");
      clearDrafts();
      track("revision_selected");
    },
    [clearDrafts],
  );

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
    <div className="workspace" data-moving={moving ? "" : undefined}>
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

        <span className="topbar-spacer" />

        <AccountChip />

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
        <aside className="library-rail" aria-label="Model library">
          <ComponentBrowser
            catalog={catalog}
            busy={busy}
            onAdd={handleAddComponent}
          />
        </aside>
        <div className="workspace-main">
          <CadViewport
            objects={objects.map((object) => {
              const isSel = object.id === activeSelectedId;
              // While the gizmo drags, the attached group holds the live
              // offset. Freeze the mesh at the drag origin for that frame; the
              // final pose is already in the object's draft.
              const frozen = isSel && moving ? moveOrigin : null;
              return {
                id: object.id,
                url: object.stlUrl ?? "",
                position:
                  frozen === null ? object.transform.position : frozen.position,
                rotation:
                  frozen === null ? object.transform.rotation : draftRotation,
                visible: object.visible && Boolean(object.stlUrl),
                selected: isSel,
                instances: frozen === null ? object.instances : frozen.instances,
                activeInstanceIndex: isSel ? selectedInstance : -1,
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
            onRemint={handleRemint}
            remintBusy={busy}
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
                  draftPosition={shownPosition}
                  draftRotation={draftRotation}
                  draftParams={draftParams}
                  placementDirty={placementDirty}
                  paramsDirty={paramsDirty}
                  busy={busy}
                  onName={handleNameChange}
                  onPosition={handleEditPosition}
                  onRotation={handleEditRotation}
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
