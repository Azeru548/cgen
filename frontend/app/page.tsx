import Image from "next/image";
import Link from "next/link";
import { SpecimenPanel } from "@/components/landing/SpecimenPanel";
import { LandingPing, TrackedLink } from "@/components/landing/TrackedLink";

const FACTS = [
  { label: "Output", value: "STEP + STL" },
  { label: "Engine", value: "CadQuery" },
  { label: "Model role", value: "Spec only" },
];

const STATIONS = [
  {
    number: "01",
    label: "Interpret",
    title: "Intent, not code.",
    copy: "The model reads a plain sentence and returns a strict JSON CAD document. No Python, no shell, no executable output.",
    output: "3d_part v3.2",
  },
  {
    number: "02",
    label: "Validate",
    title: "Every number checked.",
    copy: "Pydantic enforces operation types, dimension ranges, feature caps and unit normalization before geometry begins.",
    output: "schema valid",
  },
  {
    number: "03",
    label: "Build",
    title: "Deterministic geometry.",
    copy: "CadQuery builds the solid in millimeters. Through-holes, grids and fillets are applied in a fixed, tested order.",
    output: "STEP + STL",
  },
  {
    number: "04",
    label: "Keep",
    title: "History, not overwrites.",
    copy: "Every successful edit appends a revision. Re-view any earlier state and branch from it without losing the record.",
    output: "rev + 1",
  },
];

const OPERATIONS = [
  { type: "box", meta: "width · depth · height" },
  { type: "cylinder", meta: "radius · height" },
  { type: "cone", meta: "bottom_r · top_r · height" },
  { type: "sphere", meta: "radius" },
  { type: "torus", meta: "major_r · minor_r" },
  { type: "polygon_prism", meta: "sides · circumradius" },
  { type: "revolve", meta: "axial section · angle" },
  { type: "sweep", meta: "wire radius · 3D path" },
  { type: "union", meta: "base + tool" },
  { type: "cut", meta: "base − tool" },
  { type: "intersect", meta: "base ∩ tool" },
  { type: "part", meta: "build + features" },
];

const FEATURES = [
  ["hole", "one centered bore, through or blind"],
  ["hole_pattern", "2–12 holes on a bolt circle"],
  ["hole_grid", "rectangular or linear arrays"],
  ["shell", "hollow with an open top face"],
  ["chamfer", "45° bevel on outer rims"],
  ["fillet", "rolled radius on outer rims"],
];

const LIBRARY = [
  ["Geometry", "06", "plates, extrusions, profiles"],
  ["Fasteners", "17", "screws, nuts, washers, inserts"],
  ["Mechanical", "13", "gears, pulleys, extrusion, springs"],
  ["Electronics", "16", "boards, fans, headers, holders"],
  ["Robotics", "11", "servos, rails, hubs, casters"],
  ["Templates", "09", "enclosures and printed helpers"],
];

const LEDGER = [
  {
    rev: "REV 06",
    kind: "Assemble",
    prompt: "Add ESP32, four M3 × 12 screws, chassis plate",
    digest: "sha 91b0e2",
    time: "10:31",
  },
  {
    rev: "REV 05",
    kind: "Modify",
    prompt: "Open the USB cutout to 12 × 6 mm",
    digest: "sha 8f2c41",
    time: "10:24",
  },
  {
    rev: "REV 04",
    kind: "Adjust",
    prompt: "Shell 2.5 → 3.0 mm; mounting holes Ø3.2 → Ø3.4",
    digest: "sha 22d7c9",
    time: "10:18",
  },
  {
    rev: "REV 03",
    kind: "Generate",
    prompt: "Arduino Uno enclosure, 120 × 80 × 40 mm",
    digest: "sha 5c1a77",
    time: "10:11",
  },
];

const STATS = [
  ["10", "operation types"],
  ["25+", "registry components"],
  ["2", "export formats"],
  ["0", "lines of AI code"],
];

