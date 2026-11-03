import Link from "next/link";

/** Custom 404. Next's default is an unstyled page that looks like a different
 *  product, which is exactly the wrong note on a launch-day dead link. */
export default function NotFound() {
  return (
    <main className="legal">
      <div className="legal-inner">
        <p className="legal-eyebrow mono">
          <Link href="/">← cgen</Link>
          <span>404</span>
        </p>

        <h1>No such page.</h1>
        <p className="legal-lede">
          The address you followed does not exist in this deployment. It may have
          been renamed, or a link may have been mistyped.
        </p>

        <div className="legal-actions">
          <Link className="lp-cta" href="/">
            Back to the bench <span aria-hidden="true">→</span>
          </Link>
          <Link className="lp-ghost mono" href="/workspace">
            Open the workspace
          </Link>
        </div>

        <p className="legal-foot mono">
          <span>cgen · language to solid</span>
          <Link href="/terms">Terms →</Link>
        </p>
      </div>
    </main>
  );
}
