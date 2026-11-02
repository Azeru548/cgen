"use client";

/** Landing hero instrument: three real spec shapes drawn as orthographic
 *  working drawings, with the matching validated document beside them.
 *  Demo content only; every specimen is labelled as such. */
import { useState, type ReactNode } from "react";

interface Specimen {
  key: string;
  tab: string;
  name: string;
  serial: string;
  operation: string;
  prompt: string;
  dims: [string, string, string];
  feature: string;
  files: [string, string];
}

const SPECIMENS: Specimen[] = [
  {
    key: "bracket",
    tab: "Bracket",
    name: "L-bracket, bolt circle",
    serial: "SP-041",
    operation: "union → cut",
    prompt:
      "An L-bracket, 90 by 70 by 60 mm, 6 mm walls, with four Ø5 holes on a 60 mm bolt circle.",
    dims: ["90.0", "70.0", "60.0"],
    feature: "Ø5.0 × 4",
    files: ["bracket.step", "bracket.stl"],
  },
  {
    key: "enclosure",
    tab: "Enclosure",
    name: "Arduino enclosure",
    serial: "SP-118",
    operation: "part → shell",
    prompt:
      "An enclosure for an Arduino Uno, 120 by 80 by 40 mm, 2.5 mm shell, four M3 mounting holes, open top.",
    dims: ["120.0", "80.0", "40.0"],
    feature: "Ø3.2 × 4",
    files: ["enclosure.step", "enclosure.stl"],
  },
  {
    key: "shaft",
    tab: "Shaft",
    name: "Shaft, through-bore",
    serial: "SP-207",
    operation: "cut",
    prompt:
      "A 120 mm shaft, Ø30, with a Ø15 hole through the center.",
    dims: ["30.0", "30.0", "120.0"],
    feature: "Ø15.0 through",
    files: ["shaft.step", "shaft.stl"],
  },
];

function BracketDrawing() {
  return (
    <svg
      className="lp-draw"
      viewBox="0 0 420 300"
      role="img"
      aria-label="Front working drawing of an L-bracket with four mounting holes"
    >
      <title>L-bracket working drawing</title>
      <g className="lp-draw-part">
        <path d="M80 40 H290 V115 H165 V240 H80 Z" />
        <path d="M105 65 H265 V140 H140 V215 H105 Z" className="lp-draw-inner" />
        <circle cx="120" cy="85" r="8" />
        <circle cx="245" cy="85" r="8" />
        <circle cx="122" cy="165" r="8" />
        <circle cx="122" cy="200" r="8" />
      </g>
      <g className="lp-draw-dim">
        <path d="M80 270 H290" />
        <path d="M80 262 V278 M290 262 V278" />
        <text x="185" y="291" textAnchor="middle">
          90.0
        </text>
        <path d="M322 40 V240" />
        <path d="M314 40 H330 M314 240 H330" />
        <text x="342" y="145" transform="rotate(90 342 145)" textAnchor="middle">
          70.0
        </text>
      </g>
      <g className="lp-draw-note">
        <path d="M245 77 L278 40" className="lp-draw-leader" />
        <text x="284" y="36">
          Ø5.0 × 4
        </text>
        <path d="M122 173 L86 208" className="lp-draw-leader" />
        <text x="20" y="224">
          60.0 B.C.
        </text>
      </g>
    </svg>
  );
}

function EnclosureDrawing() {
  return (
    <svg
      className="lp-draw"
      viewBox="0 0 420 300"
      role="img"
      aria-label="Front working drawing of an open-top enclosure with four corner holes"
    >
      <title>Enclosure working drawing</title>
      <rect x="86" y="52" width="248" height="198" rx="8" className="lp-draw-part" />
      <rect
        x="108"
        y="80"
        width="204"
        height="148"
        rx="3"
        className="lp-draw-inner"
        strokeDasharray="6 4"
      />
      <circle cx="120" cy="86" r="6" className="lp-draw-part" />
      <circle cx="300" cy="86" r="6" className="lp-draw-part" />
      <circle cx="120" cy="216" r="6" className="lp-draw-part" />
      <circle cx="300" cy="216" r="6" className="lp-draw-part" />
      <g className="lp-draw-dim">
        <path d="M86 274 H334" />
        <path d="M86 266 V282 M334 266 V282" />
        <text x="210" y="295" textAnchor="middle">
          120.0
        </text>
        <path d="M362 52 V250" />
        <path d="M354 52 H370 M354 250 H370" />
        <text x="382" y="155" transform="rotate(90 382 155)" textAnchor="middle">
          80.0
        </text>
      </g>
      <g className="lp-draw-note">
        <path d="M210 80 L210 40" className="lp-draw-leader" />
        <text x="210" y="32" textAnchor="middle">
          OPEN TOP · 2.5 WALL
        </text>
        <path d="M300 80 L344 108" className="lp-draw-leader" />
        <text x="348" y="112">
          M3 × 4
        </text>
      </g>
    </svg>
  );
}

