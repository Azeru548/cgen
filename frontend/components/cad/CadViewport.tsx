"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas } from "@react-three/fiber";
import {
  GizmoHelper,
  GizmoViewport,
  Grid,
  OrbitControls,
  TransformControls,
} from "@react-three/drei";
import { FrameCamera, StlModel, type PreviewState } from "./StlModel";
import { GenerationLoader } from "../GenerationLoader";

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
}

interface CadViewportProps {
  objects: SceneViewObject[];
  busy: boolean;
  previewError: string | null;
  onPreviewStatus: (state: PreviewState, message?: string) => void;
  onSelectExample: (prompt: string) => void;
  onSelectObject?: (id: string | null, instanceIndex?: number) => void;
  /** Technical chip text shown top-left (schema/engine revision). */  schemaVersion?: string;
  /** Immediate dial-drag scale applied to the current mesh. */
  liveScale?: [number, number, number] | null;
  /** Drag selected object → world translation delta (mm). Draft only. */
  onMoveDelta?: (delta: [number, number, number]) => void;
  /** Drag began — parent can freeze other inputs. */
  onMoveStart?: () => void;
  /** Drag ended — bake drafts; parent may reset the drag group. */
  onMoveEnd?: () => void;
  /** When false, no TransformControls (busy / no selection). */
  canDrag?: boolean;
}

/** One object = one stable group. Selection never remounts StlModel
 *  (remount disposed geometry and blanked the well). TransformControls
 *  attaches to this group only while the object is selected. */