const FAQ = [
  {
    q: "Is this real CAD or a rendered picture?",
    a: "Real. Every generation ends with validated STEP and STL files from CadQuery. The STEP file is the authoritative artifact and opens in standard CAD software; the STL is the preview mesh.",
  },
  {
    q: "Does the model write code?",
    a: "No. The model returns a JSON specification that must pass a strict Pydantic schema. Only an allowlisted set of operations and registry components can reach the geometry engine, so a bad or hostile response fails validation instead of running.",
  },
  {
    q: "Do I need an account?",
    a: "No. The sign-in page has a guest path straight into the bench. An account keeps projects and revision history in Firestore and makes them available across sessions.",
  },
  {
    q: "Why do download links expire?",
    a: "Generated files live on ephemeral storage with a short TTL. The specification in each revision does not expire, so Re-mint files rebuilds fresh STEP/STL from the stored spec without calling the model.",
  },
  {
    q: "Can I self-host it?",
    a: "Yes. The project is MIT licensed: FastAPI + CadQuery on the backend, Next.js on the frontend, with your own Groq key and an optional Firebase project for accounts. The README covers the local setup and deployment.",
  },
  {
    q: "What can't it do?",
    a: "It is not a full MCAD package. There is no constraint solver, collision engine, real thread geometry or professional mating. Assembly placement is explicit transforms plus lightweight relationships, and fit conflicts fail loudly rather than producing silent bad geometry.",
  },
];

function OpGlyph({ type }: { type: string }) {
  const line = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.4,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <svg className="lp-glyph" viewBox="0 0 48 48" aria-hidden="true">
      {type === "box" && (
        <g {...line}>
          <path d="M10 17 24 10l14 7-14 7z" />
          <path d="M10 17v14l14 7 14-7V17" />
          <path d="M24 24v14" />
        </g>
      )}
      {type === "cylinder" && (
        <g {...line}>
          <ellipse cx="24" cy="13" rx="13" ry="5" />
          <path d="M11 13v22c0 2.8 5.8 5 13 5s13-2.2 13-5V13" />
          <path d="M11 24c0 2.8 5.8 5 13 5s13-2.2 13-5" opacity=".45" />
        </g>
      )}
      {type === "cone" && (
        <g {...line}>
          <ellipse cx="24" cy="37" rx="13" ry="5" />
          <path d="M11 37 24 8l13 29" />
          <path d="M11 37c0 2.8 5.8 5 13 5s13-2.2 13-5" />
        </g>
      )}
      {type === "sphere" && (
        <g {...line}>
          <circle cx="24" cy="24" r="15" />
          <ellipse cx="24" cy="24" rx="15" ry="5.5" opacity=".5" />
          <ellipse cx="24" cy="24" rx="5.5" ry="15" opacity=".5" />
        </g>
      )}
      {type === "torus" && (
        <g {...line}>
          <ellipse cx="24" cy="24" rx="17" ry="10" />
          <ellipse cx="24" cy="24" rx="7" ry="4" />
        </g>
      )}
      {type === "polygon_prism" && (
        <g {...line}>
          <path d="M24 7 39 15v18L24 41 9 33V15z" />
          <path d="M9 15 24 23l15-8M24 23v18" opacity=".55" />
        </g>
      )}
      {type === "revolve" && (
        <g {...line}>
          <path d="M24 6v36" opacity=".4" strokeDasharray="3 3" />
          <ellipse cx="24" cy="13" rx="13" ry="5" />
          <ellipse cx="24" cy="35" rx="9" ry="3.5" />
          <path d="M11 13v22M37 13v22" />
        </g>
      )}
      {type === "sweep" && (
        <g {...line}>
          <path d="M9 36h14a8 8 0 0 0 8-8V15" />
          <path d="M9 41h14a13 13 0 0 0 13-13V15" opacity=".55" />
          <circle cx="31" cy="12" r="3.5" />
        </g>
      )}
      {type === "union" && (
        <g {...line}>
          <rect x="7" y="15" width="18" height="18" />
          <rect x="23" y="15" width="18" height="18" />
          <path d="M24 30v8M20 34h8" />
        </g>
      )}
      {type === "cut" && (
        <g {...line}>
          <rect x="7" y="15" width="22" height="18" />
          <circle cx="31" cy="24" r="8" strokeDasharray="3 3" />
          <path d="M18 24h12" />
        </g>
      )}
      {type === "intersect" && (
        <g {...line}>
          <circle cx="18" cy="24" r="11" />
          <circle cx="30" cy="24" r="11" />
          <path d="M24 14.5c4 5.6 4 13.4 0 19" />
        </g>
      )}
      {type === "part" && (
        <g {...line}>
          <rect x="9" y="11" width="30" height="26" rx="3" />
          <circle cx="24" cy="24" r="6.5" />
          <path d="M9 31h8" opacity=".6" />
        </g>
      )}
    </svg>
  );
}