function ShaftDrawing() {
  return (
    <svg
      className="lp-draw"
      viewBox="0 0 420 300"
      role="img"
      aria-label="Side working drawing of a shaft with a through bore"
    >
      <title>Shaft working drawing</title>
      <rect x="52" y="92" width="296" height="116" rx="58" className="lp-draw-part" />
      <path d="M52 150 H348" className="lp-draw-center" strokeDasharray="12 5 3 5" />
      <path d="M76 128 H324" className="lp-draw-bore" strokeDasharray="7 5" />
      <path d="M76 172 H324" className="lp-draw-bore" strokeDasharray="7 5" />
      <path d="M64 150 L84 130 M64 150 L84 170" className="lp-draw-inner" />
      <path d="M336 150 L316 130 M336 150 L316 170" className="lp-draw-inner" />
      <g className="lp-draw-dim">
        <path d="M374 92 V208" />
        <path d="M366 92 H382 M366 208 H382" />
        <text x="394" y="155" transform="rotate(90 394 155)" textAnchor="middle">
          Ø30.0
        </text>
        <path d="M52 254 H348" />
        <path d="M52 246 V262 M348 246 V262" />
        <text x="200" y="277" textAnchor="middle">
          120.0
        </text>
      </g>
      <g className="lp-draw-note">
        <path d="M210 128 L210 48" className="lp-draw-leader" />
        <text x="210" y="40" textAnchor="middle">
          Ø15.0 THROUGH
        </text>
      </g>
    </svg>
  );
}

const DRAWINGS: Record<string, () => ReactNode> = {
  bracket: BracketDrawing,
  enclosure: EnclosureDrawing,
  shaft: ShaftDrawing,
};

export function SpecimenPanel() {
  const [active, setActive] = useState(0);
  const specimen = SPECIMENS[active];
  const Drawing = DRAWINGS[specimen.key];

  return (
    <div className="lp-inst">
      <div className="lp-inst-bar mono">
        <span>specimen {String(active + 1).padStart(2, "0")} / 03</span>
        <span className="lp-live">
          <i aria-hidden="true" /> validated
        </span>
      </div>

      <div className="lp-inst-tabs" role="tablist" aria-label="Example specimens">
        {SPECIMENS.map((item, index) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            id={`specimen-tab-${item.key}`}
            aria-selected={index === active}
            aria-controls="specimen-panel"
            className="lp-inst-tab"
            onClick={() => setActive(index)}
          >
            <span className="mono">{String(index + 1).padStart(2, "0")}</span>
            {item.tab}
          </button>
        ))}
      </div>

      <div
        className="lp-inst-well"
        id="specimen-panel"
        role="tabpanel"
        aria-labelledby={`specimen-tab-${specimen.key}`}
        aria-live="polite"
      >
        <div className="lp-inst-well-tag mono">
          <span>{specimen.serial}</span>
          <span>SECTION A–A</span>
        </div>
        <Drawing />
        <p className="lp-inst-prompt">{specimen.prompt}</p>
      </div>

      <dl className="lp-inst-dro">
        {(["X", "Y", "Z"] as const).map((axis, index) => (
          <div key={axis} className="lp-dro-row">
            <dt className="mono">{axis}</dt>
            <dd className="mono">
              {specimen.dims[index]}
              <span>mm</span>
            </dd>
          </div>
        ))}
        <div className="lp-dro-row lp-dro-wide">
          <dt className="mono">feature</dt>
          <dd className="mono">{specimen.feature}</dd>
        </div>
        <div className="lp-dro-row lp-dro-wide">
          <dt className="mono">operation</dt>
          <dd className="mono">{specimen.operation}</dd>
        </div>
      </dl>

      <div className="lp-inst-foot mono">
        <span>{specimen.name}</span>
        <span>
          {specimen.files[0]} · {specimen.files[1]}
        </span>
      </div>
      <p className="lp-inst-note mono">
        Example specimen, not a customer file
      </p>
    </div>
  );
}