function SelectableObject({
  object,
  canDrag,
  onMoveDelta,
  onMoveStart,
  onMoveEnd,
  onGeometry,
  onPreviewStatus,
  onSelectObject,
  liveScale,
  onOrbitEnabledChange,
}: {
  object: SceneViewObject;
  canDrag: boolean;
  onMoveDelta?: (delta: [number, number, number]) => void;
  onMoveStart?: () => void;
  onMoveEnd?: () => void;
  onGeometry: () => void;
  onPreviewStatus: (state: PreviewState, message?: string) => void;
  onSelectObject?: (id: string | null) => void;
  liveScale?: [number, number, number] | null;
  onOrbitEnabledChange?: (enabled: boolean) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const dragRef = useRef(false);
  const [groupNode, setGroupNode] = useState<THREE.Group | null>(null);
  const showGizmo = canDrag && object.selected && object.url.length > 0;
  // -1 targets the component transform (single-pose parts / whole-component
  // move); >=0 targets one instance of a repeated component.
  const activeIndex = object.activeInstanceIndex ?? -1;
  const hasInstances = object.instances.length > 0;

  const setGroup = useCallback((node: THREE.Group | null) => {
    groupRef.current = node;
    setGroupNode(node);
  }, []);

  useEffect(() => {
    if (!showGizmo) {
      groupRef.current?.position.set(0, 0, 0);
    }
  }, [showGizmo]);

  // NOTE: TransformControls MUST stay a sibling of the group it drives.
  // drei renders its gizmo helper as a child of wherever this element
  // sits; nesting it inside the controlled group feeds the gizmo back
  // into its own transform math and locks the render loop on select.
  return (
    <>
      {hasInstances ? (
        /* Repeated component: one group per instance so a single screw can be
         * dragged without dragging its siblings. The gizmo attaches to the
         * active instance's group only. */
        <>
          {object.instances.map((pose, index) => (
            <group
              key={`${object.id}:${index}`}
              ref={
                index === activeIndex
                  ? (node: THREE.Group | null) => {
                      if (groupRef.current !== node) {
                        groupRef.current = node;
                        setGroupNode(node);
                      }
                    }
                  : undefined
              }
            >
              <StlModel
                url={object.url}
                onStatus={onPreviewStatus}
                onGeometry={onGeometry}
                scale={liveScale}
                position={pose.position}
                rotationDeg={pose.rotation}
                recenter={object.recenter}
                selected={object.selected && index === activeIndex}
                objectId={object.id}
                instanceIndex={index}
                onSelect={onSelectObject}
              />
            </group>
          ))}
        </>
      ) : (
        <group ref={setGroup}>
          <StlModel
            url={object.url}
            onStatus={onPreviewStatus}
            onGeometry={onGeometry}
            scale={liveScale}
            position={object.position}
            rotationDeg={object.rotation}
            recenter={object.recenter}
            selected={object.selected}
            objectId={object.id}
            instanceIndex={-1}
            onSelect={onSelectObject}
          />
        </group>
      )}

      {showGizmo && groupNode ? (
        <TransformControls
          object={groupNode}
          mode="translate"
          size={0.85}
          onMouseDown={() => {
            dragRef.current = true;
            onOrbitEnabledChange?.(false);
            onMoveStart?.();
          }}
          onMouseUp={() => {
            const g = groupRef.current;
            const delta: [number, number, number] = g
              ? [g.position.x, g.position.y, g.position.z]
              : [0, 0, 0];
            dragRef.current = false;
            onOrbitEnabledChange?.(true);
            // Commit the final gizmo delta while it is still non-zero, then
            // release the group. The parent bakes the new absolute pose into
            // the draft, so the mesh stays where it was dropped.
            if (delta[0] !== 0 || delta[1] !== 0 || delta[2] !== 0) {
              onMoveDelta?.(delta);
            }
            groupNode.position.set(0, 0, 0);
            onMoveEnd?.();
          }}
          onObjectChange={() => {
            if (!dragRef.current || !onMoveDelta) return;
            const g = groupRef.current;
            if (!g) return;
            onMoveDelta([g.position.x, g.position.y, g.position.z]);
          }}
        />
      ) : null}
    </>
  );
}

function DragGroup({
  objects,
  canDrag,
  onMoveDelta,
  onMoveStart,
  onMoveEnd,
  onGeometry,
  onPreviewStatus,
  onSelectObject,
  liveScale,
  contentRev,
  resetSignal,
  floorY,
  hasContent,
  onOrbitEnabledChange,
}: {
  objects: SceneViewObject[];
  canDrag: boolean;
  onMoveDelta?: (delta: [number, number, number]) => void;
  onMoveStart?: () => void;
  onMoveEnd?: () => void;
  onGeometry: () => void;
  onPreviewStatus: (state: PreviewState, message?: string) => void;
  onSelectObject?: (id: string | null) => void;
  liveScale?: [number, number, number] | null;
  contentRev: number;
  resetSignal: number;
  floorY: (y: number) => void;
  hasContent: boolean;
  onOrbitEnabledChange?: (enabled: boolean) => void;
}) {
  const [outerNode, setOuterNode] = useState<THREE.Group | null>(null);

  return (
    <group ref={setOuterNode}>
      {objects.map((object) => (
        <SelectableObject
          key={object.id}
          object={object}
          canDrag={canDrag}
          onMoveDelta={onMoveDelta}
          onMoveStart={onMoveStart}
          onMoveEnd={onMoveEnd}
          onGeometry={onGeometry}
          onPreviewStatus={onPreviewStatus}
          onSelectObject={onSelectObject}
          liveScale={liveScale}
          onOrbitEnabledChange={onOrbitEnabledChange}
        />
      ))}

      <FrameCamera
        group={outerNode}
        contentRev={contentRev}
        resetSignal={resetSignal}
        floorY={floorY}
        hasContent={hasContent}
      />
    </group>
  );
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
  onMoveStart,
  onMoveEnd,
  canDrag = false,
}: CadViewportProps) {
  const [contentRev, setContentRev] = useState(0);
  const [resetSignal, setResetSignal] = useState(0);
  const [floorY, setFloorY] = useState(0);
  const [orbitEnabled, setOrbitEnabled] = useState(true);
  const handleFloorY = useCallback((y: number) => setFloorY(y), []);
  const handleGeometry = useCallback(() => {
    setContentRev((n) => n + 1);
  }, []);
  const handleOrbitEnabled = useCallback((enabled: boolean) => {
    setOrbitEnabled(enabled);
  }, []);
  const visible = objects.filter((o) => o.visible && o.url);
  const showEmpty = visible.length === 0 && !busy && !previewError;

  return (
    <div className="viewport" data-testid="viewport">
      <Canvas
        camera={{ fov: 40, position: [180, 140, 180] }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <color attach="background" args={["#0e1014"]} />
        <ambientLight intensity={0.85} />
        <directionalLight position={[120, 180, 90]} intensity={1.35} />
        <directionalLight position={[-100, 60, -120]} intensity={0.45} />
        <Suspense fallback={null}>
          <group onPointerMissed={() => onSelectObject?.(null)}>
            <DragGroup
              objects={visible}
              canDrag={canDrag && !busy}
              onMoveDelta={onMoveDelta}
              onMoveStart={onMoveStart}
              onMoveEnd={onMoveEnd}
              onGeometry={handleGeometry}
              onPreviewStatus={onPreviewStatus}
              onSelectObject={onSelectObject}
              liveScale={liveScale}
              contentRev={contentRev}
              resetSignal={resetSignal}
              floorY={handleFloorY}
              hasContent={visible.length > 0}
              onOrbitEnabledChange={handleOrbitEnabled}
            />
          </group>
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

      <div className="viewport-toolbar">
        <span className="viewport-hint">
          drag&nbsp;·&nbsp;orbit&nbsp;&nbsp;&nbsp;wheel&nbsp;·&nbsp;zoom&nbsp;&nbsp;&nbsp;right-drag&nbsp;·&nbsp;pan
          {canDrag ? <>&nbsp;&nbsp;&nbsp;drag object&nbsp;·&nbsp;move</> : null}
        </span>
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
            STEP/STL downloads below remain authoritative.
          </p>
        </div>
      ) : null}
    </div>
  );
}
