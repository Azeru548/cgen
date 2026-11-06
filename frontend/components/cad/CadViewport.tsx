"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  ContactShadows,
  Environment,
  GizmoHelper,
  GizmoViewport,
  Grid,
  Html,
  Lightformer,
  Line,
  OrbitControls,
  OrthographicCamera,
  PerspectiveCamera,
  TransformControls,
} from "@react-three/drei";
import {
  FrameCamera,
  StlModel,
  type PreviewState,
  type ViewName,
} from "./StlModel";
import { GenerationLoader } from "../GenerationLoader";
import { DEFAULT_MATERIAL_ID, MATERIALS, type MaterialId } from "@/lib/materials";
import { sampleTrack, type ObjectBounds } from "@/lib/assembly";
import type { MotionTrack, SceneAnimation } from "@/types/api";

export const EXAMPLE_PROMPTS = [
  "Create a 100mm × 60mm × 30mm rectangular block.",
  "Create a 50mm diameter sphere.",
  "Create a 120mm shaft with a 15mm through-hole.",
  "Create an enclosure for an Arduino Uno with four M3 mounting screws and a USB opening.",
];

export interface SceneViewObject {
  id: string;
  url: string;
  position: [number, number, number];
  rotation: [number, number, number];
  visible: boolean;
  selected: boolean;
  instances: Array<{
    position: [number, number, number];
    rotation: [number, number, number];
  }>;
  recenter: boolean;
  /** Selected instance of a repeated component; -1 moves the component itself. */
  activeInstanceIndex?: number;
  /** Show the move/rotate gizmo on this object (primary selection only). */
  gizmo?: boolean;
  /** Ignore this part's motion track and draw its draft pose instead: true
   *  while the gizmo is dragging it, so the drag is live. */
  freezeMotion?: boolean;
}

/** Live numbers for the selected object. Position/rotation come from the
 *  editor (its drafts update on every drag frame); the size comes from the
 *  parsed mesh, so it is the built part's envelope, not the requested one. */
export interface ViewerReadout {
  id: string;
  name: string;
  position: [number, number, number];
  rotation: [number, number, number];
  /** Active instance of a repeated component; -1 targets the component. */
  instanceIndex?: number;
}

interface CadViewportProps {
  objects: SceneViewObject[];
  /** Selected object's live pose/size readout; null hides the DRO. */
  readout?: ViewerReadout | null;
  /** Reports each parsed mesh's local bounds so the editor can seat/centre it. */
  onBounds?: (id: string, bounds: ObjectBounds) => void;
  /** Drag snap step in millimetres; 0 disables snapping. */
  snapMm?: number;
  onSnapChange?: (step: number) => void;
  /** Scene motion metadata (viewer only, never exported). */
  animation?: SceneAnimation | null;
  playing?: boolean;
  playhead?: number;
  /** Reports the clock while playing (~10 Hz, for the scrub bar). */
  onPlayhead?: (time: number) => void;
  busy: boolean;
  previewError: string | null;
  onPreviewStatus: (state: PreviewState, message?: string) => void;
  onSelectExample: (prompt: string) => void;
  onSelectObject?: (
    id: string | null,
    instanceIndex?: number,
    additive?: boolean,
  ) => void;
  /** Technical chip text shown top-left (schema/engine revision). */  schemaVersion?: string;
  /** Immediate dial-drag scale applied to the current mesh. */
  liveScale?: [number, number, number] | null;
  /** Drag selected object → world translation delta (mm). Draft only. */
  onMoveDelta?: (delta: [number, number, number]) => void;
  /** Rotate gizmo → world Euler delta in degrees. Draft only. */
  onRotateDelta?: (delta: [number, number, number]) => void;
  /** Drag began — parent can freeze other inputs. */
  onMoveStart?: () => void;
  onRotateStart?: () => void;
  /** Drag ended — bake drafts; parent may reset the drag group. */
  onMoveEnd?: () => void;
  /** When false, no TransformControls (busy / no selection). */
  canDrag?: boolean;
}

type GizmoMode = "translate" | "rotate";

const ORIGIN_POSE: [number, number, number] = [0, 0, 0];

/** Shared scene clock: one source of truth for every animated part. */
export interface MotionClockRef {
  current: { time: number; playing: boolean };
}

/** Advances the clock while playing and reports it for the scrub bar. */
function MotionTicker({
  clock,
  duration,
  onTick,
}: {
  clock: MotionClockRef;
  duration: number;
  onTick?: (time: number) => void;
}) {
  const lastReport = useRef(0);
  useFrame((_, delta) => {
    if (!clock.current.playing) return;
    const span = Math.max(duration, 0.2);
    clock.current.time = (clock.current.time + delta) % span;
    const now = performance.now();
    if (now - lastReport.current > 100) {
      lastReport.current = now;
      onTick?.(clock.current.time);
    }
  });
  return null;
}

