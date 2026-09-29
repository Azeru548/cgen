import Link from "next/link";
import Image from "next/image";
import { SpecReadout } from "@/components/landing/SpecReadout";

/** Product landing. Persuade mode: prove the mechanism, then one action. */
export default function LandingPage() {
  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="brand-mark">
          <Image
            src="/logo-removebg.png"
            alt="cgen"
            width={40}
            height={40}
            className="brand-logo"
            priority
          />
        </span>
        <span className="landing-bar-name mono">cgen</span>
        <span className="topbar-spacer" />
        <Link className="landing-link" href="/signin">
          Sign in
        </Link>
        <Link className="landing-cta" href="/workspace">
          Open the bench
        </Link>
      </header>

      <main className="landing-main">
        <section className="landing-hero">
          <div className="landing-copy">
            <h1 className="landing-hook">
              Describe the part.
              <br />
              Get the solid.
            </h1>
            <p className="landing-sub">
              cgen turns a plain sentence into a validated CAD specification,
              builds it with a deterministic engine, and hands back STEP and
              STL you can manufacture. Adjust numbers and placement without ever
              calling the model again.
            </p>
            <div className="landing-actions">
              <Link className="landing-cta landing-cta-lg" href="/signin">
                Start building
              </Link>
              <Link className="landing-ghost" href="/workspace">
                Try it without an account
              </Link>
            </div>
            <dl className="landing-facts">
              <div>
                <dt className="mono">Output</dt>
                <dd>STEP + STL, per component</dd>
              </div>
              <div>
                <dt className="mono">Geometry</dt>
                <dd>CadQuery, deterministic</dd>
              </div>
              <div>
                <dt className="mono">Edits</dt>
                <dd>Numeric changes skip the LLM</dd>
              </div>
            </dl>
          </div>

          <div className="landing-proof">
            <SpecReadout />
          </div>
        </section>

        <section className="landing-steps" aria-label="How it works">
          <article className="landing-step">
            <span className="landing-step-tag mono">Describe</span>
            <h2>A sentence in, a specification out</h2>
            <p>
              The model returns a structured CAD document, not code. Dimensions,
              hole patterns and features are validated before any geometry is
              built, so a bad request fails in words you can act on.
            </p>
          </article>
          <article className="landing-step">
            <span className="landing-step-tag mono">Assemble</span>
            <h2>A real component library, no AI needed</h2>
            <p>
              Add an ESP32, a servo, a chassis plate or M3 hardware straight
              from the library. Library inserts never call the model, and
              repeated parts are one definition with N poses.
            </p>
          </article>
          <article className="landing-step">
            <span className="landing-step-tag mono">Keep</span>
            <h2>History that is never rewritten</h2>
            <p>
              Every generate, modify or assembly edit appends a revision. Step
              back to any earlier state, branch a new one from it, and nothing
              is destroyed.
            </p>
          </article>
        </section>

        <section className="landing-close">
          <h2>Start at the bench</h2>
          <p className="landing-sub">
            Accounts keep your projects per user. You can also skip straight in
            and work without one.
          </p>
          <Link className="landing-cta landing-cta-lg" href="/signin">
            Create an account
          </Link>
        </section>
      </main>

      <footer className="landing-foot mono">
        cgen — language to solid · CadQuery geometry · STEP/STL export
      </footer>
    </div>
  );
}
