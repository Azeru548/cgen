"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { useThree } from "@react-three/fiber";
import { Edges } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ApiError, fetchArtifact } from "@/lib/api";
import { DEFAULT_MATERIAL_ID, materialById, type MaterialId } from "@/lib/materials";

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
  /** Index within the component's instance list; -1 for single-pose parts. */
  instanceIndex?: number;
  onSelect?: (id: string, instanceIndex: number, additive: boolean) => void;
  /** Display-only surface preset; never affects the exported geometry. */
  material?: MaterialId;
  /** Clicks report a hit point instead of selecting (measure tool). */
  measure?: boolean;
  onMeasure?: (point: THREE.Vector3) => void;
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
  instanceIndex = -1,
  onSelect,
  material = DEFAULT_MATERIAL_ID,
  measure = false,
  onMeasure,
}: StlModelProps) {
  const geometryRef = useRef<THREE.BufferGeometry | null>(null);
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    let cancelled = false;
    onStatus("loading");

    // Mesh bytes live behind the API origin, so the fetch needs the same
    // cold-start tolerance as any other call: a sleeping instance answers
    // through Render's proxy with 502/503 rather than a network error.
    fetchArtifact(url)
      .then((response) => {
        if (!response.ok) {
          throw new ApiError(
            `STL download failed (HTTP ${response.status}).`,
            response.status,
          );
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
  // Stored rotations are the backend's XYZ Euler applied X first, then Y,
  // then Z (= Rz·Ry·Rx). three's "ZYX" order is that same composition; the
  // default "XYZ" order would show a different pose than the exported STEP.
  const euler: [number, number, number, "ZYX"] = [rx, ry, rz, "ZYX"];
  const surface = materialById(material);
  return (
    <mesh
      userData={{ cgenContent: true }}
      geometry={geometry}
      scale={scale ?? [1, 1, 1]}
      position={position ?? [0, 0, 0]}
      rotation={euler}
      onClick={(event) => {
        event.stopPropagation();
        if (measure) {
          onMeasure?.(event.point.clone());
          return;
        }
        if (!objectId || !onSelect) return;
        onSelect(
          objectId,
          instanceIndex,
          event.shiftKey || event.metaKey || event.ctrlKey,
        );
      }}
    >
      <meshStandardMaterial
        color={selected ? "#e04a55" : surface.color}
        metalness={surface.metalness}
        roughness={surface.roughness}
        emissive={selected ? "#8a1520" : "#000000"}
        emissiveIntensity={selected ? 0.35 : 0}
        envMapIntensity={1.15}
      />
      {/* Sharp feature edges only (threshold in degrees): this is what makes a
          machined part read as machined. Curved tessellation is never outlined
          because neighbouring facets differ by less than the threshold. */}
      {selected ? (
        <Edges threshold={28} color="#f4f6f8" scale={1.001} />
      ) : null}
    </mesh>
  );
}

export type ViewName = "iso" | "front" | "top" | "right";

/** Camera directions in **world** space (Y up). The scene is drawn inside a
 *  CAD→viewer wrapper, so CAD +Z is world +Y: `front` looks along CAD −Y and
 *  `top` looks down CAD −Z, exactly like a drawing's front/top views.
 *
 *  `iso` is the default three-quarter view: CAD +Y runs up the screen and CAD
 *  +Z (the face of a flat part) leans towards the camera, so a board or plate
 *  is read the way it sits on a desk — upright, in 3D, with the grid behind it.
 *
 *  These are world vectors. In CAD terms `iso` is (1, 0.62, 1) — the viewer's
 *  long-standing default — which is (1, 1, -0.62) here because the scene
 *  wrapper maps CAD (x, y, z) to world (x, z, -y). */
export const VIEW_DIRECTIONS: Record<ViewName, [number, number, number]> = {
  iso: [1, 1, -0.62],
  front: [0, 0, 1],
  top: [0, 1, 0],
  right: [1, 0, 0],
};

/** Screen-up per view, in world space. Views that look down the CAD Z axis need
 *  CAD +Y up the screen; straight-down views would degenerate, so they roll. */
export const VIEW_UP: Record<ViewName, [number, number, number]> = {
  iso: [0, 0, -1],
  front: [0, 1, 0],
  top: [0, 0, -1],
  right: [0, 1, 0],
};

/** Camera distance as a multiple of the fitting distance. Above 1 the part
 *  sits back in the frame with air and grid around it instead of filling the
 *  well edge to edge. */
const FRAME_BREATHING_ROOM = 1.9;

interface FrameCameraProps {
  group: THREE.Object3D | null;
  contentRev: number;
  resetSignal: number;
  floorY: (y: number) => void;
  hasContent: boolean;
  /** Largest bounding-box dimension, for size-relative scene effects. */
  onScale?: (maxDim: number) => void;
  /** One-shot standard-view request; `id` re-triggers the same view. */
  viewRequest?: { id: number; view: ViewName } | null;
  /** Perspective or orthographic; a swap re-fits the new camera once. */
  projection?: "persp" | "ortho";
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
  onScale,
  viewRequest = null,
  projection = "persp",
}: FrameCameraProps) {
  const camera = useThree((s) => s.camera);
  // Read the canvas size on demand: the framing must not depend on a resize,
  // or every layout change silently re-aims the camera the user just orbited.
  const getState = useThree((s) => s.get);
  const controls = useThree((s) => s.controls) as unknown as {
    target: THREE.Vector3;
    update: () => void;
  } | null;
  const lastFramedRef = useRef<number | null>(null);
  const hadGeometryRef = useRef(false);
  const viewRef = useRef<ViewName>("iso");

  /* eslint-disable react-hooks/immutability -- R3F cameras/controls are mutated by design */
  const measure = useCallback((): {
    maxDim: number;
    minY: number;
    centre: [number, number, number];
  } | null => {
    if (!group || !hasContent) return null;
    /* Measure only CAD content. TransformControls' gizmo is a sibling
     * object in the same group and is sized to the camera distance —
     * including it throws the camera miles away on every reframe. */
    const box = new THREE.Box3();
    group.traverse((node) => {
      if (node.userData?.cgenContent === true) box.expandByObject(node);
    });
    if (box.isEmpty()) return null;
    const dim = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    return {
      maxDim: Math.max(dim.x, dim.y, dim.z, 1),
      minY: box.min.y,
      centre: [centre.x, centre.y, centre.z],
    };
  }, [group, hasContent]);

  /* Places whichever camera is current. The toolbar can swap perspective for
   * orthographic, and both have to frame the same box on the same target. */
  const place = useCallback(
    (view: ViewName, maxDim: number, centre: [number, number, number]) => {
      const target = new THREE.Vector3(...centre);
      const direction = new THREE.Vector3(...VIEW_DIRECTIONS[view]).normalize();
      const { width, height } = getState().size;
      const ortho = camera as THREE.OrthographicCamera;
      if (ortho.isOrthographicCamera) {
        // The ortho frustum is in pixels, so `zoom` is pixels-per-mm.
        const pixels = Math.max(Math.min(width, height), 1);
        ortho.zoom = pixels / (maxDim * 1.7);
        ortho.near = -maxDim * 20;
        ortho.far = maxDim * 40;
        ortho.updateProjectionMatrix();
        camera.position.copy(target.clone().addScaledVector(direction, maxDim * 3));
      } else {
        const perspective = camera as THREE.PerspectiveCamera;
        const fov = ((perspective.fov || 40) * Math.PI) / 180;
        const distance =
          (maxDim / 2 / Math.tan(fov / 2)) * FRAME_BREATHING_ROOM;
        perspective.near = Math.max(distance / 1000, 0.1);
        perspective.far = Math.max(distance * 20, 1000);
        perspective.updateProjectionMatrix();
        camera.position.copy(target.clone().addScaledVector(direction, distance));
      }
      camera.up.set(...VIEW_UP[view]);
      camera.lookAt(target);
      controls?.target.copy(target);
      controls?.update();
      viewRef.current = view;
    },
    [camera, controls, getState],
  );

  const frame = useCallback(() => {
    const measured = measure();
    if (!measured) return;
    onScale?.(measured.maxDim);
    place("iso", measured.maxDim, measured.centre);
    lastFramedRef.current = measured.maxDim;
    floorY(measured.minY);
  }, [measure, place, floorY, onScale]);

  useEffect(() => {
    if (!hasContent) {
      hadGeometryRef.current = false;
      lastFramedRef.current = null;
      return;
    }
    const measured = measure();
    if (!measured) return;
    floorY(measured.minY);
    onScale?.(measured.maxDim);
    const firstLoad = !hadGeometryRef.current;
    hadGeometryRef.current = true;
    const last = lastFramedRef.current;
    const largeChange =
      last !== null && (measured.maxDim > last * 1.5 || last > measured.maxDim * 1.5);
    if (firstLoad || largeChange) {
      frame();
    }
  }, [contentRev, hasContent, measure, frame, floorY, onScale]);

  useEffect(() => {
    if (resetSignal > 0) frame();
  }, [resetSignal, frame]);

  // Front / Top / Right / Iso from the viewport toolbar.
  useEffect(() => {
    if (!viewRequest) return;
    const measured = measure();
    if (!measured) return;
    place(viewRequest.view, measured.maxDim, measured.centre);
  }, [viewRequest, measure, place]);

  // Projection swap (perspective <-> orthographic): fit the new camera once.
  // Keyed on the requested projection, not on the camera object, so a re-render
  // can never re-aim a camera the user has orbited.
  const placedProjectionRef = useRef<"persp" | "ortho">(projection);
  useEffect(() => {
    if (placedProjectionRef.current === projection) return;
    placedProjectionRef.current = projection;
    if (!hasContent) return;
    const measured = measure();
    if (!measured) return;
    place(viewRef.current, measured.maxDim, measured.centre);
  }, [projection, hasContent, measure, place]);
  /* eslint-enable react-hooks/immutability */

  return null;
}
