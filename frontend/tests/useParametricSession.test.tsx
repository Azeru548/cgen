import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PREVIEW_DEBOUNCE_MS, useParametricSession } from "../lib/useParametricSession";
import type { CadSpecification } from "../types/api";

const BASE: CadSpecification = {
  document_type: "3d_part",
  units: "mm",
  name: "plate",
  operation: { type: "box", width: 100, depth: 60, height: 20 },
};

function editedBox(width: number): CadSpecification {
  return {
    ...BASE,
    operation: { type: "box", width, depth: 60, height: 20 },
  };
}

function okResponse(spec: unknown, requestId: string): Response {
  return new Response(
    JSON.stringify({
      status: "completed",
      request_id: requestId,
      specification: spec,
      units: "mm",
      generation_time_ms: 5,
      files: {
        step: { format: "step", filename: "plate.step", bytes: 100, download_url: `/download/${requestId}?format=step` },
        stl: { format: "stl", filename: "plate.stl", bytes: 200, download_url: `/download/${requestId}?format=stl` },
      },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function errResponse(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface PendingFetch {
  promise: Promise<Response>;
  resolve: (r: Response) => void;
  signal: AbortSignal | undefined;
}

let pending: PendingFetch[];
let calls: number;

type FetchMock = { mock: { calls: Array<[string, { body?: string; signal?: AbortSignal }]> } };

function lastBodySpec(): Record<string, unknown> {
  const mocked = fetch as unknown as FetchMock;
  const last = mocked.mock.calls[mocked.mock.calls.length - 1];
  return (JSON.parse(last[1].body ?? "{}") as { specification: Record<string, unknown> }).specification;
}

async function settle(ms = PREVIEW_DEBOUNCE_MS + 50): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  pending = [];
  calls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init?: { signal?: AbortSignal }) => {
      calls += 1;
      let resolve!: (r: Response) => void;
      const promise = new Promise<Response>((res) => {
        resolve = res;
      });
      pending.push({ promise, resolve, signal: init?.signal });
      return promise;
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useParametricSession", () => {
  it("resolves a transient preview without committing anything", async () => {
    const { result } = renderHook(() => useParametricSession(BASE));
    act(() => {
      result.current.previewValue("build.width", 120);
    });
    await settle();
    pending[0].resolve(okResponse(lastBodySpec(), "prev-1"));
    await settle(0);
    expect(result.current.preview?.spec.document_type).toBe("3d_part");
    if (result.current.preview?.spec.document_type === "3d_part") {
      expect(result.current.preview.spec.operation).toMatchObject({ width: 120 });
    }
    expect(result.current.preview?.response.request_id).toBe("prev-1");
    expect(result.current.paramError).toBeNull();
    expect(calls).toBe(1);
  });

  it("commit reuses the matching preview: one fetch, one result", async () => {
    const { result } = renderHook(() => useParametricSession(BASE));
    act(() => {
      result.current.previewValue("build.width", 120);
    });
    await settle();
    pending[0].resolve(okResponse(lastBodySpec(), "prev-1"));
    await settle(0);
    let done: { summary: string } | null = null;
    await act(async () => {
      done = await result.current.commit();
    });
    expect(done).toMatchObject({ summary: "Adjusted width 100 → 120 mm" });
    expect(calls).toBe(1);
    // A repeated commit reuses the same preview — still no rebuild.
    await act(async () => {
      await result.current.commit();
    });
    expect(calls).toBe(1);
  });

  it("stale responses never overwrite a newer preview", async () => {
    const { result } = renderHook(() => useParametricSession(BASE));
    act(() => {
      result.current.previewValue("build.width", 110);
    });
    await settle();
    act(() => {
      result.current.previewValue("build.width", 120);
    });
    await settle();
    // Newer resolves first, older resolves last — older must lose.
    pending[1].resolve(okResponse(editedBox(120), "prev-2"));
    await settle(0);
    pending[0].resolve(okResponse(editedBox(110), "prev-1"));
    await settle(0);
    expect(result.current.preview?.spec.document_type).toBe("3d_part");
    if (result.current.preview?.spec.document_type === "3d_part") {
      expect(result.current.preview.spec.operation).toMatchObject({ width: 120 });
    }
    expect(result.current.preview?.response.request_id).toBe("prev-2");
  });

  it("aborts the superseded in-flight preview", async () => {
    const mocked = fetch as unknown as FetchMock;
    const { result } = renderHook(() => useParametricSession(BASE));
    act(() => {
      result.current.previewValue("build.width", 110);
    });
    await settle();
    act(() => {
      result.current.previewValue("build.width", 120);
    });
    await settle();
    expect(mocked.mock.calls[0][1].signal?.aborted).toBe(true);
    expect(mocked.mock.calls[1][1].signal?.aborted).toBe(false);
    pending[1].resolve(okResponse(editedBox(120), "prev-2"));
    await settle(0);
  });

  it("invalid rebuild keeps the last valid preview and reports", async () => {
    const { result } = renderHook(() => useParametricSession(BASE));
    act(() => {
      result.current.previewValue("build.width", 120);
    });
    await settle();
    pending[0].resolve(okResponse(lastBodySpec(), "prev-1"));
    await settle(0);
    act(() => {
      result.current.previewValue("build.width", 500);
    });
    await settle();
    pending[1].resolve(errResponse(422, "Rebuild changes the operation structure"));
    await settle(0);
    expect(result.current.paramError).toContain("Rebuild changes");
    // Last valid preview geometry is preserved, not cleared.
    expect(result.current.preview?.spec.document_type).toBe("3d_part");
    if (result.current.preview?.spec.document_type === "3d_part") {
      expect(result.current.preview.spec.operation).toMatchObject({ width: 120 });
    }
  });

  it("commit after further edits performs exactly one final rebuild", async () => {
    const { result } = renderHook(() => useParametricSession(BASE));
    act(() => {
      result.current.previewValue("build.width", 120);
    });
    await settle();
    pending[0].resolve(okResponse(lastBodySpec(), "prev-1"));
    await settle(0);
    act(() => {
      result.current.previewValue("build.width", 130);
    });
    // Commit before the debounce fires: timer cancelled, one final rebuild.
    const out: { done: { summary: string; response: { request_id: string } } | null } = {
      done: null,
    };
    await act(async () => {
      const started = result.current.commit();
      await vi.advanceTimersByTimeAsync(0);
      pending[pending.length - 1].resolve(okResponse(editedBox(130), "final-1"));
      out.done = await started;
    });
    expect(out.done?.response.request_id).toBe("final-1");
    expect(out.done?.summary).toBe("Adjusted width 100 → 130 mm");
    expect(calls).toBe(2);
  });
});
