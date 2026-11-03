import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What cgen stores, where it is stored, and what it never collects. No third-party trackers, no advertising pixels.",
  alternates: { canonical: "/privacy" },
};

const REPO = "https://github.com/Azeru548/cgen";

export default function PrivacyPage() {
  return (
    <main className="legal">
      <div className="legal-inner">
        <p className="legal-eyebrow mono">
          <Link href="/">← cgen</Link>
          <span>Privacy</span>
        </p>

        <h1>Privacy</h1>
        <p className="legal-lede">
          This page describes exactly what this deployment keeps. It is short
          because the product keeps very little.
        </p>

        <h2>What is stored</h2>
        <ul>
          <li>
            <strong>The text you type</strong> — the prompt or modification
            instruction is sent to the CAD service and to the language-model
            provider that turns it into a specification.
          </li>
          <li>
            <strong>Your work, if you sign in</strong> — project and workspace
            documents containing the validated specification, its revisions,
            object placements and file links are stored in Google Cloud
            Firestore under your account&apos;s user id.
          </li>
          <li>
            <strong>Your account identity</strong> — the email address and
            provider identity Firebase issues when you sign in.
          </li>
          <li>
            <strong>Generated files</strong> — STEP and STL artifacts are stored
            in the deployment&apos;s object storage (Byteship) and are reachable
            by anyone who holds the link. Do not generate confidential geometry.
          </li>
          <li>
            <strong>Aggregate counters</strong> — daily counts of product events
            (for example &quot;generation completed&quot;) and client error
            messages. No prompt text and no user identifier are attached to
            these.
          </li>
        </ul>

        <h2>What is not stored</h2>
        <ul>
          <li>No advertising or cross-site tracking scripts, cookies or pixels.</li>
          <li>
            No payment data — there is no payment flow in this deployment.
          </li>
          <li>
            Nothing at all for a signed-out visitor: guest work lives in the
            browser tab and is gone when the tab closes or the page reloads.
          </li>
        </ul>

        <h2>Who processes it</h2>
        <p>
          Requests pass through the hosting providers of this deployment. The
          language model call goes to the configured AI provider, and file
          storage to Byteship. Authentication is handled by Google Firebase.
        </p>

        <h2>Deletion</h2>
        <p>
          A signed-in user can delete a workspace from the history panel, which
          removes its document from Firestore. Generated STEP/STL files already
          written to object storage are not deleted individually; to request
          removal of a file or of account data, open an issue at{" "}
          <a href={`${REPO}/issues`} rel="noreferrer noopener" target="_blank">
            {REPO.replace("https://", "")}/issues
          </a>
          .
        </p>

        <h2>Changes</h2>
        <p>
          This notice is versioned with the code. The source of this page is in
          the repository, so any change is visible in its history.
        </p>

        <p className="legal-foot mono">
          <span>Last updated 3 November 2026</span>
          <Link href="/terms">Terms →</Link>
        </p>
      </div>
    </main>
  );
}
