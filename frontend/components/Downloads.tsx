"use client";

import type { GenerateResponse } from "@/types/api";
import { resolveFileUrl } from "@/lib/api";
import { formatBytes } from "@/lib/spec";

interface DownloadsProps {
  result: GenerateResponse;
  onRemint?: () => void;
  remintBusy?: boolean;
}

export function Downloads({ result, onRemint, remintBusy }: DownloadsProps) {
  const entries = [result.files.step, result.files.stl];
  return (
    <section className="panel" aria-labelledby="files-heading" data-testid="files-panel">
      <h2 id="files-heading" className="panel-title">
        Output
      </h2>
      <ul className="file-list">
        {entries.map((file) => (
          <li key={file.format} className="file-row">
            <div className="file-meta">
              <span className="file-format">{file.format.toUpperCase()}</span>
              <span className="file-name mono">{file.filename}</span>
              <span className="file-size">{formatBytes(file.bytes)}</span>
            </div>
            <a
              className="download-button"
              href={resolveFileUrl(file.download_url)}
              download={file.filename}
              aria-label={`Download ${file.format.toUpperCase()} file ${file.filename}`}
            >
              Download
            </a>
          </li>
        ))}
      </ul>
      <p className="files-note">
        STEP is the authoritative CAD artifact. STL is the preview mesh.
        Download links expire after ~1h or on server restart; the spec is
        kept — re-run Generate/Rebuild for fresh links.
      </p>
      {onRemint ? (
        <button
          type="button"
          className="download-button"
          onClick={onRemint}
          disabled={remintBusy}
          aria-label="Re-mint fresh STEP and STL files for this revision"
        >
          {remintBusy ? "Re-minting…" : "Re-mint files"}
        </button>
      ) : null}
    </section>
  );
}
