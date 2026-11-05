/** Minimal API client for the cgen backend. No secrets live here —
 *  the browser only ever sends a prompt and receives files/metadata.
 */
import type {
  BackendHealth,
  ComponentsCatalog,
  GenerateResponse,
  ParamValue,
} from "@/types/api";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/+$/, "");

export const MAX_PROMPT_LENGTH = 2000;

/**
 * Render's free tier stops the service after ~15 minutes idle, and the first
 * request afterwards is either held until the instance boots, answered with a
 * proxy 502/503, or refused outright. Measured cold starts have exceeded 60s,
 * so both failure shapes are retried on a ~2 minute budget and opening a saved
 * workspace re-mints its files instead of failing with an error the user
 * cannot do anything about. An aborted request is never retried.
 */
const WAKE_RETRY_DELAYS_MS = [
  1000, 2500, 5000, 10000, 15000, 20000, 30000, 30000,
];

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Gateway codes Render's proxy returns while the instance boots. The API
 * itself only ever answers 502 with a JSON `detail` (an AI-provider failure),
 * so the content type distinguishes "still waking" from "really failed".
 */
const WAKE_GATEWAY_STATUSES = new Set([502, 503, 504]);

function isProxyColdStart(response: Response): boolean {
  if (!WAKE_GATEWAY_STATUSES.has(response.status)) return false;
  const contentType = response.headers.get("content-type") ?? "";
  return !contentType.includes("application/json");
}

