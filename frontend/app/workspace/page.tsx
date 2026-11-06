"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BootScreen, type BootChecks } from "@/components/BootScreen";
import { CadViewport } from "@/components/cad/CadViewport";
import type { PreviewState } from "@/components/cad/StlModel";
import { AssemblyTree } from "@/components/AssemblyTree";
import { Bom } from "@/components/Bom";
import { ComponentBrowser } from "@/components/ComponentBrowser";
import { Inspector } from "@/components/Inspector";
import { ObjectInspector } from "@/components/ObjectInspector";
import { MotionPanel } from "@/components/MotionPanel";
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
  resolveFileUrl,
  updateAssemblyComponent,
  type ApiError,
} from "@/lib/api";
import {
  applyPlacementToResponse,
  bakeDisplayedScene,
  DEFAULT_MOTION_DURATION,
  duplicateComponent,
  expandSelectionToGroups,
  keyAt,
  groupSelection,
  groupsOf,
  isAssemblySpec,
  isPartSpec,
  placedBounds,
  removeComponentFromResponse,
  sampleTrack,
  sceneObjects,
  setAnimationDuration,
  setSelectionLocked,
  trackFor,
  translateSelection,
  ungroupSelection,
  withTrack,
  withoutKey,
  type ObjectBounds,
  type SceneObject,
} from "@/lib/assembly";
import { rotatePose, type Vec3 } from "@/lib/transforms";
import { useParametricSession } from "@/lib/useParametricSession";
import {
  addWorkspace,
  appendRevision,
  clearViewer,
  getActiveWorkspace,
  removeWorkspace,
  selectRevision,
  switchWorkspace,
  visibleRevision,
} from "@/lib/revisions";
import { deleteWorkspaceRecord } from "@/lib/projectStore";
import { computeLiveScale } from "@/lib/parameters";
import type {
  AssemblyGroup,
  AssemblySpecification,
  CatalogComponent,
  GenerateResponse,
  MotionTrack,
  ParamValue,
} from "@/types/api";
import type { Project } from "@/types/revisions";

type PageStatus = "idle" | "generating" | "ready" | "error";
type AppView = "home" | "workspace";

