"use client";

/**
 * M8.1 parametric session hook: transient preview + single-commit revision.
 *
 * Owns edits, debounced rebuild previews, stale-response guarding, and the
 * commit flow (reuse matching preview, else one final rebuild). Never
 * touches project/revision state — commit() returns the summary and the
 * winning response; the caller appends exactly one revision.
 *
 * Sequencing: every preview/commit attempt takes a sequence number; only
 * the newest sequence may write state. In-flight requests are also aborted
 * so the backend does minimal wasted work.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { humanizeApiError, rebuildPart, type ApiError } from "@/lib/api";
import {
  applyParameter,
  extractParameters,
  specsEqualJson,
  summarizeAdjustments,
  type ParameterDescriptor,
} from "@/lib/parameters";
import type { DocumentSpecification, GenerateResponse } from "@/types/api";

export const PREVIEW_DEBOUNCE_MS = 650;

export interface SessionPreview {
  spec: DocumentSpecification;
  response: GenerateResponse;
}

export interface CommitResult {
  summary: string;
  response: GenerateResponse;
}

function buildEditedSpec(
  base: DocumentSpecification,
  descriptors: ParameterDescriptor[],
  edits: Record<string, number>,
): DocumentSpecification {
  let next = base;
  for (const d of descriptors) {
    const value = edits[d.key];
    if (value === undefined || value === d.value) continue;
    next = applyParameter(next, d.target, value);
  }
  return next;
}

export function useParametricSession(baseSpec: DocumentSpecification | null) {
  const [edits, setEdits] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<SessionPreview | null>(null);
  const [paramError, setParamError] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [committing, setCommitting] = useState(false);
  const seqRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const committingRef = useRef(false);
  const latest = useRef({ edits, preview });
  latest.current = { edits, preview };

  const descriptors = useMemo(
    () => (baseSpec === null ? [] : extractParameters(baseSpec)),
    [baseSpec],
  );

  const editedSpec = useMemo<DocumentSpecification | null>(() => {
    if (baseSpec === null) return null;
    try {
      return buildEditedSpec(baseSpec, descriptors, edits);
    } catch {
      return baseSpec;
    }
  }, [baseSpec, descriptors, edits]);

  const editsActive = Object.keys(edits).length > 0;
  const previewCurrent =
    preview !== null &&
    editedSpec !== null &&
    specsEqualJson(preview.spec, editedSpec);

  const clearFlight = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const reset = useCallback(() => {
    clearFlight();
    committingRef.current = false;
    seqRef.current += 1;
    setEdits({});
    setPreview(null);
    setParamError(null);
    setPreviewBusy(false);
    setCommitting(false);
  }, [clearFlight]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  const runRebuild = useCallback(
    async (
      seq: number,
      base: DocumentSpecification,
      spec: DocumentSpecification,
    ): Promise<GenerateResponse | null> => {
      const controller = new AbortController();
      abortRef.current = controller;
      setPreviewBusy(true);
      try {
        const response = await rebuildPart(
          base as unknown as Record<string, unknown>,
          spec as unknown as Record<string, unknown>,
          controller.signal,
        );
        if (seqRef.current !== seq) return null;
        setPreview({ spec, response });
        setParamError(null);
        return response;
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return null;
        if (seqRef.current !== seq) return null;
        setParamError(humanizeApiError(err as ApiError));
        return null;
      } finally {
        if (seqRef.current === seq) setPreviewBusy(false);
      }
    },
    [],
  );

  const previewValue = useCallback(
    (key: string, value: number) => {
      if (baseSpec === null || committingRef.current) return;
      const descriptor = descriptors.find((d) => d.key === key);
      if (descriptor === undefined) return;
      const clamped = Math.min(descriptor.max * 4, Math.max(0.01, value));
      setEdits((prev) => {
        if (clamped === descriptor.value) {
          return Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key));
        }
        return { ...prev, [key]: clamped };
      });
      setParamError(null);
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      abortRef.current?.abort();
      const seq = seqRef.current + 1;
      seqRef.current = seq;
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        if (baseSpec === null) return;
        // Read the freshest edits (this tick's change may not be rendered yet).
        const current = { ...latest.current.edits };
        const known = descriptors.find((d) => d.key === key);
        if (known !== undefined) {
          if (clamped === known.value) delete current[key];
          else current[key] = clamped;
        }
        try {
          const spec = buildEditedSpec(baseSpec, descriptors, current);
          void runRebuild(seq, baseSpec, spec);
        } catch {
          if (seqRef.current === seq) {
            setParamError("That value cannot be applied to this model.");
          }
        }
      }, PREVIEW_DEBOUNCE_MS);
    },
    [baseSpec, descriptors, runRebuild],
  );

  const commit = useCallback(async (): Promise<CommitResult | null> => {
    const { edits: nowEdits, preview: nowPreview } = latest.current;
    if (
      Object.keys(nowEdits).length === 0 ||
      baseSpec === null ||
      committingRef.current
    ) {
      return null;
    }
    committingRef.current = true;
    setCommitting(true);
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    abortRef.current?.abort();
    try {
      let spec: DocumentSpecification;
      try {
        spec = buildEditedSpec(baseSpec, descriptors, nowEdits);
      } catch {
        setParamError("That value cannot be applied to this model.");
        return null;
      }
      // Phase 7: reuse the matching preview instead of rebuilding again.
      if (nowPreview !== null && specsEqualJson(nowPreview.spec, spec)) {
        return {
          summary: summarizeAdjustments(descriptors, nowEdits),
          response: nowPreview.response,
        };
      }
      const seq = seqRef.current + 1;
      seqRef.current = seq;
      setPreviewBusy(true);
      const response = await runRebuild(seq, baseSpec, spec);
      if (response === null) return null;
      return {
        summary: summarizeAdjustments(descriptors, nowEdits),
        response,
      };
    } finally {
      committingRef.current = false;
      setCommitting(false);
    }
  }, [baseSpec, descriptors, runRebuild]);

  return {
    descriptors,
    edits,
    editedSpec,
    preview,
    previewCurrent,
    editsActive,
    paramError,
    previewBusy,
    committing,
    canCommit: editsActive,
    previewValue,
    commit,
    reset,
  };
}