function StackDrawing() {
  return (
    <svg
      className="lp-stack"
      viewBox="0 0 440 360"
      role="img"
      aria-label="Exploded assembly of a chassis plate, controller board, standoffs and screws"
    >
      <title>Exploded assembly</title>
      <g className="lp-stack-line">
        <path d="M86 268 232 322 356 268 210 216z" />
        <path d="M86 268v10l124 54 146-54v-10" opacity=".55" />
        <path d="M100 250 236 300 360 250 224 202z" />
        <path d="M100 250v8l124 50 136-50v-8" opacity=".45" />
        <path d="M112 226 238 272 350 226 224 182z" />
        <path d="M112 226v7l126 46 112-46v-7" opacity=".4" />
      </g>
      <g className="lp-stack-part">
        <path d="M112 226 238 272 350 226 224 182z" />
        <path d="M136 212 238 248 326 212 224 176z" opacity=".5" />
        <path d="M154 205h30v18h-30zM260 200h24v16h-24z" opacity=".65" />
        <path d="M205 190h34v12h-34z" opacity=".65" />
      </g>
      <g className="lp-stack-standoff">
        <path d="M128 246v-20M336 246v-20M154 272v-20M318 272v-20" />
        <circle cx="128" cy="226" r="3" />
        <circle cx="336" cy="226" r="3" />
        <circle cx="154" cy="252" r="3" />
        <circle cx="318" cy="252" r="3" />
      </g>
      <g className="lp-stack-screw">
        <path d="M128 198v-23M336 198v-23M154 224v-23M318 224v-23" />
        <path d="M120 175h16M328 175h16M146 201h16M310 201h16" />
        <path d="M120 168h16M328 168h16M146 194h16M310 194h16" opacity=".55" />
      </g>
      <g className="lp-stack-label">
        <path d="M224 176 224 120 286 120" />
        <text x="292" y="117">ESP32</text>
        <path d="M350 226 384 202 384 164" />
        <text x="352" y="150">CHASSIS PLATE</text>
        <path d="M336 190 384 166" />
        <text x="352" y="182">M3 × 12</text>
      </g>
    </svg>
  );
}

