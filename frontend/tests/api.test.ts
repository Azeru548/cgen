import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  checkBackendHealth,
  fetchArtifact,
  generatePart,
  humanizeApiError,
  parseGenerateResponse,
  rebuildPart,
  remintFiles,
  resolveFileUrl,
  setAuthTokenProvider,
} from "../lib/api";

const SHAFT_RESPONSE = {
  status: "completed",
  request_id: "abc123",
  specification: {
    document_type: "3d_part",
    units: "mm",
    name: "shaft_with_center_hole",
    operation: {
      type: "cut",
      base: { type: "cylinder", radius: 15, height: 120, through: false },
      tool: { type: "cylinder", radius: 7.5, height: 120, through: true },
    },
  },
  units: "mm",
  generation_time_ms: 987,
  files: {
    step: {
      format: "step",
      filename: "shaft.step",
      bytes: 9338,
      download_url: "/download/TOK?format=step",
    },
    stl: {
      format: "stl",
      filename: "shaft.stl",
      bytes: 50484,
      download_url: "/download/TOK?format=stl",
    },
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(SHAFT_RESPONSE)),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setAuthTokenProvider(null);
});

describe("generatePart", () => {
  it("posts the prompt as JSON to POST /generate", async () => {
    await generatePart("Create a shaft.");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/generate$/);
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body as string)).toEqual({ prompt: "Create a shaft." });
  });

  it("parses a successful response", async () => {
    const result = await generatePart("Create a shaft.");
    expect(result.status).toBe("completed");
    expect(result.specification.document_type).toBe("3d_part");
    if (result.specification.document_type === "3d_part") {
      expect(result.specification.operation.type).toBe("cut");
    }
    expect(result.files.step.bytes).toBe(9338);
  });

  it("throws ApiError with status and backend detail on 422", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "AI specification failed validation" }, 422),
    );
    const err = await generatePart("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as ApiError).detail).toContain("validation");
  });

  it("rides out a backend cold start and succeeds", async () => {
    vi.useFakeTimers();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(jsonResponse(SHAFT_RESPONSE));

    const pending = generatePart("x");
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result.status).toBe("completed");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("gives up after the cold-start budget with a null-status ApiError", async () => {
    vi.useFakeTimers();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));

    const pending = generatePart("x").catch((e: unknown) => e);
    await vi.runAllTimersAsync();
    const err = await pending;

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBeNull();
    expect(fetchMock.mock.calls.length).toBeGreaterThan(1);
  });

  it("does not retry an aborted request", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          const fail = () =>
            reject(new DOMException("Aborted", "AbortError"));
          const signal = init?.signal;
          if (signal?.aborted) {
            fail();
            return;
          }
          signal?.addEventListener("abort", fail);
        }),
    );
    const controller = new AbortController();
    const pending = generatePart("x", controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("retries a proxy 503 from a booting instance", async () => {
    vi.useFakeTimers();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        new Response("<html>waking</html>", {
          status: 503,
          headers: { "Content-Type": "text/html" },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(SHAFT_RESPONSE));

    const pending = generatePart("x");
    await vi.runAllTimersAsync();
    const result = await pending;

    expect(result.status).toBe("completed");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry a JSON 502 from the API itself", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "AI provider unavailable" }, 502),
    );

    const err = await generatePart("x").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(502);
    expect((err as ApiError).detail).toContain("AI provider");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rejects malformed success bodies", () => {
    expect(() =>
      parseGenerateResponse({ status: "completed", files: {} }),
    ).toThrow(ApiError);
    expect(() => parseGenerateResponse(null)).toThrow(ApiError);
    expect(() => parseGenerateResponse({ ...SHAFT_RESPONSE, files: null })).toThrow(
      ApiError,
    );
  });

  it("accepts an assembly specification at the contract boundary", () => {
    expect(() =>
      parseGenerateResponse({
        ...SHAFT_RESPONSE,
        specification: {
          document_type: "3d_assembly",
          units: "mm",
          name: "kit",
          schema_version: "4.0",
          components: [
            {
              id: "box_1",
              component_type: "box",
              name: "Box",
              parameters: { width: 10, depth: 10, height: 10 },
              transform: { position: [0, 0, 0], rotation: [0, 0, 0] },
              visible: true,
              instances: [],
              relationships: [],
            },
          ],
        },
        component_files: {
          box_1: SHAFT_RESPONSE.files,
        },
      }),
    ).not.toThrow();
  });

  it("accepts every schema operation type at the contract boundary", () => {
    for (const type of [
      "torus",
      "polygon_prism",
      "revolve",
      "sweep",
      "intersect",
      "part",
    ]) {
      expect(() =>
        parseGenerateResponse({
          ...SHAFT_RESPONSE,
          specification: {
            ...SHAFT_RESPONSE.specification,
            operation: { type },
          },
        }),
      ).not.toThrow();
    }
    for (const type of ["extrude", "loft", "sketch", "fillet"]) {
      expect(() =>
        parseGenerateResponse({
          ...SHAFT_RESPONSE,
          specification: {
            ...SHAFT_RESPONSE.specification,
            operation: { type },
          },
        }),
      ).toThrow(ApiError);
    }
  });
});

