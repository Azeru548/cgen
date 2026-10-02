/* Build app/favicon.ico and app/apple-icon.png from public/logo-removebg.png.
 *
 * The logo is a wide wordmark on white; trim it, letterbox it onto a white
 * square so it stays legible at 16px, and wrap the PNGs in a classic ICO
 * container (PNG-in-ICO is supported by every current browser). */
const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const ROOT = path.resolve(__dirname, "..");
const LOGO = path.join(ROOT, "public", "logo-removebg.png");

function icoFromPngs(entries) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(entries.length, 4);

  const dirEntries = [];
  let offset = 6 + entries.length * 16;
  for (const { size, png } of entries) {
    const e = Buffer.alloc(16);
    e.writeUInt8(size === 256 ? 0 : size, 0); // width
    e.writeUInt8(size === 256 ? 0 : size, 1); // height
    e.writeUInt8(0, 2); // palette colours
    e.writeUInt8(0, 3); // reserved
    e.writeUInt16LE(1, 4); // colour planes
    e.writeUInt16LE(32, 6); // bits per pixel
    e.writeUInt32LE(png.length, 8);
    e.writeUInt32LE(offset, 12);
    offset += png.length;
    dirEntries.push(e);
  }

  return Buffer.concat([header, ...dirEntries, ...entries.map((e) => e.png)]);
}

(async () => {
  const faviconEntries = [];
  for (const size of [16, 32, 48]) {
    const png = await sharp(LOGO)
      .trim({ background: "#ffffff" })
      .resize(size, size, { fit: "contain", background: { r: 255, g: 255, b: 255 } })
      .png()
      .toBuffer();
    faviconEntries.push({ size, png });
  }

  const ico = icoFromPngs(faviconEntries);
  fs.writeFileSync(path.join(ROOT, "app", "favicon.ico"), ico);

  const apple = await sharp(LOGO)
    .trim({ background: "#ffffff" })
    .resize(180, 180, { fit: "contain", background: { r: 255, g: 255, b: 255 } })
    .png()
    .toBuffer();
  fs.writeFileSync(path.join(ROOT, "app", "apple-icon.png"), apple);

  console.log("favicon.ico", ico.length, "bytes; apple-icon.png", apple.length, "bytes");
})().catch((err) => {
  console.error("FAIL", err);
  process.exit(1);
});
