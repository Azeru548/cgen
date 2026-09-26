import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  checkBackendHealth,
  generatePart,
  humanizeApiError,
  parseGenerateResponse,
  rebuildPart,
  resolveFileUrl,
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
  vi.unstubAllGlobals();
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

  it("throws ApiError with null status on network failure", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const err = await generatePart("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBeNull();
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

  it("accepts M6 operation types at the contract boundary", () => {
    for (const type of ["torus", "polygon_prism", "intersect", "part"]) {
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
    for (const type of ["extrude", "revolve", "loft"]) {
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

describe("resolveFileUrl", () => {
  it("joins relative backend URLs against the API base", () => {
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
    expect(humanizeApiError(new ApiError("x", null))).toContain("connection");
    expect(humanizeApiError(new Error("boom"))).toContain("try again");
  });
});