/** Quantise a drag delta so the part lands on a `step` grid in CAD space. */
function snapVector(
  anchor: [number, number, number],
  delta: [number, number, number],
  step: number,
): [number, number, number] {
  if (step <= 0) return delta;
  return [0, 1, 2].map((axis) => {
    const next = anchor[axis] + delta[axis];
    return Math.round(next / step) * step - anchor[axis];
  }) as [number, number, number];
}

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
  // Multi-selection for grouping and group rotation. `selectedId` stays the
  // primary object (what the object inspector edits); this is the working set.
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
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
  // Parsed mesh envelopes, reported by the viewport. Seating, centring and
  // alignment all need the real box, not the requested dimensions.
  const [objectBounds, setObjectBounds] = useState<Record<string, ObjectBounds>>(
    {},
  );
  const [snapMm, setSnapMm] = useState(0);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
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
  // Sibling origins for grouped objects that travel with the gizmo target.
  const groupMoveOriginsRef = useRef<
    Record<
      string,
      {
        position: [number, number, number];
        instances: Array<{
          position: [number, number, number];
          rotation: [number, number, number];
        }>;
      }
    >
  >({});
  const rotateSnapshotRef = useRef<{
    pivot: Vec3;
    poses: Record<
      string,
      {
        position: Vec3;
        rotation: Vec3;
        instances: Array<{ position: Vec3; rotation: Vec3 }>;
      }
    >;
  } | null>(null);
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
  const { uid } = useProjectSync(project, setProject, firestoreDb, clearDrafts);
  const [homeNotice, setHomeNotice] = useState<string | null>(null);

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
    const spec = displayResult?.specification;
    const companions: typeof groupMoveOriginsRef.current = {};
    if (spec && activeSelectedId !== null) {
      const movingIds = expandSelectionToGroups(spec, [activeSelectedId]);
      for (const id of movingIds) {
        if (id === activeSelectedId) continue;
        const object = objects.find((item) => item.id === id);
        if (object === undefined || object.locked) continue;
        companions[id] = {
          position: [...object.transform.position] as [number, number, number],
          instances: object.instances.map((inst) => ({
            position: [...inst.position] as [number, number, number],
            rotation: [...inst.rotation] as [number, number, number],
          })),
        };
      }
    }
    groupMoveOriginsRef.current = companions;
  }, [
    selectedObject,
    draftPosition,
    draftInstances,
    displayResult,
    activeSelectedId,
    objects,
  ]);

  const handleMoveDelta = useCallback(
    (rawDelta: [number, number, number]) => {
      const origin = moveOriginRef.current;
      if (origin === null) return;
      const active = selectedInstanceRef.current;
      const activeId = activeSelectedId;
      // Snap the dragged target, then apply that same delta to companions so
      // a grouped move stays rigid instead of each part rounding apart.
      const anchor: [number, number, number] =
        active >= 0 && origin.instances[active]
          ? origin.instances[active].position
          : origin.position;
      const delta = snapVector(anchor, rawDelta, snapMm);
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
      for (const [id, companion] of Object.entries(groupMoveOriginsRef.current)) {
        const companionPosition: [number, number, number] = [
          companion.position[0] + delta[0],
          companion.position[1] + delta[1],
          companion.position[2] + delta[2],
        ];
        const companionInstances =
          companion.instances.length > 0
            ? companion.instances.map((inst) => ({
                position: [
                  inst.position[0] + delta[0],
                  inst.position[1] + delta[1],
                  inst.position[2] + delta[2],
                ] as [number, number, number],
                rotation: inst.rotation,
              }))
            : [];
        rememberPlacement(id, {
          position: companionPosition,
          ...(companionInstances.length > 0 ? { instances: companionInstances } : {}),
        });
      }
    },
    [activeSelectedId, rememberPlacement, snapMm],
  );

  const handleMoveEnd = useCallback(() => {
    setMoving(false);
    setMoveOrigin(null);
    groupMoveOriginsRef.current = {};
    rotateSnapshotRef.current = null;
  }, []);

  const handleRotateStart = useCallback(() => {
    const seed =
      selectedIds.length > 0
        ? selectedIds
        : activeSelectedId !== null
          ? [activeSelectedId]
          : [];
    if (seed.length === 0) return;
    const spec = displayResult?.specification;
    const ids = spec ? expandSelectionToGroups(spec, seed) : seed;
    const poses: NonNullable<typeof rotateSnapshotRef.current>["poses"] = {};
    for (const id of ids) {
      const object = objects.find((item) => item.id === id);
      if (object === undefined || object.locked) continue;
      poses[id] = {
        position: [...object.transform.position] as Vec3,
        rotation: [...object.transform.rotation] as Vec3,
        instances: object.instances.map((inst) => ({
          position: [...inst.position] as Vec3,
          rotation: [...inst.rotation] as Vec3,
        })),
      };
    }
    if (Object.keys(poses).length === 0) return;
    const primaryId = activeSelectedId && poses[activeSelectedId]
      ? activeSelectedId
      : Object.keys(poses)[0];
    setMoving(true);
    rotateSnapshotRef.current = {
      pivot: poses[primaryId].position,
      poses,
    };
  }, [selectedIds, activeSelectedId, displayResult, objects]);

  const handleRotateDelta = useCallback(
    (delta: [number, number, number]) => {
      const snap = rotateSnapshotRef.current;
      if (snap === null) return;
      if (delta[0] === 0 && delta[1] === 0 && delta[2] === 0) return;
      for (const [id, pose] of Object.entries(snap.poses)) {
        const next = rotatePose(pose, delta, snap.pivot);
        const nextInstances = pose.instances.map((inst) =>
          rotatePose(inst, delta, snap.pivot),
        );
        rememberPlacement(id, {
          position: next.position,
          rotation: next.rotation,
          ...(nextInstances.length > 0 ? { instances: nextInstances } : {}),
        });
        if (id === activeSelectedId) {
          setDraftPosition(next.position);
          setDraftRotation(next.rotation);
          if (nextInstances.length > 0) setDraftInstances(nextInstances);
        }
      }
    },
    [activeSelectedId, rememberPlacement],
  );

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
    (id: string | null, instanceIndex = -1, additive = false) => {
      if (id === null) {
        setSelectedId(null);
        setSelectedIds([]);
        setSelectedInstance(-1);
        return;
      }
      if (additive) {
        setSelectedIds((prev) => {
          if (prev.includes(id)) {
            const next = prev.filter((item) => item !== id);
            if (selectedId === id) {
              const fallback = next[0] ?? null;
              setSelectedId(fallback);
              setSelectedInstance(-1);
              const object = objects.find((item) => item.id === fallback);
              if (object) hydrateDrafts(object);
            }
            return next;
          }
          if (selectedId === null) {
            setSelectedId(id);
            setSelectedInstance(instanceIndex);
            const object = objects.find((item) => item.id === id);
            if (object) hydrateDrafts(object);
          }
          return [...prev, id];
        });
        return;
      }
      setSelectedId(id);
      setSelectedIds([id]);
      setSelectedInstance(instanceIndex);
      if (id === selectedId) return;
      const object = objects.find((item) => item.id === id);
      if (object) hydrateDrafts(object);
    },
    [objects, hydrateDrafts, selectedId],
  );

  const handleTreeSelect = useCallback(
    (id: string, additive: boolean) => {
      if (!additive) {
        handleSelectObject(id, -1);
        return;
      }
      setSelectedIds((prev) => {
        if (prev.includes(id)) {
          const next = prev.filter((item) => item !== id);
          if (selectedId === id) {
            const fallback = next[0] ?? null;
            setSelectedId(fallback);
            setSelectedInstance(-1);
            const object = objects.find((item) => item.id === fallback);
            if (object) hydrateDrafts(object);
          }
          return next;
        }
        if (selectedId === null) {
          setSelectedId(id);
          setSelectedInstance(-1);
          const object = objects.find((item) => item.id === id);
          if (object) hydrateDrafts(object);
        }
        return [...prev, id];
      });
    },
    [handleSelectObject, selectedId, objects, hydrateDrafts],
  );

  const handleSelectGroup = useCallback(
    (group: AssemblyGroup) => {
      const members = group.component_ids.filter((id) =>
        objects.some((object) => object.id === id),
      );
      if (members.length === 0) return;
      setSelectedIds(members);
      setSelectedId(members[0]);
      setSelectedInstance(-1);
      const object = objects.find((item) => item.id === members[0]);
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
    track("generate_started");
    try {
      const text = prompt.trim();
      const host =
        visible !== null
          ? (visible.response.specification as unknown as Record<string, unknown>)
          : null;
      const response = await generatePart(text, controller.signal, host);
      setProject((p) => appendRevision(p, "generate", text, response));
      setStatus("ready");
      clearDrafts();
      setSelectedId(null);
      setSelectedIds([]);
      setSelectedInstance(-1);
      setPrompt("");
      track("generate_completed");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      track("generate_failed");
      setGenerateError(humanizeApiError(err as ApiError));
      setStatus("error");
    }
  }, [prompt, status, clearDrafts, visible]);

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
      const spec = visible.response.specification;
      const focused =
        activeSelectedId !== null && isAssemblySpec(spec)
          ? `Modify only component '${activeSelectedId}' (${selectedObject?.name ?? activeSelectedId}). Leave every other object unchanged. ${text}`
          : text;
      const response = await modifyPart(
        spec as unknown as Record<string, unknown>,
        focused,
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
  }, [prompt, status, visible, clearDrafts, activeSelectedId, selectedObject]);

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

  const reuseFiles = useCallback(() => {
    if (visible === null) return {};
    const { files, component_files, specification } = visible.response;
    if (component_files) return { component_files, files };
    if (isPartSpec(specification)) {
      return {
        component_files: {
          generated_1: { step: files.step, stl: files.stl },
        },
        files,
      };
    }
    return { files };
  }, [visible]);

  const handleAddComponent = useCallback(
    (type: string, count = 1) => {
      void commitAssembly(
        `Add ${type}`,
        () =>
          addAssemblyComponent(
            specRecord(),
            type,
            { count, ...reuseFiles() },
            abortRef.current?.signal,
          ),
      );
    },
    [commitAssembly, specRecord, reuseFiles],
  );

  const handleRemoveComponent = useCallback(
    (id: string) => {
      if (visible === null) return;
      const next = removeComponentFromResponse(visible.response, id);
      if (next === null) {
        setGenerateError(
          "Cannot remove the last object. Clear the viewer instead.",
        );
        setStatus("error");
        return;
      }
      setProject((p) => appendRevision(p, "assemble", `Remove ${id}`, next));
      setGenerateError(null);
      forgetDraft(id);
      setSelectedIds((prev) => prev.filter((item) => item !== id));
      if (selectedId === id) {
        setSelectedId(null);
        setSelectedInstance(-1);
      }
    },
    [visible, forgetDraft, selectedId],
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

  /** Commit a whole response locally: no rebuild, no new meshes. */
  const commitResponsePatch = useCallback(
    (label: string, next: GenerateResponse) => {
      setProject((p) => appendRevision(p, "assemble", label, next));
      setGenerateError(null);
      clearDrafts();
    },
    [clearDrafts],
  );

  const commitSpecPatch = useCallback(
    (label: string, next: ReturnType<typeof groupSelection>) => {
      if (next === null || visible === null) return;
      // Groups, locks and placement fixes are scene handles, not a boolean
      // merge and not a CAD rebuild. Keep the current files; only the
      // specification changes.
      commitResponsePatch(label, { ...visible.response, specification: next });
    },
    [visible, commitResponsePatch],
  );

  // Scene actions commit a specification, not a rebuild — but they must commit
  // the scene as DISPLAYED, otherwise a drag that has not been applied yet is
  // dropped and the object snaps back to its last committed pose.
  const sceneSpec = useCallback(() => {
    if (visible === null) return null;
    // bakeDisplayedScene promotes a single-part document to a one-object
    // assembly, so scene metadata (groups, placement, motion) works there too.
    const baked = bakeDisplayedScene(visible.response, objects).specification;
    return isAssemblySpec(baked) ? baked : null;
  }, [visible, objects]);

  const handleGroup = useCallback(() => {
    const current = sceneSpec();
    if (current === null) return;
    commitSpecPatch("Group", groupSelection(current, selectedIds, ""));
  }, [sceneSpec, selectedIds, commitSpecPatch]);

  const handleUngroup = useCallback(() => {
    const current = sceneSpec();
    if (current === null) return;
    commitSpecPatch("Ungroup", ungroupSelection(current, selectedIds));
  }, [sceneSpec, selectedIds, commitSpecPatch]);

  const handleLock = useCallback(() => {
    const current = sceneSpec();
    if (current === null) return;
    const selectedObjects = objects.filter((object) => selectedIds.includes(object.id));
    const allLocked =
      selectedObjects.length > 0 && selectedObjects.every((object) => object.locked);
    commitSpecPatch(
      allLocked ? "Unlock" : "Lock",
      setSelectionLocked(current, selectedIds, !allLocked),
    );
  }, [sceneSpec, objects, selectedIds, commitSpecPatch]);



  const handleObjectBounds = useCallback((id: string, next: ObjectBounds) => {
    setObjectBounds((prev) => ({ ...prev, [id]: next }));
  }, []);

  /** Axis-aligned bounds of one placed component, from its parsed mesh. */
  const worldBoundsOf = useCallback(
    (spec: AssemblySpecification, id: string) => {
      const component = spec.components.find((item) => item.id === id);
      const bounds = objectBounds[id];
      if (component === undefined || bounds === undefined) return null;
      return placedBounds(component.transform, bounds);
    },
    [objectBounds],
  );

  // Placement quick actions are pure translations of the committed scene: no
  // regeneration, no new meshes, one local revision each.
  const handleSeatFloor = useCallback(() => {
    if (activeSelectedId === null) return;
    const spec = sceneSpec();
    if (spec === null) return;
    const world = worldBoundsOf(spec, activeSelectedId);
    if (world === null) return;
    const next = translateSelection(spec, [activeSelectedId], [
      0,
      0,
      -world.min[2],
    ]);
    if (next === null) return;
    commitSpecPatch("Seat on floor", next);
  }, [activeSelectedId, sceneSpec, worldBoundsOf, commitSpecPatch]);

  const handleCentre = useCallback(
    (axis: 0 | 1 | 2) => {
      if (activeSelectedId === null) return;
      const spec = sceneSpec();
      if (spec === null) return;
      const world = worldBoundsOf(spec, activeSelectedId);
      if (world === null) return;
      const delta: Vec3 = [0, 0, 0];
      delta[axis] = -((world.min[axis] + world.max[axis]) / 2);
      const next = translateSelection(spec, [activeSelectedId], delta);
      if (next === null) return;
      commitSpecPatch(`Centre ${["X", "Y", "Z"][axis]}`, next);
    },
    [activeSelectedId, sceneSpec, worldBoundsOf, commitSpecPatch],
  );

  const handleAlign = useCallback(
    (axis: 0 | 1 | 2) => {
      if (activeSelectedId === null) return;
      let spec = sceneSpec();
      if (spec === null) return;
      // The active object is the datum: every other ticked part moves to it.
      const reference = worldBoundsOf(spec, activeSelectedId);
      if (reference === null) return;
      const target = (reference.min[axis] + reference.max[axis]) / 2;
      let moved = false;
      for (const id of selectedIds) {
        if (id === activeSelectedId) continue;
        const component = spec.components.find((item) => item.id === id);
        if (component === undefined || component.locked) continue;
        const world = worldBoundsOf(spec, id);
        if (world === null) continue;
        const delta: Vec3 = [0, 0, 0];
        delta[axis] = target - (world.min[axis] + world.max[axis]) / 2;
        const next = translateSelection(spec, [id], delta);
        if (next === null) continue;
        spec = next;
        moved = true;
      }
      if (!moved) return;
      commitSpecPatch(`Align ${["X", "Y", "Z"][axis]}`, spec);
    },
    [activeSelectedId, selectedIds, sceneSpec, worldBoundsOf, commitSpecPatch],
  );

  const handleDuplicate = useCallback(() => {
    if (activeSelectedId === null || visible === null) return;
    const spec = sceneSpec();
    if (spec === null) return;
    const bounds = objectBounds[activeSelectedId];
    // Offset by the part's own width plus a 10 mm gap, so the copy clears the
    // original whether it is a 3 mm screw or a 200 mm plate.
    const offset: Vec3 = bounds ? [bounds.size[0] + 10, 0, 0] : [20, 0, 0];
    const result = duplicateComponent(spec, activeSelectedId, offset);
    if (result === null) return;
    const files = visible.response.component_files ?? {};
    const sourceFiles = files[activeSelectedId];
    commitResponsePatch("Duplicate", {
      ...visible.response,
      specification: result.specification,
      component_files:
        sourceFiles === undefined
          ? visible.response.component_files
          : { ...files, [result.id]: sourceFiles },
    });
    setSelectedId(result.id);
    setSelectedIds([result.id]);
  }, [
    activeSelectedId,
    visible,
    sceneSpec,
    objectBounds,
    commitResponsePatch,
  ]);

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

  // --- Motion (viewer-only keyframes) ---------------------------------------

  const activeTrack = useMemo<MotionTrack | null>(() => {
    const spec = visible?.response.specification;
    if (spec === undefined || activeSelectedId === null) return null;
    return trackFor(spec, activeSelectedId);
  }, [visible, activeSelectedId]);

  const sceneAnimation =
    visible !== null &&
    visible.response.specification.document_type === "3d_assembly"
      ? visible.response.specification.animation ?? null
      : null;
  const motionDuration = sceneAnimation?.duration ?? DEFAULT_MOTION_DURATION;

  const animatedPose = useMemo(
    () => (activeTrack === null ? null : sampleTrack(activeTrack, playhead)),
    [activeTrack, playhead],
  );

  const writeTrack = useCallback(
    (next: MotionTrack | null, label: string) => {
      if (visible === null) return;
      const spec = sceneSpec();
      if (spec === null) return;
      commitSpecPatch(label, withTrack(spec, next));
    },
    [visible, sceneSpec, commitSpecPatch],
  );

  const handleAddKey = useCallback(() => {
    if (activeSelectedId === null) return;
    const track: MotionTrack = activeTrack ?? {
      component_id: activeSelectedId,
      keys: [],
      loop: true,
    };
    const next = keyAt(track, playhead, {
      position: shownPosition,
      rotation: draftRotation,
    });
    writeTrack(next, activeTrack === null ? "Animate" : "Key");
  }, [
    activeSelectedId,
    activeTrack,
    playhead,
    shownPosition,
    draftRotation,
    writeTrack,
  ]);

  const handleRemoveKey = useCallback(
    (index: number) => {
      if (activeTrack === null) return;
      const next = withoutKey(activeTrack, index);
      writeTrack(next.keys.length === 0 ? null : next, "Delete key");
    },
    [activeTrack, writeTrack],
  );

  const handleToggleTrack = useCallback(() => {
    if (activeSelectedId === null) return;
    if (activeTrack !== null) {
      writeTrack(null, "Clear motion");
      setPlaying(false);
      setPlayhead(0);
      return;
    }
    const next = keyAt(
      { component_id: activeSelectedId, keys: [], loop: true },
      0,
      { position: shownPosition, rotation: draftRotation },
    );
    writeTrack(next, "Animate");
  }, [
    activeSelectedId,
    activeTrack,
    shownPosition,
    draftRotation,
    writeTrack,
  ]);

  const handleDuration = useCallback(
    (duration: number) => {
      if (visible === null || !Number.isFinite(duration)) return;
      const spec = sceneSpec();
      if (spec === null) return;
      commitSpecPatch("Motion length", setAnimationDuration(spec, duration));
      setPlayhead((value) => Math.min(value, Math.max(0.2, duration)));
    },
    [visible, sceneSpec, commitSpecPatch],
  );

  const handlePlay = useCallback(() => {
    if (activeTrack === null) return;
    setPlaying((value) => {
      if (!value && playhead >= motionDuration - 0.05) setPlayhead(0);
      return !value;
    });
  }, [activeTrack, playhead, motionDuration]);

  const handleApplyPlacement = useCallback(() => {
    if (visible === null || activeSelectedId === null) return;
    const id = activeSelectedId;
    if (paramsDirty) {
      const spec = specRecord();
      if (spec === null) return;
      const vis = Object.prototype.hasOwnProperty.call(visibilityDraft, id)
        ? visibilityDraft[id]
        : selectedObject?.visible;
      void commitAssembly(
        `Place ${id}`,
        () =>
          updateAssemblyComponent(
            spec,
            id,
            {
              name: draftName,
              transform: { position: draftPosition, rotation: draftRotation },
              visible: vis,
              ...(draftInstances.length > 0 ? { instances: draftInstances } : {}),
              parameters: draftParams,
              ...reuseFiles(),
            },
            abortRef.current?.signal,
          ),
      ).then((ok) => {
        if (ok) forgetDraft(id);
      });
      return;
    }
    const ids = [...new Set([id, ...selectedIds])];
    let next = visible.response;
    for (const componentId of ids) {
      const object = objects.find((item) => item.id === componentId);
      if (object === undefined) continue;
      const patched = applyPlacementToResponse(next, componentId, {
        name: object.name,
        transform: object.transform,
        visible: object.visible,
        ...(object.instances.length > 0 ? { instances: object.instances } : {}),
      });
      if (patched !== null) next = patched;
    }
    setProject((p) => appendRevision(p, "assemble", `Place ${id}`, next));
    setGenerateError(null);
    for (const componentId of ids) forgetDraft(componentId);
  }, [
    visible,
    specRecord,
    activeSelectedId,
    selectedIds,
    objects,
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
    reuseFiles,
  ]);

  const handleApplyParams = useCallback(() => {
    const spec = specRecord();
    if (spec === null || activeSelectedId === null) return;
    const id = activeSelectedId;
    const vis = Object.prototype.hasOwnProperty.call(visibilityDraft, id)
      ? visibilityDraft[id]
      : selectedObject?.visible;
    void commitAssembly(
      `Edit ${id}`,
      () =>
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
            ...reuseFiles(),
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
    reuseFiles,
  ]);

  const handleNewWorkspace = useCallback(() => {
    setProject((p) => addWorkspace(p, `Workspace ${p.workspaces.length + 1}`));
    setHomeNotice(null);
    setPrompt("");
    setGenerateError(null);
    setPreviewError(null);
    setStatus("idle");
    clearDrafts();
    setView("workspace");
  }, [clearDrafts]);

  /**
   * Remove a workspace from the bench. Signed-in users get the plate flagged in
   * Firestore first: if that write fails the plate stays, so the list never
   * disagrees with what a reload will show.
   */
  const handleDeleteWorkspace = useCallback(
    (workspaceId: string) => {
      if (firestoreDb === null || uid === null) {
        setProject((p) => removeWorkspace(p, workspaceId));
        setHomeNotice(null);
        return;
      }
      void deleteWorkspaceRecord(firestoreDb, uid, project.id, workspaceId)
        .then(() => {
          setProject((p) => removeWorkspace(p, workspaceId));
          setHomeNotice(null);
        })
        .catch(() => {
          setHomeNotice("That workspace could not be removed. Nothing was changed.");
        });
    },
    [firestoreDb, uid, project.id],
  );

  const handleOpenWorkspace = useCallback(
    (workspaceId: string) => {
      // Compute outside the state updater: updaters must stay pure, and React
      // may run them twice in development.
      const next = switchWorkspace(project, workspaceId);
      const target = getActiveWorkspace(next);
      setProject(next);
      setHomeNotice(null);
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
        if (activeSelectedId !== null) {
          handleModify();
        } else {
          handleGenerate();
        }
      }
    },
    [handleGenerate, handleModify, activeSelectedId],
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
          notice={homeNotice}
          onOpen={handleOpenWorkspace}
          onCreate={handleNewWorkspace}
          onDelete={handleDeleteWorkspace}
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
            src="/logo-wordmark-light.png"
            alt="cgen"
            width={423}
            height={107}
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
                selected: isSel || selectedIds.includes(object.id),
                gizmo: isSel,
                instances: frozen === null ? object.instances : frozen.instances,
                activeInstanceIndex: isSel ? selectedInstance : -1,
                recenter:
                  displayResult !== null &&
                  isPartSpec(displayResult.specification),
              };
            })}
            busy={busy || committing}
            onBounds={handleObjectBounds}
            snapMm={snapMm}
            onSnapChange={setSnapMm}
            animation={sceneAnimation}
            playing={playing}
            playhead={playhead}
            onPlayhead={setPlayhead}
            readout={
              activeSelectedId !== null && selectedObject !== null
                ? {
                    id: activeSelectedId,
                    name: draftName || selectedObject.name,
                    position: animatedPose?.position ?? shownPosition,
                    rotation: animatedPose?.rotation ?? draftRotation,
                    instanceIndex: selectedInstance,
                  }
                : null
            }
            previewError={previewError}
            onPreviewStatus={handlePreviewStatus}
            onSelectExample={setPrompt}
            onSelectObject={handleSelectObject}
            liveScale={liveScale}
            canDrag={
              !busy &&
              activeSelectedId !== null &&
              selectedObject?.locked !== true &&
              activeTrack === null
            }
            onMoveStart={handleMoveStart}
            onMoveDelta={handleMoveDelta}
            onRotateStart={handleRotateStart}
            onRotateDelta={handleRotateDelta}
            onMoveEnd={handleMoveEnd}
          />

          <div className="prompt-bar">
            {status === "error" && generateError ? (
              <div className="error-box">
                <div className="error-title">
                  {activeSelectedId !== null ? "Modification failed" : "Generation failed"}
                </div>
                <div className="error-text">{generateError}</div>
              </div>
            ) : null}
            <div className="prompt-bar-inner">
              <textarea
                ref={textareaRef}
                className="prompt-input"
                placeholder={
                  activeSelectedId !== null
                    ? "Describe how to modify the selected part..."
                    : "Describe the part you want to build..."
                }
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={handlePromptKeyDown}
                disabled={busy}
                rows={2}
                maxLength={MAX_PROMPT_LENGTH}
                aria-label={
                  activeSelectedId !== null
                    ? "Modification instruction"
                    : "Part description"
                }
              />
              <button
                className="generate-button"
                onClick={
                  activeSelectedId !== null ? handleModify : handleGenerate
                }
                disabled={busy || prompt.trim().length === 0}
                aria-label={
                  activeSelectedId !== null
                    ? "Modify selected CAD model"
                    : "Generate CAD model"
                }
              >
                {busy
                  ? "Working..."
                  : activeSelectedId !== null
                    ? "Modify"
                    : "Generate"}
              </button>
            </div>
            <div className="prompt-footer">
              <span className="char-count">
                {prompt.length} / {MAX_PROMPT_LENGTH}
              </span>
              <span className="char-count">
                {busy
                  ? activeSelectedId !== null
                    ? "Modifying…"
                    : "Generating…"
                  : `Ctrl+Enter to ${activeSelectedId !== null ? "modify" : "generate"}`}
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
            bom={
              displayResult ? <Bom spec={displayResult.specification} /> : undefined
            }
            assembly={
              <>
                <AssemblyTree
                  name={
                    displayResult
                      ? displayResult.specification.name
                      : activeWorkspace.name
                  }
                  objects={objects}
                  groups={
                    displayResult
                      ? groupsOf(displayResult.specification)
                      : []
                  }
                  selectedId={activeSelectedId}
                  selectedIds={selectedIds}
                  onSelect={handleTreeSelect}
                  onSelectGroup={handleSelectGroup}
                  onToggleVisible={handleToggleVisible}
                  onRemove={handleRemoveComponent}
                  onGroup={handleGroup}
                  onUngroup={handleUngroup}
                  onLock={handleLock}
                  onDuplicate={handleDuplicate}
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
                  bounds={
                    activeSelectedId === null
                      ? null
                      : objectBounds[activeSelectedId] ?? null
                  }
                  alignCount={selectedIds.length}
                  onSeatFloor={handleSeatFloor}
                  onCentre={handleCentre}
                  onAlign={handleAlign}
                  onName={handleNameChange}
                  onPosition={handleEditPosition}
                  onRotation={handleEditRotation}
                  onParam={(key, value) =>
                    setDraftParams((prev) => ({ ...prev, [key]: value }))
                  }
                  onApplyPlacement={handleApplyPlacement}
                  onApplyParams={handleApplyParams}
                />
                <MotionPanel
                  track={activeTrack}
                  duration={motionDuration}
                  playhead={playhead}
                  playing={playing}
                  canAnimate={
                    selectedObject !== null &&
                    selectedObject.instances.length <= 1 &&
                    !selectedObject.locked
                  }
                  busy={busy}
                  onPlay={handlePlay}
                  onScrub={(time) => {
                    setPlaying(false);
                    setPlayhead(time);
                  }}
                  onAddKey={handleAddKey}
                  onRemoveKey={handleRemoveKey}
                  onToggleTrack={handleToggleTrack}
                  onDuration={handleDuration}
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
