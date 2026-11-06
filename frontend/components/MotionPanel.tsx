"use client";

/**
 * MotionPanel - keyframe transport for the selected object.
 *
 * Animation is presentation metadata (schema 4.1 `animation`): it drives the
 * viewer only, never the exported STEP/STL. Keys capture the part's current
 * pose at the playhead; the viewer interpolates between them.
 */
import type { MotionTrack } from "@/types/api";

interface MotionPanelProps {
  /** Track for the selected object, or null when it has no motion yet. */
  track: MotionTrack | null;
  duration: number;
  playhead: number;
  playing: boolean;
  /** False for repeated components and locked parts. */
  canAnimate: boolean;
  busy: boolean;
  onPlay: () => void;
  onScrub: (time: number) => void;
  onAddKey: () => void;
  onRemoveKey: (index: number) => void;
  onToggleTrack: () => void;
  onDuration: (duration: number) => void;
}

export function MotionPanel({
  track,
  duration,
  playhead,
  playing,
  canAnimate,
  busy,
  onPlay,
  onScrub,
  onAddKey,
  onRemoveKey,
  onToggleTrack,
  onDuration,
}: MotionPanelProps) {
  return (
    <section className="inspector-section" data-testid="motion-panel">
      <div className="inspector-label">Motion</div>
      {!canAnimate ? (
        <p className="inspector-empty-inline">
          Animation drives a single part. Select one pose — repeated components
          are placed by their instance list instead.
        </p>
      ) : (
        <>
          <div className="motion-transport">
            <button
              type="button"
              className={`motion-play${playing ? " is-playing" : ""}`}
              onClick={onPlay}
              disabled={busy || track === null}
              aria-pressed={playing}
              title={track === null ? "Add a key first" : "Play or pause the scene"}
            >
              {playing ? "Pause" : "Play"}
            </button>
            <input
              type="range"
              className="motion-scrub"
              min={0}
              max={duration}
              step={0.05}
              value={Math.min(playhead, duration)}
              onChange={(event) => onScrub(Number(event.target.value))}
              disabled={busy || track === null}
              aria-label="Playhead"
            />
            <span className="motion-time mono">{playhead.toFixed(1)}s</span>
          </div>

          <div className="motion-actions">
            <label className="object-field motion-length">
              <span>Length (s)</span>
              <input
                className="object-input mono"
                type="number"
                min={0.2}
                max={120}
                step={0.5}
                value={duration}
                onChange={(event) => onDuration(Number(event.target.value))}
                disabled={busy}
              />
            </label>
            <button
              type="button"
              className="object-quick-button motion-key-add"
              onClick={onAddKey}
              disabled={busy}
              title="Store this part's current pose at the playhead"
            >
              Key here
            </button>
            <button
              type="button"
              className="object-quick-button motion-key-remove"
              onClick={onToggleTrack}
              disabled={busy}
              title={
                track === null
                  ? "Start a motion track for this part"
                  : "Remove this part's motion track"
              }
            >
              {track === null ? "Animate" : "Clear"}
            </button>
          </div>

          {track === null ? (
            <p className="inspector-empty-inline">
              No motion yet. Animate starts a track at the part&apos;s pose.
            </p>
          ) : (
            <ul className="motion-keys" aria-label="Motion keys">
              {track.keys.map((key, index) => (
                <li key={`${key.t}-${index}`} className="motion-key">
                  <button
                    type="button"
                    className="motion-key-time"
                    onClick={() => onScrub(key.t)}
                    title="Move the playhead to this key"
                  >
                    {key.t.toFixed(2)}s
                  </button>
                  <span className="motion-key-pose mono">
                    {key.position.map((value) => Math.round(value)).join(" / ")}
                  </span>
                  <button
                    type="button"
                    className="motion-key-delete"
                    onClick={() => onRemoveKey(index)}
                    disabled={busy}
                    aria-label={`Delete the key at ${key.t.toFixed(2)} seconds`}
                    title="Delete this key"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