export default function LandingPage() {
  return (
    <div className="lp">
      <LandingPing />
      <header className="lp-bar">
        <div className="lp-bar-inner">
          <Link href="/" className="lp-brand" aria-label="cgen home">
            <Image
              src="/logo-wordmark-light.png"
              alt=""
              width={423}
              height={107}
              className="lp-brand-logo"
              priority
            />
            <span className="lp-brand-tag mono">language → solid</span>
          </Link>

          <nav className="lp-nav" aria-label="Landing sections">
            <a href="#sequence">Sequence</a>
            <a href="#capabilities">Capabilities</a>
            <a href="#assembly">Assembly</a>
            <a href="#history">History</a>
            <a href="#interface">Interface</a>
          </nav>

          <div className="lp-bar-actions">
            <Link className="lp-link mono" href="/signin">
              Sign in
            </Link>
            <Link className="lp-cta" href="/workspace">
              Open the bench <span aria-hidden="true">→</span>
            </Link>
          </div>
        </div>
      </header>
      <div className="lp-tickrail" aria-hidden="true" />

      <main>
        <section className="lp-hero">
          <div className="lp-hero-grid">
            <div className="lp-hero-copy">
              <p className="lp-eyebrow mono">
                <span className="lp-eyebrow-mark" aria-hidden="true" />
                Language → validated solid
              </p>
              <h1 className="lp-h1">
                Say the part.
                <br />
                Hold the solid<span className="lp-dot">.</span>
              </h1>
              <p className="lp-lede">
                cgen reads a plain sentence, returns a validated CAD
                specification, and machines it with a deterministic engine.
                STEP and STL come out the other side — not a picture of a part,
                the part.
              </p>
              <div className="lp-actions">
                <TrackedLink
                  className="lp-cta lp-cta-lg"
                  href="/workspace"
                  event="landing_cta"
                >
                  Start building <span aria-hidden="true">→</span>
                </TrackedLink>
                <a className="lp-ghost mono" href="#sequence">
                  See the pipeline
                </a>
              </div>
              <dl className="lp-facts">
                {FACTS.map((fact) => (
                  <div key={fact.label} className="lp-fact">
                    <dt className="mono">{fact.label}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
              <p className="lp-hero-note mono">
                No code execution · deterministic CadQuery · schema v3.2
              </p>
            </div>

            <div className="lp-hero-instrument">
              <SpecimenPanel />
              <div className="lp-plate mono">
                <span>Specimen series 01–03</span>
                <span>not a customer file</span>
              </div>
            </div>
          </div>
        </section>

        <div className="lp-marquee" aria-hidden="true">
          <div className="lp-marquee-track mono">
            {[0, 1].map((copy) => (
              <span key={copy} className="lp-marquee-set">
                <span>Schema 3.2</span>
                <i />
                <span>Deterministic geometry</span>
                <i />
                <span>No code execution</span>
                <i />
                <span>STEP / STL</span>
                <i />
                <span>Component registry</span>
                <i />
                <span>Append-only revisions</span>
                <i />
              </span>
            ))}
          </div>
        </div>

        <section className="lp-section" id="sequence">
          <div className="lp-section-inner">
            <header className="lp-section-head">
              <p className="lp-kicker mono">01 / sequence</p>
              <h2 className="lp-title">Four moves from sentence to solid.</h2>
              <p className="lp-section-lede">
                The model interprets intent. The schema checks every number.
                The engine builds geometry. The bench keeps the record. Nothing
                in that chain executes generated code.
              </p>
            </header>

            <ol className="lp-sequence">
              {STATIONS.map((station) => (
                <li key={station.number} className="lp-station">
                  <div className="lp-station-top mono">
                    <span className="lp-station-num">{station.number}</span>
                    <span>{station.label}</span>
                  </div>
                  <h3>{station.title}</h3>
                  <p>{station.copy}</p>
                  <span className="lp-station-out mono">{station.output}</span>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="lp-section lp-band" id="capabilities">
          <div className="lp-section-inner">
            <header className="lp-section-head lp-split-head">
              <div>
                <p className="lp-kicker mono">02 / capability</p>
                <h2 className="lp-title">A machining vocabulary, not a prompt trick.</h2>
              </div>
              <p className="lp-section-lede">
                Ten primitives and boolean operations, plus the engineering
                features that make a part manufacturable. All dimensions are
                millimeters; operation trees are capped at depth 4 and 15
                nodes.
              </p>
            </header>

            <ul className="lp-tools">
              {OPERATIONS.map((op) => (
                <li key={op.type} className="lp-tool">
                  <OpGlyph type={op.type} />
                  <span className="lp-tool-name mono">{op.type}</span>
                  <span className="lp-tool-meta">{op.meta}</span>
                </li>
              ))}
            </ul>

            <div className="lp-features">
              <p className="lp-features-title mono">Engineering features</p>
              <ul>
                {FEATURES.map(([name, note]) => (
                  <li key={name}>
                    <span className="lp-feature-name mono">{name}</span>
                    <span className="lp-feature-note">{note}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="lp-section" id="assembly">
          <div className="lp-section-inner lp-assembly">
            <div className="lp-assembly-copy">
              <p className="lp-kicker mono">03 / assembly</p>
              <h2 className="lp-title">A parts bin that never calls the model.</h2>
              <p className="lp-section-lede">
                Pull an ESP32, a servo, an M3 screw or a chassis plate from the
                registry. Add, move, hide and re-parameterize without a prompt.
                Repeated fasteners are one definition with N poses.
              </p>

              <ul className="lp-library">
                {LIBRARY.map(([name, count, note]) => (
                  <li key={name}>
                    <span className="lp-library-name mono">{name}</span>
                    <span className="lp-library-count mono">{count}</span>
                    <span className="lp-library-note">{note}</span>
                  </li>
                ))}
              </ul>

              <div className="lp-zero">
                <span className="lp-zero-number">0</span>
                <span className="lp-zero-copy">
                  LLM calls for library inserts, placement, visibility and
                  numeric rebuilds.
                </span>
              </div>
            </div>

            <figure className="lp-assembly-visual">
              <div className="lp-visual-bar mono">
                <span>Assembly 04</span>
                <span>exploded / 6 parts</span>
              </div>
              <StackDrawing />
              <figcaption className="lp-visual-note mono">
                Objects stay separate in the scene; exports pass a compound,
                not a boolean union.
              </figcaption>
            </figure>
          </div>
        </section>

        <section className="lp-section lp-band" id="history">
          <div className="lp-section-inner">
            <header className="lp-section-head lp-split-head">
              <div>
                <p className="lp-kicker mono">04 / ledger</p>
                <h2 className="lp-title">The ledger never erases.</h2>
              </div>
              <p className="lp-section-lede">
                Every successful generate, modify, assembly edit and numeric
                adjustment appends a revision. Step back to any earlier state,
                branch a new child from it, and nothing is destroyed.
              </p>
            </header>

            <div className="lp-ledger-wrap">
              <ol className="lp-ledger">
                {LEDGER.map((row) => (
                  <li key={row.rev} className="lp-ledger-row">
                    <span className="lp-rev mono">{row.rev}</span>
                    <span className="lp-kind mono">{row.kind}</span>
                    <span className="lp-prompt">{row.prompt}</span>
                    <span className="lp-digest mono">{row.digest}</span>
                    <span className="lp-time mono">{row.time}</span>
                  </li>
                ))}
                <li className="lp-ledger-row lp-ledger-branch">
                  <span className="lp-rev mono">REV 04b</span>
                  <span className="lp-kind mono">Branch</span>
                  <span className="lp-prompt">
                    Re-open revision 04 and retune the wall without touching 05
                    or 06
                  </span>
                  <span className="lp-digest mono">sha a14e08</span>
                  <span className="lp-time mono">10:37</span>
                </li>
              </ol>

              <aside className="lp-ledger-aside">
                <p className="lp-aside-title mono">Retention</p>
                <p>
                  File links expire on ephemeral storage. Specifications do
                  not. One click re-mints STEP and STL from the stored spec —
                  no model call, no diff guard, no lost revision.
                </p>
                <p className="lp-aside-note mono">
                  Links ≈ 1 h · specs permanent
                </p>
              </aside>
            </div>
          </div>
        </section>

        <section className="lp-section" id="interface">
          <div className="lp-section-inner">
            <header className="lp-section-head">
              <p className="lp-kicker mono">05 / interface</p>
              <h2 className="lp-title">Structured data in. Real files out.</h2>
              <p className="lp-section-lede">
                A small HTTP surface with deterministic routes for the work
                that should never touch the model. Errors are controlled;
                secrets, paths and tracebacks stay in the server logs.
              </p>
            </header>

            <div className="lp-endpoints mono">
              <span>POST /generate</span>
              <span>POST /modify</span>
              <span>POST /rebuild</span>
              <span>POST /remint</span>
              <span>POST /assembly/*</span>
              <span>GET /download/&#123;token&#125;</span>
            </div>

            <div className="lp-code-grid">
              <div className="lp-code">
                <div className="lp-code-bar mono">
                  <span>request.json</span>
                  <span>POST /generate</span>
                </div>
                <pre className="lp-code-body">
                  <code>{`{
  `}<span className="lp-c-key">&quot;prompt&quot;</span>{`: `}<span className="lp-c-str">&quot;An L-bracket, 90 by 70 by 60 mm,
  with four Ø5 holes.&quot;</span>{`
}`}</code>
                </pre>
              </div>

              <div className="lp-code">
                <div className="lp-code-bar mono">
                  <span>response.json</span>
                  <span>200 · completed</span>
                </div>
                <pre className="lp-code-body">
                  <code>{`{
  `}<span className="lp-c-key">&quot;status&quot;</span>{`: `}<span className="lp-c-str">&quot;completed&quot;</span>{`,
  `}<span className="lp-c-key">&quot;specification&quot;</span>{`: {
    `}<span className="lp-c-key">&quot;document_type&quot;</span>{`: `}<span className="lp-c-str">&quot;3d_part&quot;</span>{`,
    `}<span className="lp-c-key">&quot;units&quot;</span>{`: `}<span className="lp-c-str">&quot;mm&quot;</span>{`,
    `}<span className="lp-c-key">&quot;operation&quot;</span>{`: { `}<span className="lp-c-str">&quot;type&quot;</span>{`: `}<span className="lp-c-str">&quot;part&quot;</span>{` }
  },
  `}<span className="lp-c-key">&quot;files&quot;</span>{`: {
    `}<span className="lp-c-key">&quot;step&quot;</span>{`: `}<span className="lp-c-str">&quot;/download/…&quot;</span>{`,
    `}<span className="lp-c-key">&quot;stl&quot;</span>{`: `}<span className="lp-c-str">&quot;/download/…&quot;</span>{`
  }
}`}</code>
                </pre>
              </div>
            </div>

            <ul className="lp-stats">
              {STATS.map(([number, label]) => (
                <li key={label} className="lp-stat">
                  <span className="lp-stat-number mono">{number}</span>
                  <span className="lp-stat-label mono">{label}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="lp-section lp-band" id="notes">
          <div className="lp-section-inner lp-notes">
            <header className="lp-section-head">
              <p className="lp-kicker mono">06 / notes</p>
              <h2 className="lp-title">Bench notes.</h2>
              <p className="lp-section-lede">
                Honest limits, quick answers, and the parts that are
                deliberately out of scope.
              </p>
            </header>

            <div className="lp-faq">
              {FAQ.map((item, index) => (
                <details
                  key={item.q}
                  className="lp-faq-item"
                  open={index === 0}
                >
                  <summary className="lp-faq-q">
                    <span className="lp-faq-index mono">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span>{item.q}</span>
                    <span className="lp-faq-mark" aria-hidden="true">
                      +
                    </span>
                  </summary>
                  <p className="lp-faq-a">{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-close">
          <div className="lp-close-inner">
            <p className="lp-kicker mono">07 / the bench</p>
            <h2 className="lp-close-title">
              Bring a part
              <br />
              to the bench<span className="lp-dot">.</span>
            </h2>
            <p className="lp-close-sub">
              Describe it plainly. Adjust it numerically. Download the solid.
              No account required to start.
            </p>
            <div className="lp-actions">
              <TrackedLink
                className="lp-cta lp-cta-lg"
                href="/workspace"
                event="landing_cta"
              >
                Open the bench <span aria-hidden="true">→</span>
              </TrackedLink>
              <Link className="lp-ghost mono" href="/signin">
                Create an account
              </Link>
            </div>
            <p className="lp-close-coords mono">
              X 000.00 · Y 000.00 · Z 000.00 ·<span> ready</span>
            </p>
          </div>
        </section>
      </main>

      <footer className="lp-foot">
        <div className="lp-foot-inner">
          <div className="lp-foot-brand">
            <div className="lp-foot-mark">
              <Image
                src="/logo-wordmark-light.png"
                alt="cgen"
                width={423}
                height={107}
                className="lp-brand-logo"
              />
            </div>
            <p>Language to solid. Built on CadQuery, kept in revisions.</p>
          </div>

          <nav className="lp-foot-col" aria-label="Bench">
            <p className="lp-foot-title mono">Bench</p>
            <Link href="/workspace">Open workspace</Link>
            <Link href="/signin">Sign in</Link>
            <a href="#history">Revision ledger</a>
          </nav>

          <nav className="lp-foot-col" aria-label="Reference">
            <p className="lp-foot-title mono">Reference</p>
            <a href="#sequence">Pipeline</a>
            <a href="#capabilities">Operations</a>
            <a href="#interface">API surface</a>
          </nav>

          <nav className="lp-foot-col" aria-label="Legal">
            <p className="lp-foot-title mono">Project</p>
            <a href="#notes">Limits &amp; notes</a>
            <a href="#assembly">Component registry</a>
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
            <Link href="/workspace">Try without an account</Link>
          </nav>
        </div>

        <div className="lp-foot-bottom mono">
          <span>cgen · MIT · schema 3.2</span>
          <span>Precision Bench / 2026</span>
        </div>
      </footer>
    </div>
  );
}
