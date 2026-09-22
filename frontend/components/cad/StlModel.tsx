"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { useThree } from "@react-three/fiber";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

export type PreviewState = "loading" | "ready" | "error";

interface StlModelProps {
  url: string;
  onStatus: (state: PreviewState, message?: string) => void;
  onGeometry: (geometry: THREE.BufferGeometry | null) => void;
  /** Immediate non-uniform scale for dial drags; identity/null when settled. */
  scale?: [number, number, number] | null;
  /** World pose in CAD millimetres / XYZ Euler degrees. */
  position?: [number, number, number];
  rotationDeg?: [number, number, number];
  /** Recenter the mesh on its bbox (single-part preview). Off for assemblies. */
  recenter?: boolean;
  selected?: boolean;
  objectId?: string;
  onSelect?: (id: string) => void;
}

/** Fetches an STL URL, parses it to BufferGeometry, centers it on the
 *  origin, and disposes everything on replacement/unmount (no leaks across
 *  many generations in one session). Rendering is the parent's job.
 *  The previous mesh stays visible until the next URL fully loads. */
const DEG = Math.PI / 180;

export function StlModel({
  url,
  onStatus,
  onGeometry,
  scale,
  position,
  rotationDeg,
  recenter = true,
  selected = false,
  objectId,
  onSelect,
}: StlModelProps) {
  const geometryRef = useRef<THREE.BufferGeometry | null>(null);
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    let cancelled = false;
    onStatus("loading");

    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`STL download failed (HTTP ${response.status}).`);
        }
        return response.arrayBuffer();
      })
      .then((buffer) => {
        const parsed = new STLLoader().parse(buffer);
        parsed.computeBoundingBox();
        if (recenter && parsed.boundingBox) {
          const center = parsed.boundingBox.getCenter(new THREE.Vector3());
          parsed.translate(-center.x, -center.y, -center.z);
          parsed.computeBoundingBox();
        }
        if (cancelled) {
          parsed.dispose();
          return;
        }
        geometryRef.current?.dispose();
        geometryRef.current = parsed;
        setGeometry(parsed);
        onGeometry(parsed);
        onStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        onStatus("error", err instanceof Error ? err.message : "STL parsing failed.");
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, recenter]);

  useEffect(() => {
    return () => {
      geometryRef.current?.dispose();
      geometryRef.current = null;
    };
  }, []);

  if (!geometry) return null;
  const rx = (rotationDeg?.[0] ?? 0) * DEG;
  const ry = (rotationDeg?.[1] ?? 0) * DEG;
  const rz = (rotationDeg?.[2] ?? 0) * DEG;
  return (
    <mesh
      geometry={geometry}
      scale={scale ?? [1, 1, 1]}
      position={position ?? [0, 0, 0]}
      rotation={[rx, ry, rz]}
      onClick={(event) => {
        if (!objectId || !onSelect) return;
        event.stopPropagation();
        onSelect(objectId);
      }}
    >
      <meshStandardMaterial
        color={selected ? "#5c7ae8" : "#8a8d85"}
        metalness={0.3}
        roughness={0.5}
        emissive={selected ? "#1c3fa8" : "#000000"}
        emissiveIntensity={selected ? 0.35 : 0}
      />
    </mesh>
  );
}

interface FrameCameraProps {
  group: THREE.Object3D | null;
  contentRev: number;
  resetSignal: number;
  floorY: (y: number) => void;
  hasContent: boolean;
}

/** Frames any model size: distance derives from the bounding box, so a
 *  10 mm sphere and a 500 mm box both fill the viewport usefully.
 *  Reframes only on reset, first load, or a large size change — never on
 *  every parametric geometry swap (keeps the user's view stable). */
export function FrameCamera({
  group,
  contentRev,
  resetSignal,
  floorY,
  hasContent,
}: FrameCameraProps) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as {
    target: THREE.Vector3;
    update: () => void;
  } | null;
  const lastFramedRef = useRef<number | null>(null);
  const hadGeometryRef = useRef(false);

  /* eslint-disable react-hooks/immutability -- R3F cameras/controls are mutated by design */
  const measure = useCallback((): { maxDim: number; minY: number } | null => {
    if (!group || !hasContent) return null;
    const box = new THREE.Box3().setFromObject(group);
    if (box.isEmpty()) return null;
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);
    return { maxDim, minY: box.min.y };
  }, [group, hasContent]);

  const frame = useCallback(() => {
    const measured = measure();
    if (!measured) return;
    const { maxDim, minY } = measured;
    const perspective = camera as THREE.PerspectiveCamera;
    const fov = ((perspective.fov || 40) * Math.PI) / 180;
    const distance = ((maxDim / 2) / Math.tan(fov / 2)) * 1.6;
    const direction = new THREE.Vector3(1, 0.62, 1).normalize();
    camera.position.copy(direction.multiplyScalar(distance));
    camera.near = Math.max(distance / 1000, 0.1);
    camera.far = Math.max(distance * 20, 1000);
    camera.updateProjectionMatrix();
    controls?.target.set(0, 0, 0);
    controls?.update();
    lastFramedRef.current = maxDim;
    floorY(minY);
  }, [measure, camera, controls, floorY]);

  useEffect(() => {
    if (!hasContent) {
      hadGeometryRef.current = false;
      lastFramedRef.current = null;
      return;
    }
    const measured = measure();
    if (!measured) return;
    floorY(measured.minY);
    const firstLoad = !hadGeometryRef.current;
    hadGeometryRef.current = true;
    const last = lastFramedRef.current;
    const largeChange =
      last !== null && (measured.maxDim > last * 1.5 || last > measured.maxDim * 1.5);
    if (firstLoad || largeChange) {
      frame();
    }
  }, [contentRev, hasContent, measure, frame, floorY]);

  useEffect(() => {
    if (resetSignal > 0) frame();
  }, [resetSignal, frame]);
  /* eslint-enable react-hooks/immutability */

  return null;
}
