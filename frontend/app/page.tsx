"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CadViewport } from "@/components/cad/CadViewport";
import type { PreviewState } from "@/components/cad/StlModel";
import { Downloads } from "@/components/Downloads";
import { GeneratePanel } from "@/components/GeneratePanel";
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

export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState<PageStatus>("idle");
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [stlUrl, setStlUrl] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    checkBackendHealth().then((info) => {
      if (!cancelled) setHealth(info);
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

  const handlePreviewStatus = useCallback((state: PreviewState, message?: string) => {
    if (state === "error") {
      setPreviewError(
        message ?? "The preview mesh could not be loaded. Downloads still work.",
      );
    } else if (state === "loading") {
      setPreviewError(null);
    }
  }, []);

  const busy = status === "generating";

  return (
    <div className="workspace">
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
          className={`health-pill ${health?.cadquery_available ? "ok" : "unknown"}`}
          title={
            health
              ? `Backend reachable · CadQuery ${health.cadquery_version ?? "unknown"}`
              : "Backend status unknown"
          }
        >
          <span className="health-dot" aria-hidden="true" />
          {health?.cadquery_available
            ? `API ready · CQ ${health.cadquery_version ?? "?"}`
            : "API status…"}
        </div>
      </header>

      <main className="layout">
        <CadViewport
          stlUrl={stlUrl}
          busy={busy}
          previewError={previewError}
          onPreviewStatus={handlePreviewStatus}
          onSelectExample={setPrompt}
        />
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

      <footer className="footnote">
        STEP is the authoritative CAD artifact · STL renders the browser preview ·
        AI produces structured specifications, never executable code
      </footer>
    </div>
  );
}
