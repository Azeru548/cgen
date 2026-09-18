"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { useThree } from "@react-three/fiber";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

export type PreviewState = "loading" | "ready" | "error";

interface StlModelProps {
  url: string;
  onStatus: (state: PreviewState, message?: string) => void;
  onGeometry: (geometry: THREE.BufferGeometry | null) => void;
}

/** Fetches an STL URL, parses it to BufferGeometry, centers it on the
 *  origin, and disposes everything on replacement/unmount (no leaks across
 *  many generations in one session). Rendering is the parent's job. */
export function StlModel({ url, onStatus, onGeometry }: StlModelProps) {
  const geometryRef = useRef<THREE.BufferGeometry | null>(null);
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    let cancelled = false;
    onStatus("loading");
    onGeometry(null);

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
        if (parsed.boundingBox) {
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
  }, [url]);

  useEffect(() => {
    return () => {
      geometryRef.current?.dispose();
      geometryRef.current = null;
    };
  }, []);

  if (!geometry) return null;
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial color="#4a4d47" metalness={0.35} roughness={0.45} />
    </mesh>
  );
}

interface FrameCameraProps {
  geometry: THREE.BufferGeometry | null;
  resetSignal: number;
  floorY: (y: number) => void;
}

/** Frames any model size: distance derives from the bounding box, so a
 *  10 mm sphere and a 500 mm box both fill the viewport usefully. */
export function FrameCamera({ geometry, resetSignal, floorY }: FrameCameraProps) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as {
    target: THREE.Vector3;
    update: () => void;
  } | null;

  useEffect(() => {
    if (!geometry) return;
    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    if (!box) return;
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 1);
    const perspective = camera as THREE.PerspectiveCamera;
    const fov = ((perspective.fov || 40) * Math.PI) / 180;
    const distance = ((maxDim / 2) / Math.tan(fov / 2)) * 1.6;
    const direction = new THREE.Vector3(1, 0.62, 1).normalize();
    /* eslint-disable react-hooks/immutability -- R3F cameras/controls are mutated by design */
    camera.position.copy(direction.multiplyScalar(distance));
    camera.near = Math.max(distance / 1000, 0.1);
    camera.far = Math.max(distance * 20, 1000);
    camera.updateProjectionMatrix();
    controls?.target.set(0, 0, 0);
    controls?.update();
    /* eslint-enable react-hooks/immutability */
    floorY(-size.y / 2);
  }, [geometry, resetSignal, camera, controls, floorY]);

  return null;
}
