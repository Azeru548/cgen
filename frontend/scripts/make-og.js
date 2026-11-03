/* Build public/og.png (1200x630) for social link previews.
 *
 * Launch posts live or die by the unfurl, so this is a designed card rather
 * than a screenshot: the product's own dark palette, a blueprint grid, the
 * one-line promise, and the three claims that make it credible.
 *
 * Rendered once at build-authoring time and committed as a static file — no
 * image processing at request time, same rule as the icons.
 */
const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "public", "og.png");

const W = 1200;
const H = 630;
const BG = "#0e1014";
const LINE = "#23262d";
const TEXT = "#f2f3f5";
const MUTED = "#9aa1ab";
const ACCENT = "#e04a55";

const grid = Array.from({ length: 20 }, (_, i) => {
  const x = i * 60;
  return `<line x1="${x}" y1="0" x2="${x}" y2="${H}" stroke="${LINE}" stroke-width="1" opacity="0.55"/>`;
}).join("");
const gridRows = Array.from({ length: 11 }, (_, i) => {
  const y = i * 60;
  return `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="${LINE}" stroke-width="1" opacity="0.55"/>`;
}).join("");

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">
  <rect width="${W}" height="${H}" fill="${BG}"/>
  ${grid}${gridRows}
  <rect x="0" y="0" width="${W}" height="${H}" fill="url(#fade)" />
  <defs>
    <linearGradient id="fade" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="${BG}" stop-opacity="0.1"/>
      <stop offset="1" stop-color="${BG}" stop-opacity="0.85"/>
    </linearGradient>
  </defs>

  <rect x="80" y="96" width="6" height="118" fill="${ACCENT}"/>

  <text x="112" y="128" font-family="monospace" font-size="20" letter-spacing="6"
        fill="${ACCENT}">CGEN</text>

  <text x="112" y="192" font-family="Arial, Helvetica, sans-serif" font-size="62"
        font-weight="700" fill="${TEXT}">Describe a part.</text>
  <text x="112" y="262" font-family="Arial, Helvetica, sans-serif" font-size="62"
        font-weight="700" fill="${TEXT}">Download STEP + STL.</text>

  <text x="112" y="330" font-family="Arial, Helvetica, sans-serif" font-size="26"
        fill="${MUTED}">Plain language in, validated CAD out. No code execution,</text>
  <text x="112" y="366" font-family="Arial, Helvetica, sans-serif" font-size="26"
        fill="${MUTED}">no hallucinated geometry.</text>

  <rect x="80" y="430" width="${W - 160}" height="1" fill="${LINE}"/>

  <text x="112" y="492" font-family="monospace" font-size="19" fill="${MUTED}">DETERMINISTIC · CADQUERY 2.8</text>
  <text x="452" y="492" font-family="monospace" font-size="19" fill="${MUTED}">SCHEMA v3.2 / v4.0</text>
  <text x="742" y="492" font-family="monospace" font-size="19" fill="${MUTED}">APPEND-ONLY REVISIONS</text>

  <rect x="0" y="${H - 8}" width="${W}" height="8" fill="${ACCENT}"/>
</svg>`;

(async () => {
  const png = await sharp(Buffer.from(svg)).png({ compressionLevel: 9 }).toBuffer();
  fs.writeFileSync(OUT, png);
  const meta = await sharp(OUT).metadata();
  console.log(`og.png ${meta.width}x${meta.height} ${png.length} bytes`);
})().catch((err) => {
  console.error("FAIL", err);
  process.exit(1);
});
