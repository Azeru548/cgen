"use client";

import Image from "next/image";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BootScreen, type BootChecks } from "@/components/BootScreen";
import { CadViewport } from "@/components/cad/CadViewport";
import type { PreviewState } from "@/components/cad/StlModel";
import { Inspector } from "@/components/Inspector";
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

const SCHEMA_VERSION = "M6 · SCHEMA 3.1";
const MAX_PROMPT_LENGTH = 2000;

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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
      setGenerateError("Describe the part first \u2014 the prompt is empty.");
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

  const handlePromptKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        handleGenerate();
      }
    },
    [handleGenerate],
  );

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
    ? `Backend ${health.status} \u00b7 CadQuery ${health.cadquery_version ?? "unknown"}`
    : "Backend status unknown";

  return (
    <div className="workspace">
      {booting ? (
        <BootScreen checks={bootChecks} onDone={handleBootDone} />
      ) : null}

      <header className="topbar">
        <div className="brand">
          <Image
            src="/logo-removebg.png"
            alt="cgen logo"
            width={32}
            height={32}
            className="brand-logo"
            priority
          />
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
        <div className="workspace-main">
          <CadViewport
            stlUrl={stlUrl}
            busy={busy}
            previewError={previewError}
            onPreviewStatus={handlePreviewStatus}
            onSelectExample={setPrompt}
            schemaVersion={SCHEMA_VERSION}
          />

          <div className="prompt-bar">
            {status === "error" && generateError ? (
              <div className="error-box">
                <div className="error-title">Generation failed</div>
                <div className="error-text">{generateError}</div>
              </div>
            ) : null}
            <div className="prompt-bar-inner">
              <textarea
                ref={textareaRef}
                className="prompt-input"
                placeholder="Describe the part you want to build..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={handlePromptKeyDown}
                disabled={busy}
                rows={2}
                maxLength={MAX_PROMPT_LENGTH}
                aria-label="Part description"
              />
              <button
                className="generate-button"
                onClick={handleGenerate}
                disabled={busy || prompt.trim().length === 0}
                aria-label="Generate CAD model"
              >
                {busy ? "Generating..." : "Generate"}
              </button>
            </div>
            <div className="prompt-footer">
              <span className="char-count">
                {prompt.length} / {MAX_PROMPT_LENGTH}
              </span>
              <span className="char-count">Ctrl+Enter to generate</span>
            </div>
          </div>
        </div>

        <aside className="inspector">
          <Inspector result={result} status={status} />
        </aside>
      </main>
    </div>
  );
}
