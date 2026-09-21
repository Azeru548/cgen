/** Minimal API client for the cgen backend. No secrets live here —
 *  the browser only ever sends a prompt and receives files/metadata.
 */
import type { BackendHealth, GenerateResponse } from "@/types/api";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3000"
).replace(/\/+$/, "");

export const MAX_PROMPT_LENGTH = 2000;

export class ApiError extends Error {
  /** HTTP status, or null for network/unreachable/malformed failures. */
  readonly status: number | null;
  /** Safe backend detail message, if the API provided one. */
  readonly detail: string | null;

  constructor(message: string, status: number | null, detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isValidOperationType(value: unknown): boolean {
  return (
    value === "box" ||
    value === "cylinder" ||
    value === "cone" ||
    value === "sphere" ||
    value === "torus" ||
    value === "polygon_prism" ||
    value === "union" ||
    value === "cut" ||
    value === "intersect" ||
    value === "part"
  );
}

function isFileMetadata(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return (
    (value.format === "step" || value.format === "stl") &&
    typeof value.filename === "string" &&
    typeof value.bytes === "number" &&
    typeof value.download_url === "string"
  );
}

/** Runtime guard: reject malformed backend payloads before they reach UI state. */
export function parseGenerateResponse(data: unknown): GenerateResponse {
  if (!isRecord(data)) throw new ApiError("Malformed API response.", null);
  const spec = data.specification;
  const files = data.files;
  if (
    data.status !== "completed" ||
    typeof data.request_id !== "string" ||
    !isRecord(spec) ||
    typeof spec.name !== "string" ||
    !isRecord(spec.operation) ||
    !isValidOperationType(spec.operation.type) ||
    typeof data.units !== "string" ||
    typeof data.generation_time_ms !== "number" ||
    !isRecord(files) ||
    !isFileMetadata(files.step) ||
    !isFileMetadata(files.stl)
  ) {
    throw new ApiError("Malformed API response.", null);
  }
  return data as unknown as GenerateResponse;
}

async function readDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (isRecord(body) && typeof body.detail === "string") return body.detail;
    return null;
  } catch {
    return null;
  }
}

export async function generatePart(
  prompt: string,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Cannot reach the CAD service.", null);
  }
  if (!response.ok) {
    const detail = await readDetail(response);
    throw new ApiError(
      `Generation failed (HTTP ${response.status}).`,
      response.status,
      detail,
    );
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError("Malformed API response.", response.status);
  }
  return parseGenerateResponse(data);
}

export async function modifyPart(
  specification: Record<string, unknown>,
  instruction: string,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/modify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ specification, instruction }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Cannot reach the CAD service.", null);
  }
  if (!response.ok) {
    const detail = await readDetail(response);
    throw new ApiError(
      `Modification failed (HTTP ${response.status}).`,
      response.status,
      detail,
    );
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError("Malformed API response.", response.status);
  }
  return parseGenerateResponse(data);
}

export async function rebuildPart(
  baseSpecification: Record<string, unknown>,
  specification: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/rebuild`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_specification: baseSpecification,
        specification,
      }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Cannot reach the CAD service.", null);
  }
  if (!response.ok) {
    const detail = await readDetail(response);
    throw new ApiError(
      `Rebuild failed (HTTP ${response.status}).`,
      response.status,
      detail,
    );
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError("Malformed API response.", response.status);
  }
  return parseGenerateResponse(data);
}

export async function checkBackendHealth(): Promise<BackendHealth | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, { method: "GET" });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    if (!isRecord(data) || typeof data.status !== "string") return null;
    return {
      status: data.status,
      service: typeof data.service === "string" ? data.service : "",
      cadquery_available: data.cadquery_available === true,
      cadquery_version:
        typeof data.cadquery_version === "string" ? data.cadquery_version : null,
    };
  } catch {
    return null;
  }
}

/** Backend download URLs are relative — resolve against the API base. */
export function resolveFileUrl(downloadUrl: string): string {
  if (/^https?:\/\//i.test(downloadUrl)) return downloadUrl;
  const path = downloadUrl.startsWith("/") ? downloadUrl : `/${downloadUrl}`;
  return `${API_BASE_URL}${path}`;
}

/** Human-readable error text for the UI. Backend details are safe to show:
 *  the API never leaks secrets, paths, or tracebacks (verified M2/M4). */
export function humanizeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const guidance =
      err.status === null
        ? "Check your connection and that the CAD service is running."
        : err.status === 400
          ? "Check the description and try again."
          : err.status === 422
            ? "The generated specification was invalid. Try rephrasing."
            : "The CAD service could not generate this part. Try simplifying the description.";
    return err.detail ? `${guidance} (${err.detail})` : guidance;
  }
  return "Something went wrong. Please try again.";
}
