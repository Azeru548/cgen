/** The proof object on the landing page.
 *
 *  A real `3d_part` document in the shape the API actually returns, drawn as
 *  an instrument readout. Demonstration content only — it is labelled as such
 *  rather than presented as a customer result.
 */
const SPEC_ROWS: { label: string; value: string }[] = [
  { label: "document", value: "3d_part" },
  { label: "schema", value: "3.2" },
  { label: "units", value: "mm" },
];

const OPERATION: { label: string; value: string }[] = [
  { label: "type", value: "box" },
  { label: "width", value: "120.0" },
  { label: "depth", value: "80.0" },
  { label: "height", value: "40.0" },
];

const FEATURES: { label: string; value: string }[] = [
  { label: "hole_grid", value: "4 × Ø5.0 on 100 × 60" },
  { label: "shell", value: "2.5 wall, open top" },
];

const EXPORTS: { label: string; value: string }[] = [
  { label: "STEP", value: "casing.step" },
  { label: "STL", value: "casing.stl" },
];

export function SpecReadout() {
  return (
    <figure className="spec-card">
      <figcaption className="spec-card-bar mono">
        <span>request · 8f2c41a9</span>
        <span className="spec-card-status">validated</span>
      </figcaption>

      <div className="spec-card-prompt">
        <span className="spec-card-prompt-tag mono">prompt</span>
        <p>
          An enclosure for an Arduino Uno, 120 by 80 by 40 millimetres, with
          four mounting holes and an open top.
        </p>
      </div>

      <dl className="spec-rows">
        {SPEC_ROWS.map((row) => (
          <div key={row.label} className="spec-row">
            <dt className="mono">{row.label}</dt>
            <dd className="mono">{row.value}</dd>
          </div>
        ))}
      </dl>

      <div className="spec-block">
        <span className="spec-block-tag mono">operation</span>
        <dl className="spec-rows">
          {OPERATION.map((row) => (
            <div key={row.label} className="spec-row">
              <dt className="mono">{row.label}</dt>
              <dd className="mono">{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="spec-block">
        <span className="spec-block-tag mono">features</span>
        <ul className="spec-list">
          {FEATURES.map((item) => (
            <li key={item.label} className="mono">
              <span className="spec-list-key">{item.label}</span>
              {item.value}
            </li>
          ))}
        </ul>
      </div>

      <div className="spec-block spec-block-exports">
        <span className="spec-block-tag mono">exported</span>
        <ul className="spec-list">
          {EXPORTS.map((item) => (
            <li key={item.label} className="mono">
              <span className="spec-list-key">{item.label}</span>
              {item.value}
            </li>
          ))}
        </ul>
      </div>

      <p className="spec-card-note mono">Example specification, not a customer file</p>
    </figure>
  );
}
