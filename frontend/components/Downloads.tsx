"use client";

import type { GenerateResponse } from "@/types/api";
import { resolveFileUrl } from "@/lib/api";
import { formatBytes } from "@/lib/spec";

interface DownloadsProps {
  result: GenerateResponse;
}

export function Downloads({ result }: DownloadsProps) {
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
      </p>
    </section>
  );
}
