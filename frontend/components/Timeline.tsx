"use client";

/**
 * Timeline - the motion editor.
 *
 * One row per part, one diamond per keyframe, a playhead you can scrub and a
 * transport at the end. This is deliberately shaped like every other simple
 * animation tool (PowerPoint, Keynote, Blender's dope sheet): a list of parts
 * on the left, time running to the right, keys you can drag along a track.
 *
 * Animation stays presentation metadata (schema 4.1 `animation`): it drives the
 * viewer only and never the exported STEP/STL.
 */
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { MotionTrack } from "@/types/api";

export interface TimelineRow {
  id: string;
  name: string;
  /** Track for this part, or null when it is not animated yet. */
  track: MotionTrack | null;
  /** Repeated components and locked parts cannot carry a track. */
  animatable: boolean;
}

interface TimelineProps {
  rows: TimelineRow[];
  selectedId: string | null;
  duration: number;
  playhead: number;
  playing: boolean;
  busy: boolean;
  onTogglePlay: () => void;
  onStop: () => void;
  onScrub: (time: number) => void;
  onDuration: (seconds: number) => void;
  onSelect: (id: string) => void;
  /** Record the part's current pose at the playhead. */
  onAddKey: (id: string) => void;
  onRemoveKey: (id: string, index: number) => void;
  onMoveKey: (id: string, index: number, time: number) => void;
  onClearTrack: (id: string) => void;
}

const TICK_STEPS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60];

function tickStep(duration: number): number {
  const target = duration / 8;
  return TICK_STEPS.find((step) => step >= target) ?? 60;
}

function formatTick(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? `${rounded}s` : `${rounded.toFixed(2)}s`;
}

interface KeyDrag {
  id: string;
  index: number;
  startTime: number;
  time: number;
  moved: boolean;
}