describe("rebuildPart", () => {
  const base = {
    document_type: "3d_part",
    units: "mm",
    name: "plate",
    operation: { type: "box", width: 100, depth: 60, height: 20 },
  };
  const edited = {
    document_type: "3d_part",
    units: "mm",
    name: "plate",
    operation: { type: "box", width: 120, depth: 60, height: 20 },
  };

  it("posts both specs as JSON to POST /rebuild without a prompt", async () => {
    await rebuildPart(base, edited);
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/rebuild$/);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.base_specification).toEqual(base);
    expect(body.specification).toEqual(edited);
    expect(body).not.toHaveProperty("prompt");
    expect(body).not.toHaveProperty("instruction");
  });

  it("parses a successful rebuild response", async () => {
    const rebuilt = {
      ...SHAFT_RESPONSE,
      request_id: "rebuild-1",
      specification: edited,
    };
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(jsonResponse(rebuilt));
    const result = await rebuildPart(base, edited);
    expect(result.request_id).toBe("rebuild-1");
    if (result.specification.document_type === "3d_part") {
      expect(result.specification.operation).toMatchObject({ width: 120 });
    } else {
      expect.fail("expected a 3d_part specification");
    }
  });

  it("surfaces guard rejections with status and detail", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Rebuild changes the operation structure" }, 422),
    );
    const err = await rebuildPart(base, edited).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as ApiError).detail).toContain("operation structure");
  });
});

describe("remintFiles", () => {
  it("posts the stored spec as JSON to POST /remint", async () => {
    const spec = SHAFT_RESPONSE.specification;
    await remintFiles(spec as unknown as Record<string, unknown>);
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/remint$/);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.specification).toEqual(spec);
    expect(body).not.toHaveProperty("prompt");
    expect(body).not.toHaveProperty("instruction");
  });
});

describe("auth token", () => {
  it("attaches the signed-in Firebase ID token as a bearer header", async () => {
    setAuthTokenProvider(async () => "id-token");
    await generatePart("Create a shaft.");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toMatchObject({ Authorization: "Bearer id-token" });
  });

  it("stays anonymous when the provider has no user", async () => {
    setAuthTokenProvider(async () => null);
    await generatePart("Create a shaft.");
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).not.toHaveProperty("Authorization");
  });

  it("does not block the request when token lookup fails", async () => {
    setAuthTokenProvider(async () => {
      throw new Error("refresh failed");
    });
    const result = await generatePart("Create a shaft.");
    expect(result.status).toBe("completed");
  });
});

describe("resolveFileUrl", () => {  it("joins relative backend URLs against the API base", () => {
    expect(resolveFileUrl("/download/TOK?format=step")).toMatch(
      /^https?:\/\/.+\/download\/TOK\?format=step$/,
    );
  });

  it("passes absolute URLs through", () => {
    expect(resolveFileUrl("https://cdn.example/x.stl")).toBe(
      "https://cdn.example/x.stl",
    );
  });

  it("resolves artifact delivery paths against the API base", () => {
    /* The viewer fetches these bytes to build the WebGL mesh, so they must
     * land on the API origin. A bare Byteship CDN URL would be blocked by
     * CORS and surface as "Preview unavailable / Failed to fetch". */
    const resolved = resolveFileUrl("/artifacts/req123/part.stl");
    expect(resolved).toMatch(/^https?:\/\/.+\/artifacts\/req123\/part\.stl$/);
    expect(resolved).not.toContain("byteship");
  });
});

describe("checkBackendHealth", () => {
  it("returns health on 200", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        service: "cgen-poc",
        cadquery_available: true,
        cadquery_version: "2.8.0",
      }),
    );
    const health = await checkBackendHealth();
    expect(health?.cadquery_available).toBe(true);
    expect(health?.cadquery_version).toBe("2.8.0");
  });

  it("returns null when unreachable", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockRejectedValueOnce(new TypeError("down"));
    expect(await checkBackendHealth()).toBeNull();
  });
});

describe("humanizeApiError", () => {
  it("maps statuses to guidance and surfaces safe backend detail", () => {
    expect(humanizeApiError(new ApiError("x", 400, "too long"))).toContain("too long");
    expect(humanizeApiError(new ApiError("x", 422))).toContain("rephrasing");
    expect(humanizeApiError(new ApiError("x", 404))).toContain("expired");
    expect(humanizeApiError(new ApiError("x", null))).toContain("sleeps when idle");
    expect(humanizeApiError(new Error("boom"))).toContain("try again");
  });
});

describe("fetchArtifact", () => {
  it("resolves delivery paths against the API and rides out a cold start", async () => {
    vi.useFakeTimers();
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1, 2, 3]), { status: 200 }),
      );

    const pending = fetchArtifact("/artifacts/req1/part.stl");
    await vi.runAllTimersAsync();
    const response = await pending;

    expect(response.status).toBe(200);
    expect((fetchMock.mock.calls[0] as [string])[0]).toMatch(
      /\/artifacts\/req1\/part\.stl$/,
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("returns a 404 straight away: a missing artifact is not a cold start", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Artifact not found." }, 404),
    );

    const response = await fetchArtifact("/artifacts/req1/part.stl");

    expect(response.status).toBe(404);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