/** Applies a track's sampled pose to the part it wraps. `track: null` leaves
 *  the part at the pose its StlModel props already carry. */
function MotionPose({
  track,
  clock,
  playhead,
  children,
}: {
  track: MotionTrack | null;
  clock: MotionClockRef;
  playhead: number;
  children: ReactNode;
}) {
  const node = useRef<THREE.Group>(null);
  useFrame(() => {
    const group = node.current;
    if (!group) return;
    if (track === null) {
      group.position.set(0, 0, 0);
      group.rotation.set(0, 0, 0);
      return;
    }
    const time = clock.current.playing ? clock.current.time : playhead;
    const pose = sampleTrack(track, time);
    group.position.set(pose.position[0], pose.position[1], pose.position[2]);
    group.rotation.set(
      (pose.rotation[0] * Math.PI) / 180,
      (pose.rotation[1] * Math.PI) / 180,
      (pose.rotation[2] * Math.PI) / 180,
      "ZYX",
    );
  });
  return <group ref={node}>{children}</group>;
}

const VIEW_BUTTONS: Array<{ view: ViewName; label: string; title: string }> = [
  { view: "front", label: "Front", title: "Look at the front (CAD −Y)" },
  { view: "top", label: "Top", title: "Look down from above (CAD +Z)" },
  { view: "right", label: "Right", title: "Look at the right side (CAD +X)" },
  { view: "iso", label: "Iso", title: "Three-quarter view" },
];

/** Two-point distance measurement, drawn in world space over the CAD frame.
 *  Points arrive in world coordinates; the delta is converted back to CAD
 *  axes (X, Y, Z-up) so the numbers match the inspector. */
function MeasureOverlay({
  points,
  scale,
}: {
  points: THREE.Vector3[];
  scale: number;
}) {
  if (points.length === 0) return null;
  const dot = Math.max(scale * 0.006, 0.5);
  const pair = points.length === 2 ? points : null;
  const distance = pair ? pair[0].distanceTo(pair[1]) : 0;
  const cad = pair
    ? {
        dx: pair[1].x - pair[0].x,
        dy: -(pair[1].z - pair[0].z),
        dz: pair[1].y - pair[0].y,
      }
    : null;
  return (
    <>
      {points.map((point, index) => (
        <mesh key={`measure-point-${index}`} position={point}>
          <sphereGeometry args={[dot, 12, 12]} />
          <meshBasicMaterial color="#e8eaed" />
        </mesh>
      ))}
      {pair ? (
        <>
          <Line
            points={[pair[0], pair[1]]}
            color="#e8eaed"
            lineWidth={1.4}
            dashed={false}
          />
          <Html
            position={pair[0].clone().add(pair[1]).multiplyScalar(0.5)}
            center
            className="measure-label"
            zIndexRange={[20, 0]}
          >
            <span className="measure-value">{distance.toFixed(2)} mm</span>
            {cad ? (
              <span className="measure-delta">
                {cad.dx.toFixed(1)} · {cad.dy.toFixed(1)} · {cad.dz.toFixed(1)}
              </span>
            ) : null}
          </Html>
        </>
      ) : null}
    </>
  );
}

/** Axis cross at the world origin: without it "zero" is implied, never seen. */
function OriginMarker({ scale }: { scale: number }) {
  const length = Math.max(scale * 0.14, 8);
  const thickness = Math.max(scale * 0.005, 0.4);
  const axes: Array<{
    position: [number, number, number];
    size: [number, number, number];
    color: string;
  }> = [
    { position: [length / 2, 0, 0], size: [length, thickness, thickness], color: "#cc2936" },
    { position: [0, length / 2, 0], size: [thickness, length, thickness], color: "#6a7280" },
    { position: [0, 0, length / 2], size: [thickness, thickness, length], color: "#e8eaed" },
  ];
  return (
    <group>
      {axes.map((axis) => (
        <mesh key={axis.color} position={axis.position}>
          <boxGeometry args={axis.size} />
          <meshBasicMaterial color={axis.color} transparent opacity={0.45} />
        </mesh>
      ))}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[length * 0.42, length * 0.46, 48]} />
        <meshBasicMaterial
          color="#e8eaed"
          transparent
          opacity={0.18}
          side={THREE.DoubleSide}
        />
      </mesh>
    </group>
  );
}

/** DRO numeral: one decimal, em dash when the value is not finite. */
function dro(value: number): string {
  return Number.isFinite(value) ? value.toFixed(1) : "—";
}

function eulerToDeg(e: THREE.Euler): [number, number, number] {
  return [
    (e.x * 180) / Math.PI,
    (e.y * 180) / Math.PI,
    (e.z * 180) / Math.PI,
  ];
}

