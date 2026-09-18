"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BootScreen, type BootChecks } from "@/components/BootScreen";
import { CadViewport } from "@/components/cad/CadViewport";
import type { PreviewState } from "@/components/cad/StlModel";
import { Downloads } from "@/components/Downloads";
import { GeneratePanel } from "@/components/GeneratePanel";
import { GenerationLoader } from "@/components/GenerationLoader";
import { SpecPanel } from "@/components/SpecPanel";
import {
  checkBackendHealth,
  generatePart,
  humanizeApiError,
  resolveFileUrl,
  type ApiError,
} from "@/lib/api";
import type { BackendHealth, GenerateResponse } from "@/types/api";

type PageStatus = "idle" | "generating" | "ready" | "error";
type EngineState = "ready" | "processing" | "error" | "unknown";

const SCHEMA_VERSION = "M6 · SCHEMA 3.0";

function detectWebgl(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(
      canvas.getContext("webgl2") ??
        canvas.getContext("webgl") ??
        canvas.getContext("experimental-webgl"),
    );
  } catch {
    return false;
  }
}

export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState<PageStatus>("idle");
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [stlUrl, setStlUrl] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [booting, setBooting] = useState(true);
  const [bootChecks, setBootChecks] = useState<BootChecks>({
    schema: false,
    renderer: false,
    engine: false,
  });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    checkBackendHealth().then((info) => {
      if (cancelled) return;
      setHealth(info);
      setBootChecks({
        schema: true,
        renderer: detectWebgl(),
        engine: info !== null,
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleGenerate = useCallback(async () => {
    if (status === "generating") return;
    if (prompt.trim().length === 0) {
      setGenerateError("Describe the part first — the prompt is empty.");
      setStatus("error");
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("generating");
    setGenerateError(null);
    setPreviewError(null);
    try {
      const response = await generatePart(prompt.trim(), controller.signal);
      setResult(response);
      setStlUrl(resolveFileUrl(response.files.stl.download_url));
      setStatus("ready");
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setGenerateError(humanizeApiError(err as ApiError));
      setStatus("error");
    }
  }, [prompt, status]);

  const handlePreviewStatus = useCallback(
    (state: PreviewState, message?: string) => {
      if (state === "error") {
        setPreviewError(
          message ?? "The preview mesh could not be loaded. Downloads still work.",
        );
      } else if (state === "loading") {
        setPreviewError(null);
      }
    },
    [],
  );

  const handleBootDone = useCallback(() => setBooting(false), []);

  const busy = status === "generating";

  const engineState: EngineState = busy
    ? "processing"
    : status === "error"
      ? "error"
      : health === null
        ? "unknown"
        : health.cadquery_available
          ? "ready"
          : "error";

  const engineLabel = useMemo(() => {
    switch (engineState) {
      case "ready":
        return "ENGINE READY";
      case "processing":
        return "ENGINE PROCESSING";
      case "error":
        return "ENGINE ERROR";
      default:
        return "ENGINE STANDBY";
    }
  }, [engineState]);

  const engineTitle = health
    ? `Backend ${health.status} · CadQuery ${health.cadquery_version ?? "unknown"}`
    : "Backend status unknown";

  return (
    <div className="workspace">
      {booting ? (
        <BootScreen checks={bootChecks} onDone={handleBootDone} />
      ) : null}

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            CG
          </span>
          <span className="brand-text">
            <strong>cgen</strong>
            <small>AI CAD generator</small>
          </span>
        </div>
        <div
          className={`engine-pill ${engineState}`}
          title={engineTitle}
          role="status"
        >
          <span className="engine-dot" aria-hidden="true" />
          {engineLabel}
        </div>
      </header>

      <main className="layout">
        <div className="viewport-column">
          <CadViewport
            stlUrl={stlUrl}
            busy={busy}
            previewError={previewError}
            onPreviewStatus={handlePreviewStatus}
            onSelectExample={setPrompt}
            schemaVersion={SCHEMA_VERSION}
          />
          {busy ? (
            <div className="generation-loader-dock">
              <GenerationLoader />
            </div>
          ) : null}
        </div>
        <aside className="sidebar">
          <GeneratePanel
            prompt={prompt}
            generating={busy}
            error={status === "error" ? generateError : null}
            onPromptChange={setPrompt}
            onGenerate={handleGenerate}
          />
          {result && status === "ready" ? <SpecPanel result={result} /> : null}
          {result && status === "ready" ? <Downloads result={result} /> : null}
        </aside>
      </main>

      <footer className="meta-tape">
        <span>SCHEMA {SCHEMA_VERSION}</span>
        <span className="sep">|</span>
        <span>STEP AUTHORITATIVE · STL PREVIEW MESH</span>
        <span className="sep">|</span>
        <span>AI EMITS SPECIFICATIONS — NEVER EXECUTABLE CODE</span>
        <span className="sep">|</span>
        <span aria-hidden="true">REV 2026</span>
      </footer>
    </div>
  );
}
