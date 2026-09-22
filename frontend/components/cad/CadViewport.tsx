"use client";

import { Suspense, useCallback, useState } from "react";
import * as THREE from "three";
import { Canvas } from "@react-three/fiber";
import {
  GizmoHelper,
  GizmoViewport,
  Grid,
  OrbitControls,
} from "@react-three/drei";
import { FrameCamera, StlModel, type PreviewState } from "./StlModel";
import { GenerationLoader } from "../GenerationLoader";

export const EXAMPLE_PROMPTS = [
  "Create a 100mm × 60mm × 30mm rectangular block.",
  "Create a 50mm diameter sphere.",
  "Create a 120mm shaft with a 15mm through-hole.",
];

interface CadViewportProps {
  stlUrl: string | null;
  busy: boolean;
  previewError: string | null;
  onPreviewStatus: (state: PreviewState, message?: string) => void;
  onSelectExample: (prompt: string) => void;
  /** Technical chip text shown top-left (schema/engine revision). */
  schemaVersion?: string;
  /** Immediate dial-drag scale applied to the current mesh. */
  liveScale?: [number, number, number] | null;
}

export function CadViewport({
  stlUrl,
  busy,
  previewError,
  onPreviewStatus,
  onSelectExample,
  schemaVersion,
  liveScale,
}: CadViewportProps) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);
  const [resetSignal, setResetSignal] = useState(0);
  const [floorY, setFloorY] = useState(0);
  const handleFloorY = useCallback((y: number) => setFloorY(y), []);
  const showEmpty = !stlUrl && !busy && !previewError;

  return (
    <div className="viewport" data-testid="viewport">
      <Canvas
        camera={{ fov: 40, position: [180, 140, 180] }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <color attach="background" args={["#171918"]} />
        <ambientLight intensity={0.85} />
        <directionalLight position={[120, 180, 90]} intensity={1.35} />
        <directionalLight position={[-100, 60, -120]} intensity={0.45} />
        <Suspense fallback={null}>
          {stlUrl ? (
            <StlModel
              url={stlUrl}
              onStatus={onPreviewStatus}
              onGeometry={setGeometry}
              scale={liveScale}
            />
          ) : null}
          <FrameCamera
            geometry={geometry}
            resetSignal={resetSignal}
            floorY={handleFloorY}
            scale={liveScale}
          />
          <Grid
            position={[0, floorY, 0]}
            args={[10, 10]}
            cellSize={10}
            cellThickness={0.6}
            cellColor="#3a3c38"
            sectionSize={50}
            sectionThickness={1}
            sectionColor="#4a4c46"
            fadeDistance={1400}
            fadeStrength={2}
            infiniteGrid
          />
        </Suspense>
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.12}
          minDistance={5}
          maxDistance={5000}
        />
        <GizmoHelper alignment="top-right" margin={[56, 56]}>
          <GizmoViewport
            axisColors={["#c0392b", "#198754", "#3157ff"]}
            labelColor="#faf9f5"
          />
        </GizmoHelper>
      </Canvas>

      {schemaVersion ? (
        <span className="viewport-tag">{schemaVersion}</span>
      ) : null}

      <div className="viewport-toolbar">
        <span className="viewport-hint">
          drag&nbsp;·&nbsp;orbit&nbsp;&nbsp;&nbsp;wheel&nbsp;·&nbsp;zoom&nbsp;&nbsp;&nbsp;right-drag&nbsp;·&nbsp;pan
        </span>
        <button
          type="button"
          className="viewport-reset"
          onClick={() => setResetSignal((s) => s + 1)}
          disabled={!geometry}
          aria-label="Reset view"
        >
          Reset view
        </button>
      </div>

      {showEmpty ? (
        <div className="viewport-overlay" data-testid="empty-state">
          <p className="overlay-title">Your CAD model will appear here</p>
          <p className="overlay-text">
            Describe a part below to generate your first model.
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