/** One object = one stable group. Selection never remounts StlModel
 *  (remount disposed geometry and blanked the well). TransformControls
 *  attaches to this group only while the object is selected. */
function SelectableObject({
  object,
  canDrag,
  gizmoMode,
  onMoveDelta,
  onRotateDelta,
  onMoveStart,
  onRotateStart,
  onMoveEnd,
  onGeometry,
  onBounds,
  onPreviewStatus,
  onSelectObject,
  liveScale,
  onOrbitEnabledChange,
  material,
  motion,
  clock,
  playhead,
  measure,
  onMeasure,
}: {
  object: SceneViewObject;
  canDrag: boolean;
  gizmoMode: GizmoMode;
  onMoveDelta?: (delta: [number, number, number]) => void;
  onRotateDelta?: (delta: [number, number, number]) => void;
  onMoveStart?: () => void;
  onRotateStart?: () => void;
  onMoveEnd?: () => void;
  onGeometry: () => void;
  /** Reports the mesh's local bounds (mm) for the DRO and placement tools. */
  onBounds?: (id: string, bounds: ObjectBounds) => void;
  onPreviewStatus: (state: PreviewState, message?: string) => void;
  onSelectObject?: (
    id: string | null,
    instanceIndex?: number,
    additive?: boolean,
  ) => void;
  liveScale?: [number, number, number] | null;
  onOrbitEnabledChange?: (enabled: boolean) => void;
  material: MaterialId;
  motion?: SceneAnimation | null;
  clock: MotionClockRef;
  playhead: number;
  measure?: boolean;
  onMeasure?: (point: THREE.Vector3) => void;
}) {
  // The gizmo rides on its own anchor node, sitting on the part it edits, so
  // the arrows are where the part is — not back at the world origin. Deltas are
  // measured against where the anchor started, and the mesh itself is never
  // attached to the gizmo (the editor's drafts move it).
  const anchorRef = useRef<THREE.Group>(null);
  const anchorBaseRef = useRef<[number, number, number]>([0, 0, 0]);
  const dragRef = useRef(false);
  const [anchorNode, setAnchorNode] = useState<THREE.Group | null>(null);
  const showGizmo = canDrag && (object.gizmo ?? object.selected) && object.url.length > 0;
  // -1 targets the component transform (single-pose parts / whole-component
  // move); >=0 targets one instance of a repeated component.
  const activeIndex = object.activeInstanceIndex ?? -1;
  const hasInstances = object.instances.length > 0;
  // Repeated components are placed by instance poses, so a track would have
  // nowhere to live; the editor disables motion for them.
  const track =
    motion?.tracks.find((item) => item.component_id === object.id) ?? null;
  const animated =
    track !== null && !hasInstances && object.freezeMotion !== true;

  const setAnchor = useCallback((node: THREE.Group | null) => {
    anchorRef.current = node;
    setAnchorNode(node);
  }, []);

  // Park the anchor wherever the part is drawn: one instance's pose for a
  // repeated component, the component pose otherwise.
  const activeInstancePose =
    object.activeInstanceIndex !== undefined && object.activeInstanceIndex >= 0
      ? object.instances[object.activeInstanceIndex]
      : undefined;
  const anchorPosition: [number, number, number] =
    activeInstancePose?.position ?? object.position;
  const anchorPositionRef = useRef(anchorPosition);
  anchorPositionRef.current = anchorPosition;

  useEffect(() => {
    const node = anchorRef.current;
    // A drag owns the anchor for its duration: writing the prop back in would
    // zero the rotation (or drag the arrows with the part) mid-gesture.
    if (node === null || dragRef.current) return;
    node.position.set(anchorPosition[0], anchorPosition[1], anchorPosition[2]);
    node.rotation.set(0, 0, 0);
  }, [anchorPosition[0], anchorPosition[1], anchorPosition[2], showGizmo]);

  // The parsed mesh is already centered on its own bbox, so its bounding box
  // is the part's true envelope — report it for the DRO and placement tools.
  const handleGeometry = useCallback(
    (geometry: THREE.BufferGeometry | null) => {
      onGeometry();
      if (!geometry || !onBounds) return;
      geometry.computeBoundingBox();
      const box = geometry.boundingBox;
      if (!box) return;
      const size = box.getSize(new THREE.Vector3());
      onBounds(object.id, {
        min: [box.min.x, box.min.y, box.min.z],
        size: [size.x, size.y, size.z],
      });
    },
    [onGeometry, onBounds, object.id],
  );

  // NOTE: TransformControls MUST stay a sibling of the group it drives.
  // drei renders its gizmo helper as a child of wherever this element
  // sits; nesting it inside the controlled group feeds the gizmo back
  // into its own transform math and locks the render loop on select.
  return (
    <>
      {hasInstances ? (
        /* Repeated component: one group per instance so a single screw can be
         * dragged without dragging its siblings. */
        <>
          {object.instances.map((pose, index) => (
            <group key={`${object.id}:${index}`}>
              <StlModel
                url={object.url}
                onStatus={onPreviewStatus}
                onGeometry={handleGeometry}
                scale={liveScale}
                position={pose.position}
                rotationDeg={pose.rotation}
                recenter={object.recenter}
                selected={object.selected && index === activeIndex}
                objectId={object.id}
                instanceIndex={index}
                onSelect={onSelectObject}
                material={material}
                measure={measure}
                onMeasure={onMeasure}
              />
            </group>
          ))}
        </>
      ) : (
        <group>
          <MotionPose track={animated ? track : null} clock={clock} playhead={playhead}>
            <StlModel
              url={object.url}
              onStatus={onPreviewStatus}
              onGeometry={handleGeometry}
              scale={liveScale}
              position={animated ? ORIGIN_POSE : object.position}
              rotationDeg={animated ? ORIGIN_POSE : object.rotation}
              recenter={object.recenter}
              selected={object.selected}
              objectId={object.id}
              instanceIndex={-1}
              onSelect={onSelectObject}
              material={material}
              measure={measure}
              onMeasure={onMeasure}
            />
          </MotionPose>
        </group>
      )}

      {showGizmo ? (
        <group
          ref={setAnchor}
          position={anchorPosition}
          userData={{ cgenGizmo: true }}
        />
      ) : null}

      {showGizmo && gizmoMode === "translate" && anchorNode ? (
        <TransformControls
          object={anchorNode}
          mode="translate"
          size={0.85}
          onMouseDown={() => {
            dragRef.current = true;
            const node = anchorRef.current;
            anchorBaseRef.current = node
              ? [node.position.x, node.position.y, node.position.z]
              : [0, 0, 0];
            onOrbitEnabledChange?.(false);
            onMoveStart?.();
          }}
          onMouseUp={() => {
            const node = anchorRef.current;
            const base = anchorBaseRef.current;
            const delta: [number, number, number] = node
              ? [
                  node.position.x - base[0],
                  node.position.y - base[1],
                  node.position.z - base[2],
                ]
              : [0, 0, 0];
            dragRef.current = false;
            onOrbitEnabledChange?.(true);
            // Commit the final delta while it is still non-zero, then park the
            // anchor on the part again. The parent bakes the new absolute pose
            // into the draft, so the part stays where it was dropped.
            if (delta[0] !== 0 || delta[1] !== 0 || delta[2] !== 0) {
              onMoveDelta?.(delta);
            }
            node?.position.set(base[0], base[1], base[2]);
            onMoveEnd?.();
          }}
          onObjectChange={() => {
            if (!dragRef.current || !onMoveDelta) return;
            const node = anchorRef.current;
            if (!node) return;
            const base = anchorBaseRef.current;
            onMoveDelta([
              node.position.x - base[0],
              node.position.y - base[1],
              node.position.z - base[2],
            ]);
          }}
        />
      ) : null}

      {showGizmo && gizmoMode === "rotate" && anchorNode ? (
        <TransformControls
          object={anchorNode}
          mode="rotate"
          size={0.95}
          onMouseDown={() => {
            dragRef.current = true;
            onOrbitEnabledChange?.(false);
            onRotateStart?.();
          }}
          onMouseUp={() => {
            const node = anchorRef.current;
            const delta = node
              ? eulerToDeg(node.rotation)
              : ([0, 0, 0] as [number, number, number]);
            dragRef.current = false;
            onOrbitEnabledChange?.(true);
            if (delta[0] !== 0 || delta[1] !== 0 || delta[2] !== 0) {
              onRotateDelta?.(delta);
            }
            if (node) {
              const rest = anchorPositionRef.current;
              node.position.set(rest[0], rest[1], rest[2]);
              node.rotation.set(0, 0, 0);
            }
            onMoveEnd?.();
          }}
          onObjectChange={() => {
            if (!dragRef.current || !onRotateDelta) return;
            const node = anchorRef.current;
            if (!node) return;
            onRotateDelta(eulerToDeg(node.rotation));
          }}
        />
      ) : null}
    </>
  );
}

