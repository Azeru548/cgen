"use client";

/**
 * Boot screen — a short initialization moment that frames CGEN as an
 * engineering system coming online. The checklist rows are honest: they
 * reflect real readiness signals (schema version constant, WebGL renderer
 * availability, backend health probe already in flight on the page).
 *
 * Never blocks: the page transitions as soon as the checks resolve, with a
 * hard cap so a slow/offline backend cannot trap the user on this screen.
 * All animation is CSS and disabled under prefers-reduced-motion.
 */
import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { WalkingMachine } from "./WalkingMachine";

export interface BootChecks {
  /** Schema/version gate — always true when M6 code is running. */
  schema: boolean;
  /** WebGL is available for the 3D preview. */
  renderer: boolean;
  /** Backend answered the health probe (true = reachable; false = not yet). */
  engine: boolean;
}

const BOOT_STEP_MS = 220;
/** Hard cap: never hold the user on the boot screen longer than this. */
const BOOT_MAX_MS = 2600;

interface BootScreenProps {
  checks: BootChecks;
  /** Called when the boot sequence finishes so the parent can unmount it. */
  onDone: () => void;
}

export function BootScreen({ checks, onDone }: BootScreenProps) {
  const [revealed, setRevealed] = useState(0);
  const [exiting, setExiting] = useState(false);
  const [gone, setGone] = useState(false);
  const timers = useRef<number[]>([]);

  const allResolved =
    checks.schema && checks.renderer && checks.engine;

  useEffect(() => {
    const id = window.setInterval(() => {
      setRevealed((n) => Math.min(n + 1, 3));
    }, BOOT_STEP_MS);
    timers.current.push(id);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (revealed >= 3 && allResolved) {
      const id = window.setTimeout(() => setExiting(true), 240);
      timers.current.push(id);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [revealed, allResolved]);

  // Hard cap — boot must never trap the user.
  useEffect(() => {
    const id = window.setTimeout(() => setExiting(true), BOOT_MAX_MS);
    timers.current.push(id);
    return () => window.clearTimeout(id);
  }, []);

  // Fully unmount after the fade-out so the app beneath becomes interactive.
  useEffect(() => {
    if (!exiting) return undefined;
    const id = window.setTimeout(() => {
      setGone(true);
      onDone();
    }, 340);
    timers.current.push(id);
    return () => window.clearTimeout(id);
  }, [exiting, onDone]);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach((id) => window.clearInterval(id));
      pending.forEach((id) => window.clearTimeout(id));
    };
  }, []);

  if (gone) return null;

  const rows: Array<{ key: keyof BootChecks; label: string }> = [
    { key: "schema", label: "SCHEMA" },
    { key: "renderer", label: "RENDERER" },
    { key: "engine", label: "GEOMETRY" },
  ];

  return (
    <div
      className={`boot-screen${exiting ? " boot-screen-exit" : ""}`}
      role="status"
      aria-label="CGEN initializing"
      data-testid="boot-screen"
    >
      <Image
        src="/logo-removebg.png"
        alt="cgen"
        width={80}
        height={80}
        className="boot-logo"
        priority
      />
      <div className="boot-subtitle">CAD GENERATION ENGINE</div>

      <WalkingMachine />

      <div className="boot-status">INITIALIZING ENGINE</div>
      <ul className="boot-checklist">
        {rows.map((row, index) => {
          const done = index < revealed && checks[row.key];
          return (
            <li
              key={row.key}
              className={`boot-row${done ? " done" : ""}`}
              aria-hidden={index >= revealed ? "true" : undefined}
            >
              <span className="boot-mark" aria-hidden="true">
                {done ? "✓" : "·"}
              </span>
              {row.label}
            </li>
          );
        })}
      </ul>
      <div className="boot-footer">M6 / READY</div>
    </div>
  );
}
