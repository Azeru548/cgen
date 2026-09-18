import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  checkBackendHealth,
  generatePart,
  humanizeApiError,
  parseGenerateResponse,
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
    expect(result.specification.operation.type).toBe("cut");
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
