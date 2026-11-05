/** Pose math for scene objects. No React, no I/O.
 *
 *  Rotation convention matches the backend (`cad/assembly.py`): a rotation is
 *  XYZ Euler *degrees* applied to a vector as X first, then Y, then Z, i.e.
 *  v' = Rz · Ry · Rx · v. Keeping the same convention is what makes a local
 *  group rotation agree with the exported STEP/STL instead of only looking
 *  right in the viewport.
 */

export type Vec3 = [number, number, number];
export type Mat3 = [
  [number, number, number],
  [number, number, number],
  [number, number, number],
];

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

/** Round away float dust so a 90° turn is exactly 90, not 89.99999999999. */
function clean(value: number): number {
  const rounded = Math.round(value * 1e6) / 1e6;
  return Object.is(rounded, -0) ? 0 : rounded;
}

function cleanVec(v: Vec3): Vec3 {
  return [clean(v[0]), clean(v[1]), clean(v[2])];
}

function mul(a: Mat3, b: Mat3): Mat3 {
  const out: Mat3 = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ];
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      out[row][col] =
        a[row][0] * b[0][col] + a[row][1] * b[1][col] + a[row][2] * b[2][col];
    }
  }
  return out;
}

export function applyMatrix(m: Mat3, v: Vec3): Vec3 {
  return [
    m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
    m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
    m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
  ];
}

/** Rotation matrix for XYZ Euler degrees, composed Rz · Ry · Rx. */
export function eulerToMatrix(rotation: Vec3): Mat3 {
  const [rx, ry, rz] = rotation.map((a) => a * DEG);
  const [ca, sa] = [Math.cos(rx), Math.sin(rx)];
  const [cb, sb] = [Math.cos(ry), Math.sin(ry)];
  const [cc, sc] = [Math.cos(rz), Math.sin(rz)];
  return [
    [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa],
    [sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa],
    [-sb, cb * sa, cb * ca],
  ];
}

/** Inverse of `eulerToMatrix` (XYZ Euler degrees). */
export function matrixToEuler(m: Mat3): Vec3 {
  const sb = Math.max(-1, Math.min(1, -m[2][0]));
  const ry = Math.asin(sb);
  // Gimbal lock: cos(ry) ~ 0 means X and Z collapse onto the same axis.
  if (Math.abs(Math.cos(ry)) < 1e-9) {
    const rx = Math.atan2(m[1][2], m[1][1]);
    return cleanVec([rx * RAD, ry * RAD, 0]);
  }
  const rx = Math.atan2(m[2][1], m[2][2]);
  const rz = Math.atan2(m[1][0], m[0][0]);
  return cleanVec([rx * RAD, ry * RAD, rz * RAD]);
}

/** Rotate a point by XYZ Euler degrees, X first (backend convention). */
export function rotatePoint(point: Vec3, rotation: Vec3): Vec3 {
  const [x, y, z] = point;
  const [rx, ry, rz] = rotation.map((a) => a * DEG);
  let px = x;
  let py = y;
  let pz = z;
  if (rx) {
    const [c, s] = [Math.cos(rx), Math.sin(rx)];
    [py, pz] = [py * c - pz * s, py * s + pz * c];
  }
  if (ry) {
    const [c, s] = [Math.cos(ry), Math.sin(ry)];
    [px, pz] = [px * c + pz * s, -px * s + pz * c];
  }
  if (rz) {
    const [c, s] = [Math.cos(rz), Math.sin(rz)];
    [px, py] = [px * c - py * s, px * s + py * c];
  }
  return [px, py, pz];
}

/** Euler angles of `base` after applying `delta` in world space. */
export function composeRotation(delta: Vec3, base: Vec3): Vec3 {
  return matrixToEuler(mul(eulerToMatrix(delta), eulerToMatrix(base)));
}

/** Move a pose around `pivot` by `delta` degrees, keeping its own orientation. */
export function rotatePose(
  pose: { position: Vec3; rotation: Vec3 },
  delta: Vec3,
  pivot: Vec3,
): { position: Vec3; rotation: Vec3 } {
  const local: Vec3 = [
    pose.position[0] - pivot[0],
    pose.position[1] - pivot[1],
    pose.position[2] - pivot[2],
  ];
  const spun = rotatePoint(local, delta);
  return {
    position: cleanVec([
      pivot[0] + spun[0],
      pivot[1] + spun[1],
      pivot[2] + spun[2],
    ]),
    rotation: composeRotation(delta, pose.rotation),
  };
}

/** Average of the given points — the pivot a group rotates about. */
export function centroid(points: Vec3[]): Vec3 {
  if (points.length === 0) return [0, 0, 0];
  const sum = points.reduce<Vec3>(
    (acc, p) => [acc[0] + p[0], acc[1] + p[1], acc[2] + p[2]],
    [0, 0, 0],
  );
  return [
    clean(sum[0] / points.length),
    clean(sum[1] / points.length),
    clean(sum[2] / points.length),
  ];
}