/** fetch() that survives a sleeping backend; throws ApiError once it gives up. */
async function fetchWithWakeUrl(
  url: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<Response> {
  for (let attempt = 0; ; attempt += 1) {
    const canRetry = attempt < WAKE_RETRY_DELAYS_MS.length;
    try {
      const response = await fetch(url, { ...init, signal });
      // A booting instance answers through Render's proxy with 502/503 HTML,
      // not a network error, so those must be retried too.
      if (!isProxyColdStart(response) || !canRetry) return response;
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      const offline =
        typeof navigator !== "undefined" && navigator.onLine === false;
      if (offline || !canRetry) {
        throw new ApiError("Cannot reach the CAD service.", null);
      }
    }
    await sleep(WAKE_RETRY_DELAYS_MS[attempt], signal);
  }
}

function fetchWithWake(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<Response> {
  return fetchWithWakeUrl(`${API_BASE_URL}${path}`, init, signal);
}

/** Fetch a generated artifact (mesh bytes, download) with the same cold-start
 *  tolerance as API calls. Relative delivery paths resolve against the API. */
export function fetchArtifact(
  rawUrl: string,
  signal?: AbortSignal,
): Promise<Response> {
  return fetchWithWakeUrl(resolveFileUrl(rawUrl), { method: "GET" }, signal);
}

/** Supplies the current Firebase ID token, or null when signed out. */
type AuthTokenProvider = () => Promise<string | null>;

let authTokenProvider: AuthTokenProvider | null = null;

/**
 * Register the signed-in token provider (called once by AuthProvider).
 *
 * Kept as a hook rather than importing Firebase here so this module stays
 * testable without an initialized app and guests never need accounts.
 * Returns a cleanup that only clears its own provider.
 */
export function setAuthTokenProvider(
  provider: AuthTokenProvider | null,
): () => void {
  authTokenProvider = provider;
  return () => {
    if (authTokenProvider === provider) authTokenProvider = null;
  };
}

async function requestHeaders(json: boolean): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  if (json) headers["Content-Type"] = "application/json";
  if (authTokenProvider !== null) {
    let token: string | null = null;
    try {
      token = await authTokenProvider();
    } catch {
      // A token refresh failure must not block anonymous use; the backend
      // will answer 401 if auth is enforced, and the UI explains that.
      token = null;
    }
    if (token !== null && token.length > 0) {
      headers.Authorization = `Bearer ${token}`;
    }
  }
  return headers;
}

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
    value === "revolve" ||
    value === "sweep" ||
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

function isPartSpecification(spec: Record<string, unknown>): boolean {
  return (
    spec.document_type === "3d_part" &&
    typeof spec.name === "string" &&
    isRecord(spec.operation) &&
    isValidOperationType(spec.operation.type)
  );
}

function isAssemblySpecification(spec: Record<string, unknown>): boolean {
  return (
    spec.document_type === "3d_assembly" &&
    typeof spec.name === "string" &&
    Array.isArray(spec.components)
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
    typeof data.units !== "string" ||
    typeof data.generation_time_ms !== "number" ||
    !isRecord(files) ||
    !isFileMetadata(files.step) ||
    !isFileMetadata(files.stl)
  ) {
    throw new ApiError("Malformed API response.", null);
  }
  if (!isPartSpecification(spec) && !isAssemblySpecification(spec)) {
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
  return postJson("/generate", { prompt }, signal, "Generation");
}

export async function modifyPart(
  specification: Record<string, unknown>,
  instruction: string,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  return postJson(
    "/modify",
    { specification, instruction },
    signal,
    "Modification",
  );
}

export async function rebuildPart(
  baseSpecification: Record<string, unknown>,
  specification: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  return postJson(
    "/rebuild",
    { base_specification: baseSpecification, specification },
    signal,
    "Rebuild",
  );
}

export async function remintFiles(
  specification: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  return postJson("/remint", { specification }, signal, "Re-mint files");
}

async function postJson(
  path: string,
  body: unknown,
  signal: AbortSignal | undefined,
  failVerb: string,
): Promise<GenerateResponse> {
  let response: Response;
  try {
    response = await fetchWithWake(
      path,
      {
        method: "POST",
        headers: await requestHeaders(true),
        body: JSON.stringify(body),
      },
      signal,
    );
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (err instanceof ApiError) throw err;
    throw new ApiError("Cannot reach the CAD service.", null);
  }
  if (!response.ok) {
    const detail = await readDetail(response);
    throw new ApiError(
      `${failVerb} failed (HTTP ${response.status}).`,
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

export async function fetchComponentCatalog(
  signal?: AbortSignal,
): Promise<ComponentsCatalog> {
  let response: Response;
  try {
    response = await fetchWithWake("/components", { method: "GET" }, signal);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    if (err instanceof ApiError) throw err;
    throw new ApiError("Cannot reach the CAD service.", null);
  }
  if (!response.ok) {
    throw new ApiError(`Catalog failed (HTTP ${response.status}).`, response.status);
  }
  const data: unknown = await response.json();
  if (!isRecord(data) || !Array.isArray(data.components)) {
    throw new ApiError("Malformed catalog response.", null);
  }
  return data as unknown as ComponentsCatalog;
}

export async function addAssemblyComponent(
  specification: Record<string, unknown> | null,
  componentType: string,
  options: {
    parameters?: Record<string, ParamValue>;
    count?: number;
    name?: string;
  } = {},
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  return postJson(
    "/assembly/add",
    {
      specification,
      component_type: componentType,
      parameters: options.parameters,
      count: options.count ?? 1,
      name: options.name,
    },
    signal,
    "Add component",
  );
}

export async function removeAssemblyComponent(
  specification: Record<string, unknown>,
  componentId: string,
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  return postJson(
    "/assembly/remove",
    { specification, component_id: componentId },
    signal,
    "Remove component",
  );
}

export async function updateAssemblyComponent(
  specification: Record<string, unknown>,
  componentId: string,
  patch: {
    parameters?: Record<string, ParamValue>;
    transform?: { position: [number, number, number]; rotation: [number, number, number] };
    visible?: boolean;
    name?: string;
    instances?: Array<{
      position: [number, number, number];
      rotation: [number, number, number];
    }>;
  },
  signal?: AbortSignal,
): Promise<GenerateResponse> {
  return postJson(
    "/assembly/update",
    { specification, component_id: componentId, ...patch },
    signal,
    "Update component",
  );
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
        ? "Cannot reach the CAD service. It sleeps when idle, so the first request after a while can take up to two minutes — try once more."
        : err.status === 400
          ? "Check the description and try again."
          : err.status === 401
            ? "Sign in to use this CAD service, then try again."
            : err.status === 404
              ? "That download link expired. Re-run Generate or Rebuild for fresh files."
              : err.status === 422
                ? "The generated specification was invalid. Try rephrasing."
                : err.status === 502 || err.status === 503
                  ? "The CAD service is starting up or temporarily unavailable. Try again shortly."
                  : "The CAD service could not generate this part. Try simplifying the description.";
    return err.detail ? `${guidance} (${err.detail})` : guidance;
  }
  return "Something went wrong. Please try again.";
}
