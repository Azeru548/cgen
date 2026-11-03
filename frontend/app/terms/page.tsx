import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms",
  description:
    "The terms for using cgen: what the service does, what it does not promise, and who owns the parts you generate.",
  alternates: { canonical: "/terms" },
};

const REPO = "https://github.com/Azeru548/cgen";

export default function TermsPage() {
  return (
    <main className="legal">
      <div className="legal-inner">
        <p className="legal-eyebrow mono">
          <Link href="/">← cgen</Link>
          <span>Terms</span>
        </p>

        <h1>Terms</h1>
        <p className="legal-lede">
          Plain terms for a free tool. If you need something different, do not
          use this deployment.
        </p>

        <h2>What the service does</h2>
        <p>
          cgen turns a natural-language description into a validated CAD
          specification and builds STEP and STL files from it with a
          deterministic geometry engine. The language model never writes or runs
          code; it only proposes a specification that must pass validation.
        </p>

        <h2>Your parts</h2>
        <p>
          You keep whatever rights you have in the designs you generate. You are
          responsible for them: do not use the service to produce weapons,
          safety-critical components, patented designs you do not own, or
          anything illegal where you live.
        </p>

        <h2>No engineering warranty</h2>
        <p>
          Files are provided as-is, without warranty of any kind. A passed schema
          check is not a manufacturing review. Verify every dimension, tolerance
          and material choice before you cut metal, and treat the STEP file as
          the authoritative artifact rather than the preview mesh.
        </p>

        <h2>Availability and limits</h2>
        <p>
          This is a free deployment running on shared infrastructure: it may be
          slow to wake, rate limited, or offline without notice. Daily and
          per-client limits exist to keep the service usable for everyone, and
          requests over them are refused.
        </p>

        <h2>Acceptable use</h2>
        <ul>
          <li>Do not automate the API to bypass limits or resell capacity.</li>
          <li>Do not probe, overload, or attempt to break the service.</li>
          <li>
            Do not upload or submit material you have no right to share; prompts
            are sent to a third-party model provider.
          </li>
        </ul>

        <h2>Changes</h2>
        <p>
          These terms are versioned with the code in the repository, so changes
          are visible in its history. Continued use after a change means you
          accept the updated terms.
        </p>

        <p className="legal-foot mono">
          <span>Last updated 3 November 2026</span>
          <a href={`${REPO}/issues`} rel="noreferrer noopener" target="_blank">
            Questions → issues
          </a>
        </p>
      </div>
    </main>
  );
}