function DragGroup({
  objects,
  canDrag,
  gizmoMode,
  onMoveDelta,
  onRotateDelta,
  onMoveStart,
  onRotateStart,
  onMoveEnd,
  onGeometry,
  onBounds,
  onPreviewStatus,
  onSelectObject,
  liveScale,
  contentRev,
  resetSignal,
  floorY,
  hasContent,
  onOrbitEnabledChange,
  material,
  onScale,
  viewRequest,
  projection,
  motion,
  clock,
  playhead,
  measure,
  onMeasure,
}: {
  objects: SceneViewObject[];
  canDrag: boolean;
  gizmoMode: GizmoMode;
  onMoveDelta?: (delta: [number, number, number]) => void;
  onRotateDelta?: (delta: [number, number, number]) => void;
  onMoveStart?: () => void;
  onRotateStart?: () => void;
  onMoveEnd?: () => void;
  onGeometry: () => void;
  /** Reports the mesh's local bounds (mm) for the DRO and placement tools. */
  onBounds?: (id: string, bounds: ObjectBounds) => void;
  onPreviewStatus: (state: PreviewState, message?: string) => void;
  onSelectObject?: (
    id: string | null,
    instanceIndex?: number,
    additive?: boolean,
  ) => void;
  liveScale?: [number, number, number] | null;
  contentRev: number;
  resetSignal: number;
  floorY: (y: number) => void;
  hasContent: boolean;
  onOrbitEnabledChange?: (enabled: boolean) => void;
  material: MaterialId;
  onScale: (maxDim: number) => void;
  viewRequest?: { id: number; view: ViewName } | null;
  projection: "persp" | "ortho";
  motion?: SceneAnimation | null;
  clock: MotionClockRef;
  playhead: number;
  measure?: boolean;
  onMeasure?: (point: THREE.Vector3) => void;
}) {
  const [outerNode, setOuterNode] = useState<THREE.Group | null>(null);

  return (
    <group ref={setOuterNode}>
      {/* CAD documents are Z-up; three.js is Y-up. Rotating the whole scene
          once keeps every stored transform in CAD axes (Z is up, as in the
          inspector and the exported STEP) while the viewer stays Y-up. */}
      <group rotation={[-Math.PI / 2, 0, 0]}>
        {objects.map((object) => (
          <SelectableObject
            key={object.id}
            object={object}
            canDrag={canDrag}
            gizmoMode={gizmoMode}
            onMoveDelta={onMoveDelta}
            onRotateDelta={onRotateDelta}
            onMoveStart={onMoveStart}
            onRotateStart={onRotateStart}
            onMoveEnd={onMoveEnd}
            onGeometry={onGeometry}
            onBounds={onBounds}
            onPreviewStatus={onPreviewStatus}
            onSelectObject={onSelectObject}
            liveScale={liveScale}
            onOrbitEnabledChange={onOrbitEnabledChange}
            material={material}
            motion={motion}
            clock={clock}
            playhead={playhead}
            measure={measure}
            onMeasure={onMeasure}
          />
        ))}
      </group>

      <FrameCamera
        group={outerNode}
        contentRev={contentRev}
        resetSignal={resetSignal}
        floorY={floorY}
        hasContent={hasContent}
        onScale={onScale}
        viewRequest={viewRequest}
        projection={projection}
      />
    </group>
  );
}

