"use client";

/** Landing hero: a real STL from this engine, bundled in `public/specimens`
 *  and loaded from the site itself — no backend, no cold start, no AI.
 *
 *  The drawings stay the default language of the panel, but the solid is the
 *  proof: these bytes came out of CadQuery, not a render. Hence a plain
 *  public file and a local fetch, never `fetchArtifact` (which resolves
 *  against the API origin).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

interface SpecimenModelProps {
  url: string;
  label: string;
  /** Called when the solid cannot be shown (no WebGL, failed fetch), so the
   *  panel can fall back to the drawing instead of loading forever. */
  onFail: () => void;
}

function Framed({
  url,
  onReady,
  onFail,
}: {
  url: string;
  onReady: () => void;
  onFail: () => void;
}) {
  const { camera } = useThree();
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);
  const held = useRef<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    fetch(url, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`specimen ${response.status}`);
        return response.arrayBuffer();
      })
      .then((buffer) => {
        const parsed = new STLLoader().parse(buffer);
        parsed.computeBoundingBox();
        parsed.computeVertexNormals();
        const box = parsed.boundingBox;
        if (box) {
          const centre = box.getCenter(new THREE.Vector3());
          parsed.translate(-centre.x, -centre.y, -centre.z);
          parsed.computeBoundingBox();
          // Frame every specimen from its own size so a 30mm shaft and a
          // 120mm enclosure both fill the well.
          const size = box.getSize(new THREE.Vector3());
          const radius = Math.max(size.x, size.y, size.z);
          camera.position.set(radius * 1.25, radius * 0.9, radius * 1.6);
          camera.lookAt(0, 0, 0);
          camera.updateProjectionMatrix();
        }
        if (cancelled) {
          parsed.dispose();
          return;
        }
        held.current?.dispose();
        held.current = parsed;
        setGeometry(parsed);
        onReady();
      })
      .catch(() => {
        if (!cancelled) onFail();
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(
    () => () => {
      held.current?.dispose();
      held.current = null;
    },
    [],
  );

  if (!geometry) return null;
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        color="#c7ccd4"
        metalness={0.35}
        roughness={0.42}
        flatShading={false}
      />
    </mesh>
  );
}

export function SpecimenModel({ url, label, onFail }: SpecimenModelProps) {
  const [ready, setReady] = useState(false);
  // Read once on the client: the canvas draws no DOM that differs between
  // server and client, so there is nothing to hydrate mismatched.
  const [calm, setCalm] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setCalm(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  /* A device without WebGL never fires onReady, and a dead canvas must not
     leave the panel on "loading solid…" forever. The callback is held in a ref
     so a re-render cannot restart the clock. */
  const failRef = useRef(onFail);
  useEffect(() => {
    failRef.current = onFail;
  }, [onFail]);
  useEffect(() => {
    if (ready) return;
    const timer = setTimeout(() => failRef.current(), 2500);
    return () => clearTimeout(timer);
  }, [ready]);

  const camera = useMemo(
    () => ({ fov: 34, position: [160, 120, 200] as [number, number, number] }),
    [],
  );

  return (
    <div className="lp-inst-solid" data-testid="specimen-model">
      <Canvas camera={camera} dpr={[1, 2]} gl={{ antialias: true }}>
        <color attach="background" args={["#101318"]} />
        <ambientLight intensity={0.75} />
        <directionalLight position={[120, 180, 140]} intensity={2.1} />
        <directionalLight position={[-160, -80, -120]} intensity={0.5} />
        <Framed url={url} onReady={() => setReady(true)} onFail={onFail} />
        <OrbitControls
          enableZoom={false}
          enablePan={false}
          enableDamping
          dampingFactor={0.08}
          autoRotate={!calm}
          autoRotateSpeed={0.9}
          minPolarAngle={Math.PI / 5}
          maxPolarAngle={Math.PI / 1.7}
        />
      </Canvas>
      {!ready ? <p className="lp-inst-solid-note mono">loading solid…</p> : null}
      <p className="lp-inst-solid-tag mono">{label}</p>
      <p className="lp-inst-solid-hint mono">drag to orbit · real STL from CadQuery</p>
    </div>
  );
}