export function Timeline({
  rows,
  selectedId,
  duration,
  playhead,
  playing,
  busy,
  onTogglePlay,
  onStop,
  onScrub,
  onDuration,
  onSelect,
  onAddKey,
  onRemoveKey,
  onMoveKey,
  onClearTrack,
}: TimelineProps) {
  const lanesRef = useRef<HTMLDivElement>(null);
  const [dragKey, setDragKey] = useState<KeyDrag | null>(null);
  const [seeking, setSeeking] = useState(false);

  const span = Math.max(duration, 0.2);
  const hasMotion = rows.some((row) => row.track !== null);
  const selectedRow = rows.find((row) => row.id === selectedId) ?? null;

  const ticks = useMemo(() => {
    const step = tickStep(span);
    const out: number[] = [];
    for (let value = 0; value <= span + 1e-6; value += step) {
      out.push(Math.round(value * 1000) / 1000);
    }
    return out;
  }, [span]);

  const percent = useCallback(
    (time: number) => `${Math.min(Math.max(time / span, 0), 1) * 100}%`,
    [span],
  );

  /** Time under a viewport x coordinate, clamped to the timeline. */
  const timeFromClientX = useCallback(
    (clientX: number) => {
      const el = lanesRef.current;
      if (el === null) return 0;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0) return 0;
      const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
      return Math.round((x / rect.width) * span * 100) / 100;
    },
    [span],
  );

  const handleRulerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      setSeeking(true);
      onScrub(timeFromClientX(event.clientX));
    },
    [onScrub, timeFromClientX],
  );

  const handleLaneDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>, id: string) => {
      onSelect(id);
      onScrub(timeFromClientX(event.clientX));
    },
    [onScrub, onSelect, timeFromClientX],
  );

  const startKeyDrag = useCallback(
    (
      event: ReactPointerEvent<HTMLButtonElement>,
      id: string,
      index: number,
      time: number,
    ) => {
      event.stopPropagation();
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragKey({ id, index, startTime: time, time, moved: false });
    },
    [],
  );

  const moveKeyDrag = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>, id: string, index: number) => {
      const time = timeFromClientX(event.clientX);
      setDragKey((current) => {
        if (current === null || current.id !== id || current.index !== index) {
          return current;
        }
        return {
          ...current,
          time,
          moved: current.moved || Math.abs(time - current.startTime) > 0.02,
        };
      });
    },
    [timeFromClientX],
  );

  const endKeyDrag = useCallback(
    (id: string, index: number) => {
      const current = dragKey;
      setDragKey(null);
      if (current === null || current.id !== id || current.index !== index) return;
      if (current.moved) {
        onMoveKey(id, index, current.time);
        onScrub(current.time);
        return;
      }
      // A click on a diamond is a jump to that key.
      onSelect(id);
      onScrub(current.startTime);
    },
    [dragKey, onMoveKey, onScrub, onSelect],
  );

  return (
    <section
      className="timeline"
      data-testid="timeline"
      aria-label="Motion timeline"
    >
      <div className="timeline-bar">
        <div className="timeline-transport">
          <button
            type="button"
            className="timeline-btn"
            onClick={onStop}
            disabled={busy}
            title="Jump back to the start"
            aria-label="Jump back to the start"
          >
            &#9198;
          </button>
          <button
            type="button"
            className={`timeline-btn timeline-play${playing ? " is-playing" : ""}`}
            onClick={onTogglePlay}
            disabled={busy || !hasMotion}
            aria-pressed={playing}
            title={
              hasMotion
                ? "Play or pause every animated part"
                : "Add a key to a part first"
            }
          >
            {playing ? "Pause" : "Play"}
          </button>
          <span className="timeline-clock mono">
            {playhead.toFixed(2)} / {span.toFixed(2)} s
          </span>
        </div>

        <label className="timeline-length">
          <span>Length</span>
          <input
            className="object-input mono"
            type="number"
            min={0.2}
            max={120}
            step={0.5}
            value={duration}
            onChange={(event) => onDuration(Number(event.target.value))}
            disabled={busy}
            aria-label="Timeline length in seconds"
          />
          <span className="timeline-unit">s</span>
        </label>

        <p className="timeline-help">
          {rows.length === 0
            ? "Nothing to animate yet — add parts from the library."
            : selectedRow === null
              ? "Pick a part, give it a pose, then press Key here."
              : selectedRow.track === null
                ? "Press + Key to record this part's pose at the playhead."
                : "Move the part in the viewport (or edit the inspector) to key it here. Drag a diamond to retime, double-click to delete."}
        </p>
      </div>

      <div className="timeline-body">
        <div className="timeline-gutter">
          <div className="timeline-gutter-head">
            <span>Parts</span>
            <span className="timeline-gutter-meta">
              {rows.filter((row) => row.track !== null).length} animated
            </span>
          </div>
          {rows.map((row) => (
            <div
              key={row.id}
              className={`timeline-name${row.id === selectedId ? " is-selected" : ""}`}
            >
              <button
                type="button"
                className="timeline-name-button"
                onClick={() => onSelect(row.id)}
                title={
                  row.animatable
                    ? `Select ${row.name}`
                    : `${row.name} cannot be animated (repeated or locked)`
                }
              >
                <span className="timeline-name-text">{row.name}</span>
                <span className="timeline-name-meta">
                  {row.track !== null
                    ? `${row.track.keys.length} key${row.track.keys.length === 1 ? "" : "s"}`
                    : row.animatable
                      ? ""
                      : "fixed"}
                </span>
              </button>
              {row.animatable ? (
                /* The key button has to survive the first key: a track is not a
                   one-shot, and losing the button is how a part gets stuck with
                   a single keyframe. */
                <button
                  type="button"
                  className="timeline-name-add"
                  onClick={() => onAddKey(row.id)}
                  disabled={busy}
                  title={`Record ${row.name}'s pose at the playhead`}
                  aria-label={`Key ${row.name} at the playhead`}
                >
                  + Key
                </button>
              ) : null}
              {row.track !== null ? (
                <button
                  type="button"
                  className="timeline-name-clear"
                  onClick={() => onClearTrack(row.id)}
                  disabled={busy}
                  title={`Remove ${row.name}'s motion`}
                  aria-label={`Remove ${row.name}'s motion`}
                >
                  &times;
                </button>
              ) : null}
            </div>
          ))}
        </div>

        <div className="timeline-lanes" ref={lanesRef}>
          <div
            className="timeline-ruler"
            onPointerDown={handleRulerDown}
            onPointerMove={(event) => {
              if (seeking) onScrub(timeFromClientX(event.clientX));
            }}
            onPointerUp={() => setSeeking(false)}
            onPointerCancel={() => setSeeking(false)}
            role="slider"
            tabIndex={0}
            aria-label="Playhead"
            aria-valuemin={0}
            aria-valuemax={span}
            aria-valuenow={Math.min(playhead, span)}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") {
                onScrub(Math.max(0, playhead - 0.1));
              } else if (event.key === "ArrowRight") {
                onScrub(Math.min(span, playhead + 0.1));
              }
            }}
          >
            {ticks.map((tick) => (
              <span
                key={tick}
                className="timeline-tick"
                style={{ left: percent(tick) }}
              >
                <i />
                {formatTick(tick)}
              </span>
            ))}
          </div>

          {rows.map((row) => {
            const dragging =
              dragKey !== null && dragKey.id === row.id ? dragKey : null;
            return (
              <div
                key={row.id}
                className={`timeline-lane${row.id === selectedId ? " is-selected" : ""}${row.track === null ? " is-empty" : ""}`}
                onPointerDown={(event) => handleLaneDown(event, row.id)}
              >
                {row.track?.keys.map((key, index) => {
                  const shownTime =
                    dragging !== null && dragging.index === index
                      ? dragging.time
                      : key.t;
                  const isDragged =
                    dragging !== null && dragging.index === index;
                  return (
                    <button
                      key={`${row.id}-${index}`}
                      type="button"
                      className={`timeline-key${isDragged ? " is-dragging" : ""}`}
                      style={{ left: percent(shownTime) }}
                      onPointerDown={(event) =>
                        startKeyDrag(event, row.id, index, key.t)
                      }
                      onPointerMove={(event) =>
                        moveKeyDrag(event, row.id, index)
                      }
                      onPointerUp={() => endKeyDrag(row.id, index)}
                      onPointerCancel={() => setDragKey(null)}
                      onDoubleClick={(event) => {
                        event.stopPropagation();
                        onRemoveKey(row.id, index);
                      }}
                      disabled={busy}
                      title={`${key.t.toFixed(2)}s — drag to retime, double-click to delete`}
                      aria-label={`Key at ${key.t.toFixed(2)} seconds`}
                    />
                  );
                })}
              </div>
            );
          })}

          <div
            className={`timeline-playhead${playing ? " is-playing" : ""}`}
            style={{ left: percent(playhead) }}
            aria-hidden="true"
          />
        </div>
      </div>
    </section>
  );
}
