/**
 * The viewer's expired-file revival contract.
 *
 * Real React via renderHook; what matters is when a re-mint is allowed:
 * only for a 404, only when the viewer is idle, and never more than once per
 * workspace — otherwise a broken bucket would append revisions forever.
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useExpiredFileRevival } from "../hooks/useExpiredFileRevival";

/** The message the mesh fetch produces for a dead artifact. */
const DEAD = "STL download failed (HTTP 404).";

interface Props {
  error: string | null;
  ready: boolean;
  workspace: string;
  revive: () => void;
}

function setup(overrides: Partial<Props> = {}) {
  const revive = vi.fn();
  const initialProps: Props = {
    error: null,
    ready: true,
    workspace: "ws-1",
    revive,
    ...overrides,
  };
  const view = renderHook(
    (props: Props) =>
      useExpiredFileRevival(
        props.error,
        props.ready,
        props.workspace,
        props.revive,
      ),
    { initialProps },
  );
  return { revive, view };
}

describe("useExpiredFileRevival", () => {
  it("does nothing while the viewer is healthy", () => {
    const { revive } = setup();
    expect(revive).not.toHaveBeenCalled();
  });

  it("does nothing for non-404 failures", () => {
    const { revive } = setup({ error: "Preview failed (HTTP 500)." });
    expect(revive).not.toHaveBeenCalled();
  });

  it("does nothing for transport errors without a status code", () => {
    const { revive } = setup({ error: "Could not reach the backend." });
    expect(revive).not.toHaveBeenCalled();
  });

  it("re-mints once when a saved revision's files are gone", () => {
    const { revive } = setup({ error: DEAD });
    expect(revive).toHaveBeenCalledTimes(1);
  });

  it("does not re-mint while another operation owns the viewer", () => {
    const { revive, view } = setup({ error: DEAD, ready: false });
    expect(revive).not.toHaveBeenCalled();

    view.rerender({
      error: DEAD,
      ready: true,
      workspace: "ws-1",
      revive,
    });
    expect(revive).toHaveBeenCalledTimes(1);
  });

  it("attempts at most once per workspace, even if the 404 persists", () => {
    const { revive, view } = setup({ error: DEAD });
    expect(revive).toHaveBeenCalledTimes(1);

    // A failed re-mint leaves the same error on screen; re-renders and a new
    // callback identity must not start a second attempt.
    const later = vi.fn();
    view.rerender({ error: DEAD, ready: true, workspace: "ws-1", revive: later });
    view.rerender({ error: null, ready: true, workspace: "ws-1", revive: later });
    view.rerender({ error: DEAD, ready: true, workspace: "ws-1", revive: later });

    expect(revive).toHaveBeenCalledTimes(1);
    expect(later).not.toHaveBeenCalled();
  });

  it("gives each workspace its own attempt", () => {
    const { revive, view } = setup({ error: DEAD });
    expect(revive).toHaveBeenCalledTimes(1);

    view.rerender({ error: DEAD, ready: true, workspace: "ws-2", revive });
    expect(revive).toHaveBeenCalledTimes(2);
  });
});