/** Exposes the live WebGL canvas so the toolbar can save a PNG frame.
 *  (`preserveDrawingBuffer` on the renderer keeps the buffer readable after
 *  the frame is presented.) */
function CaptureTarget({
  onCanvas,
}: {
  onCanvas: (canvas: HTMLCanvasElement | null) => void;
}) {
  const gl = useThree((state) => state.gl);
  useEffect(() => {
    onCanvas(gl.domElement);
  }, [gl, onCanvas]);
  return null;
}

export function CadViewport({
  objects,
  busy,
  previewError,
  onPreviewStatus,
  onSelectExample,
  onSelectObject,
  schemaVersion,
  liveScale,
  onMoveDelta,
  onRotateDelta,
  onMoveStart,
  onRotateStart,
  onMoveEnd,
  canDrag = false,
  readout = null,
  onBounds,
  snapMm = 0,
  onSnapChange,
  animation = null,
  playing = false,
  playhead = 0,
  onPlayhead,
}: CadViewportProps) {
  const [gizmoMode, setGizmoMode] = useState<GizmoMode>("translate");
  const [contentRev, setContentRev] = useState(0);
  const [resetSignal, setResetSignal] = useState(0);
  const [floorY, setFloorY] = useState(0);
  const [orbitEnabled, setOrbitEnabled] = useState(true);
  const [sceneScale, setSceneScale] = useState(120);
  const [material, setMaterial] = useState<MaterialId>(DEFAULT_MATERIAL_ID);
  const [bounds, setBounds] = useState<Record<string, ObjectBounds>>({});
  const [view, setView] = useState<ViewName>("iso");
  const [viewId, setViewId] = useState(0);
  const clockRef = useRef<{ time: number; playing: boolean }>({
    time: 0,
    playing: false,
  });
  // Playback runs on the render loop; only the scrub bar follows React state.
  useEffect(() => {
    clockRef.current.playing = playing;
  }, [playing]);
  useEffect(() => {
    if (!playing) clockRef.current.time = playhead;
  }, [playhead, playing]);
  const [ortho, setOrtho] = useState(false);
  const viewRequest = useMemo(() => ({ id: viewId, view }), [viewId, view]);
  const handleView = useCallback((next: ViewName) => {
    setView(next);
    setViewId((n) => n + 1);
  }, []);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const handleFloorY = useCallback((y: number) => setFloorY(y), []);
  const handleScale = useCallback((maxDim: number) => {
    setSceneScale((prev) => (prev === maxDim ? prev : maxDim));
  }, []);
  const handleCanvas = useCallback((canvas: HTMLCanvasElement | null) => {
    canvasRef.current = canvas;
  }, []);
  const handleGeometry = useCallback(() => {
    setContentRev((n) => n + 1);
  }, []);
  const handleOrbitEnabled = useCallback((enabled: boolean) => {
    setOrbitEnabled(enabled);
  }, []);
  const handleBounds = useCallback(
    (id: string, next: ObjectBounds) => {
      setBounds((prev) => {
        const last = prev[id];
        if (
          last &&
          last.min[0] === next.min[0] &&
          last.min[1] === next.min[1] &&
          last.min[2] === next.min[2] &&
          last.size[0] === next.size[0] &&
          last.size[1] === next.size[1] &&
          last.size[2] === next.size[2]
        ) {
          return prev;
        }
        return { ...prev, [id]: next };
      });
      onBounds?.(id, next);
    },
    [onBounds],
  );
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState<THREE.Vector3[]>([]);
  const handleMeasurePoint = useCallback((point: THREE.Vector3) => {
    // Third click starts a new measurement instead of silently doing nothing.
    setMeasurePoints((prev) => (prev.length >= 2 ? [point] : [...prev, point]));
  }, []);
  const toggleMeasure = useCallback(() => {
    setMeasureMode((on) => {
      if (on) setMeasurePoints([]);
      return !on;
    });
  }, []);
  useEffect(() => {
    if (!measureMode) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMeasureMode(false);
        setMeasurePoints([]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [measureMode]);
  const pointerMoved = useRef(false);
  const clearSelectionIfClick = useCallback(() => {
    if (!pointerMoved.current) onSelectObject?.(null);
  }, [onSelectObject]);

  const chooseMaterial = useCallback((id: MaterialId) => {
    setMaterial(id);
  }, []);

  const handleSnapshot = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const link = document.createElement("a");
    link.href = canvas.toDataURL("image/png");
    link.download = `cgen-${stamp}.png`;
    link.click();
  }, []);

  const visible = objects.filter((o) => o.visible && o.url);
  const showEmpty = visible.length === 0 && !busy && !previewError;
  const readoutSize = readout ? bounds[readout.id]?.size ?? null : null;

  return (
    <div className="viewport" data-testid="viewport">
      <Canvas
        camera={{ fov: 40, position: [180, 140, 180] }}
        dpr={[1, 2]}
        gl={{
          antialias: true,
          preserveDrawingBuffer: true,
          toneMapping: THREE.ACESFilmicToneMapping,
          toneMappingExposure: 1.05,
        }}
        onPointerDown={() => {
          pointerMoved.current = false;
        }}
        onPointerMove={(event) => {
          if (event.buttons) pointerMoved.current = true;
        }}
        onPointerMissed={clearSelectionIfClick}
      >
        <color attach="background" args={["#0e1014"]} />
        <CaptureTarget onCanvas={handleCanvas} />
        {ortho ? (
          <OrthographicCamera
            makeDefault
            position={[180, 140, 180]}
            zoom={1}
            near={-5000}
            far={50000}
          />
        ) : (
          <PerspectiveCamera
            makeDefault
            fov={40}
            position={[180, 140, 180]}
            near={0.1}
            far={50000}
          />
        )}
        <ambientLight intensity={0.35} />
        <directionalLight position={[120, 180, 90]} intensity={1.1} />
        {/* A studio built from emissive panels instead of an HDRI file: no
            network request, no CDN, and the reflections can be art-directed. */}
        <Environment resolution={128} frames={1}>
          <Lightformer
            form="rect"
            intensity={5}
            position={[0, 6, -7]}
            scale={[12, 5, 1]}
            color="#ffffff"
          />
          <Lightformer
            form="rect"
            intensity={2.4}
            position={[-7, 3, 3]}
            rotation={[0, Math.PI / 2, 0]}
            scale={[9, 6, 1]}
            color="#cfe0ff"
          />
          <Lightformer
            form="rect"
            intensity={1.8}
            position={[7, 1, 4]}
            rotation={[0, -Math.PI / 2, 0]}
            scale={[9, 6, 1]}
            color="#ffe8d8"
          />
          <Lightformer
            form="ring"
            intensity={1.6}
            position={[0, 7, 0]}
            scale={[7, 7, 1]}
            color="#ffffff"
          />
        </Environment>
        <Suspense fallback={null}>
          <group>
            <DragGroup
              objects={visible}
              canDrag={canDrag && !busy}
              gizmoMode={gizmoMode}
              onMoveDelta={onMoveDelta}
              onRotateDelta={onRotateDelta}
              onMoveStart={onMoveStart}
              onRotateStart={onRotateStart}
              onMoveEnd={onMoveEnd}
              onGeometry={handleGeometry}
              onBounds={handleBounds}
              onPreviewStatus={onPreviewStatus}
              onSelectObject={onSelectObject}
              liveScale={liveScale}
              contentRev={contentRev}
              resetSignal={resetSignal}
              floorY={handleFloorY}
              hasContent={visible.length > 0}
              onOrbitEnabledChange={handleOrbitEnabled}
              material={material}
              onScale={handleScale}
              viewRequest={viewRequest}
              projection={ortho ? "ortho" : "persp"}
              motion={animation}
              clock={clockRef}
              playhead={playhead}
              measure={measureMode}
              onMeasure={handleMeasurePoint}
            />
            <MotionTicker
              clock={clockRef}
              duration={animation?.duration ?? 4}
              onTick={onPlayhead}
            />
            <OriginMarker scale={sceneScale} />
            <MeasureOverlay points={measurePoints} scale={sceneScale} />
          </group>
          <ContactShadows
            key={`${contentRev}-${Math.round(sceneScale)}-${Math.round(floorY)}`}
            position={[0, floorY + 0.2, 0]}
            scale={Math.max(sceneScale * 3, 40)}
            blur={2.4}
            opacity={0.55}
            far={Math.max(sceneScale * 0.6, 10)}
            resolution={256}
            frames={1}
            color="#000000"
            onClick={clearSelectionIfClick}
          />
          <Grid
            position={[0, floorY, 0]}
            args={[10, 10]}
            cellSize={10}
            cellThickness={0.55}
            cellColor="#2a2e36"
            sectionSize={50}
            sectionThickness={1}
            sectionColor="#3a4048"
            fadeDistance={1400}
            fadeStrength={2}
            infiniteGrid
            onClick={(event) => {
              event.stopPropagation();
              clearSelectionIfClick();
            }}
          />
        </Suspense>
        <OrbitControls
          makeDefault
          enabled={orbitEnabled}
          enableDamping
          dampingFactor={0.12}
          minDistance={5}
          maxDistance={5000}
        />
        <GizmoHelper alignment="top-right" margin={[56, 56]}>
          <GizmoViewport
            axisColors={["#cc2936", "#6a7280", "#d8dce2"]}
            labelColor="#e8eaed"
          />
        </GizmoHelper>
      </Canvas>

      {schemaVersion ? (
        <span className="viewport-tag">{schemaVersion}</span>
      ) : null}

      <div className="viewport-views" role="group" aria-label="Standard views">
        <div className="material-switch">
          {VIEW_BUTTONS.map((button) => (
            <button
              key={button.view}
              type="button"
              className={`material-option${view === button.view ? " is-active" : ""}`}
              onClick={() => handleView(button.view)}
              aria-pressed={view === button.view}
              title={button.title}
            >
              {button.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={`viewport-mode${ortho ? " is-active" : ""}`}
          onClick={() => setOrtho((value) => !value)}
          aria-pressed={ortho}
          title={
            ortho
              ? "Orthographic projection: switch back to perspective"
              : "Perspective projection: switch to orthographic"
          }
        >
          {ortho ? "Ortho" : "Persp"}
        </button>
      </div>

      {readout ? (
        <div className="viewport-dro" data-testid="viewport-readout">
          <div className="viewport-dro-head">
            <span className="viewport-dro-name">{readout.name}</span>
            {(readout.instanceIndex ?? -1) >= 0 ? (
              <span className="viewport-dro-slot">
                inst {(readout.instanceIndex ?? 0) + 1}
              </span>
            ) : null}
          </div>
          <div className="viewport-dro-grid">
            <span />
            <span className="viewport-dro-axis">X</span>
            <span className="viewport-dro-axis">Y</span>
            <span className="viewport-dro-axis">Z</span>
            <span className="viewport-dro-key">pos</span>
            {readout.position.map((value, axis) => (
              <span key={`pos-${axis}`} className="viewport-dro-value">
                {dro(value)}
              </span>
            ))}
            <span className="viewport-dro-key">rot °</span>
            {readout.rotation.map((value, axis) => (
              <span key={`rot-${axis}`} className="viewport-dro-value">
                {dro(value)}
              </span>
            ))}
            {readoutSize ? (
              <>
                <span className="viewport-dro-key">size</span>
                {readoutSize.map((value, axis) => (
                  <span key={`size-${axis}`} className="viewport-dro-value">
                    {dro(value)}
                  </span>
                ))}
              </>
            ) : null}
          </div>
          <span className="viewport-dro-unit">pos / size mm</span>
        </div>
      ) : null}

      <div className="viewport-toolbar">
        <div className="viewport-controls">
          {canDrag ? (
            <div
              className="material-switch"
              role="group"
              aria-label="Move or rotate the selected part"
            >
              <button
                type="button"
                className={`material-option${gizmoMode === "translate" ? " is-active" : ""}`}
                onClick={() => setGizmoMode("translate")}
                aria-pressed={gizmoMode === "translate"}
                title="Move the selected part"
              >
                Move
              </button>
              <button
                type="button"
                className={`material-option${gizmoMode === "rotate" ? " is-active" : ""}`}
                onClick={() => setGizmoMode("rotate")}
                aria-pressed={gizmoMode === "rotate"}
                title="Rotate the selected part"
              >
                Rotate
              </button>
            </div>
          ) : null}
          {canDrag && onSnapChange ? (
            <div className="material-switch" role="group" aria-label="Drag snap">
              {[0, 1, 5, 10].map((step) => (
                <button
                  key={step}
                  type="button"
                  className={`material-option${snapMm === step ? " is-active" : ""}`}
                  onClick={() => onSnapChange(step)}
                  aria-pressed={snapMm === step}
                  title={
                    step === 0
                      ? "Move freely"
                      : `Snap the part to a ${step} mm grid`
                  }
                >
                  {step === 0 ? "Free" : step}
                </button>
              ))}
            </div>
          ) : null}
          <div
            className="material-switch"
            role="group"
            aria-label="Surface finish"
          >
            {MATERIALS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`material-option${material === preset.id ? " is-active" : ""}`}
                onClick={() => chooseMaterial(preset.id)}
                aria-pressed={material === preset.id}
                title={`${preset.label} finish (display only)`}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <span className="viewport-hint">
            {measureMode
              ? "click two points · esc to stop"
              : null}
            {measureMode ? null : (
              <>
                drag&nbsp;·&nbsp;orbit&nbsp;&nbsp;&nbsp;shift-click&nbsp;·&nbsp;add
              </>
            )}
            {canDrag ? (
              gizmoMode === "rotate" ? (
                <>&nbsp;&nbsp;&nbsp;rings&nbsp;·&nbsp;rotate part</>
              ) : (
                <>&nbsp;&nbsp;&nbsp;arrows&nbsp;·&nbsp;move part</>
              )
            ) : null}
          </span>
        </div>
        <div className="viewport-actions">
          <button
            type="button"
            className={`viewport-reset${measureMode ? " is-active" : ""}`}
            onClick={toggleMeasure}
            disabled={visible.length === 0}
            aria-pressed={measureMode}
            title="Measure the distance between two points"
          >
            Measure
          </button>
          <button
            type="button"
            className="viewport-reset"
            onClick={handleSnapshot}
            disabled={visible.length === 0}
            title="Save this view as a PNG"
          >
            Snapshot
          </button>
          <button
            type="button"
            className="viewport-reset"
            onClick={() => setResetSignal((s) => s + 1)}
            disabled={visible.length === 0}
            aria-label="Reset view"
          >
            Reset view
          </button>
        </div>
      </div>

      {showEmpty ? (
        <div className="viewport-overlay" data-testid="empty-state">
          <p className="overlay-title">Your CAD model will appear here</p>
          <p className="overlay-text">
            Describe a part, or add a component from the library.
          </p>
          <ul className="overlay-examples">
            {EXAMPLE_PROMPTS.map((prompt) => (
              <li key={prompt}>
                <button
                  type="button"
                  className="example-link"
                  onClick={() => onSelectExample(prompt)}
                >
                  {prompt}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {busy ? (
        <div
          className="viewport-overlay viewport-overlay-busy"
          role="status"
          data-testid="viewport-loading"
        >
          <GenerationLoader />
        </div>
      ) : null}

      {previewError && !busy ? (
        <div className="viewport-overlay" role="alert" data-testid="viewport-error">
          <p className="overlay-title">Preview unavailable</p>
          <p className="overlay-text">{previewError}</p>
          <p className="overlay-text overlay-note">
            This revision&apos;s files expired. Reload to rebuild them from its
            saved specification.
          </p>
        </div>
      ) : null}
    </div>
  );
}
