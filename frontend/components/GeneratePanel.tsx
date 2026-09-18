"use client";

import { MAX_PROMPT_LENGTH } from "@/lib/api";

interface GeneratePanelProps {
  prompt: string;
  generating: boolean;
  error: string | null;
  onPromptChange: (value: string) => void;
  onGenerate: () => void;
}

export function GeneratePanel({
  prompt,
  generating,
  error,
  onPromptChange,
  onGenerate,
}: GeneratePanelProps) {
  const remaining = MAX_PROMPT_LENGTH - prompt.length;

  return (
    <section className="panel" aria-labelledby="generate-heading">
      <h2 id="generate-heading" className="panel-title">
        Generate
      </h2>
      <label htmlFor="prompt-input" className="field-label">
        Describe your part
      </label>
      <textarea
        id="prompt-input"
        className="prompt-input"
        rows={5}
        maxLength={MAX_PROMPT_LENGTH}
        placeholder="Create a 120mm long shaft with a 30mm diameter and a 15mm hole through the center."
        value={prompt}
        disabled={generating}
        onChange={(e) => onPromptChange(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !generating) {
            e.preventDefault();
            onGenerate();
          }
        }}
      />
      <div className="prompt-footer">
        <span
          className="char-count"
          aria-label={`${remaining} characters remaining`}
        >
          {prompt.length} / {MAX_PROMPT_LENGTH}
        </span>
        <button
          type="button"
          className="generate-button"
          onClick={onGenerate}
          disabled={generating || prompt.trim().length === 0}
        >
          {generating ? "Generating…" : "Generate"}
        </button>
      </div>
      {error ? (
        <div className="error-box" role="alert" data-testid="generate-error">
          <p className="error-title">Generation failed</p>
          <p className="error-text">{error}</p>
        </div>
      ) : null}
    </section>
  );
}
