// Terrain and unit icons, drawn procedurally.
//
// Original shapes, not sampled from the game's art. That is a hard requirement,
// not a preference: ripped sprites are what would make the archive and the
// website a legal problem, and they are the first thing anyone will be tempted
// to "improve" this file with. Don't.
//
// Everything is drawn in a 0..1 box and scaled, so icons stay sharp from a
// 12px thumbnail tile to a 72px zoomed one. Each function takes
// (ctx, x, y, s, ink) where s is the tile size and ink is the stroke colour.

function path(ctx, s, x, y, pts, close = true) {
  ctx.beginPath();
  ctx.moveTo(x + pts[0] * s, y + pts[1] * s);
  for (let i = 2; i < pts.length; i += 2) ctx.lineTo(x + pts[i] * s, y + pts[i + 1] * s);
  if (close) ctx.closePath();
}

function box(ctx, s, x, y, bx, by, bw, bh) {
  ctx.beginPath();
  ctx.rect(x + bx * s, y + by * s, bw * s, bh * s);
}

function disc(ctx, s, x, y, cx, cy, r) {
  ctx.beginPath();
  ctx.arc(x + cx * s, y + cy * s, r * s, 0, Math.PI * 2);
}

// A cannon is defined by where it points, so its icon has to say so. These
// take the facing as a fifth argument; every other icon ignores it.
function cannon(ctx, x, y, s, ink, facing, barrel) {
  const turn = { N: -Math.PI / 2, E: 0, S: Math.PI / 2, W: Math.PI }[facing || 'N'];
  ctx.save();
  ctx.translate(x + s / 2, y + s / 2);
  ctx.rotate(turn);
  ctx.fillStyle = ink;
  // Body, then a barrel along +x, which the rotation points the right way.
  ctx.beginPath();
  ctx.arc(0, 0, s * 0.26, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillRect(0, -s * barrel * 0.5, s * 0.46, s * barrel);
  ctx.restore();
}

/**
 * A length of pipe, drawn along whichever sides it joins.
 *
 * Takes the connection set the renderer already works out, so a pipe reads as
 * a run rather than a grey square. `seam` is the breakable joint: the same
 * tube with a collar, and lighter, which is how the game distinguishes them.
 */
function pipeRun(ctx, x, y, s, dirs, body, edge, collar) {
  const mid = 0.5, half = 0.19;
  const legs = {
    N: [mid - half, 0, half * 2, mid + half],
    S: [mid - half, mid - half, half * 2, mid + half],
    W: [0, mid - half, mid + half, half * 2],
    E: [mid - half, mid - half, mid + half, half * 2],
  };
  const joined = dirs ? dirs.split('+').filter(Boolean) : [];
  ctx.fillStyle = body;
  if (!joined.length) {
    // An isolated pipe still has to look like pipe, not like a blank tile.
    box(ctx, s, x, y, mid - half, mid - half, half * 2, half * 2);
    ctx.fill();
  }
  for (const d of joined) {
    const [bx, by, bw, bh] = legs[d];
    box(ctx, s, x, y, bx, by, bw, bh);
    ctx.fill();
  }
  // A highlight along the top of every horizontal run gives it a round edge.
  ctx.fillStyle = edge;
  for (const d of joined) {
    if (d === 'W' || d === 'E') {
      const [bx, , bw] = legs[d];
      box(ctx, s, x, y, bx, mid - half, bw, 0.06);
      ctx.fill();
    }
  }
  if (collar) {
    ctx.fillStyle = collar;
    const vertical = joined.includes('N') || joined.includes('S');
    if (vertical) box(ctx, s, x, y, mid - half - 0.05, mid - 0.07, half * 2 + 0.1, 0.14);
    else box(ctx, s, x, y, mid - 0.07, mid - half - 0.05, 0.14, half * 2 + 0.1);
    ctx.fill();
  }
}

// --- terrain ---------------------------------------------------------------

export const TERRAIN_ICONS = {
  // Black Cannon (3x3), Death Ray (3x3) and Mini Cannon all aim.
  524288(ctx, x, y, s, ink, facing) { cannon(ctx, x, y, s, ink, facing, 0.30); },
  8388608(ctx, x, y, s, ink, facing) { cannon(ctx, x, y, s, ink, facing, 0.20); },
  1048576(ctx, x, y, s, ink, facing) { cannon(ctx, x, y, s, ink, facing, 0.16); },

  // Mountain: two peaks with snow caps.
  4(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    path(ctx, s, x, y, [0.12, 0.80, 0.40, 0.26, 0.68, 0.80]);
    ctx.fill();
    path(ctx, s, x, y, [0.50, 0.80, 0.72, 0.38, 0.90, 0.80]);
    ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,0.7)';
    path(ctx, s, x, y, [0.30, 0.46, 0.40, 0.26, 0.50, 0.46, 0.40, 0.40]);
    ctx.fill();
  },
  // Woods: two conifers.
  8(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    for (const cx of [0.33, 0.67]) {
      path(ctx, s, x, y, [cx - 0.18, 0.62, cx, 0.20, cx + 0.18, 0.62]);
      ctx.fill();
      path(ctx, s, x, y, [cx - 0.22, 0.80, cx, 0.40, cx + 0.22, 0.80]);
      ctx.fill();
    }
  },
  // Reef: three rounded rocks breaking the surface.
  64(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    disc(ctx, s, x, y, 0.34, 0.58, 0.15); ctx.fill();
    disc(ctx, s, x, y, 0.62, 0.50, 0.12); ctx.fill();
    disc(ctx, s, x, y, 0.52, 0.70, 0.13); ctx.fill();
  },
  // Pipe: dark metal, welded shut, impassable.
  32768(ctx, x, y, s, ink, dirs) {
    pipeRun(ctx, x, y, s, dirs, '#5d6470', '#8f97a4', null);
  },
  // Pipe seam: the same run with a collar, lighter because it can be broken.
  65536(ctx, x, y, s, ink, dirs) {
    pipeRun(ctx, x, y, s, dirs, '#6d7684', '#a8b0bd', '#cfd6e0');
  },
  // Silo: a rocket nose on a pad.
  33554432(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    path(ctx, s, x, y, [0.50, 0.18, 0.64, 0.50, 0.64, 0.68, 0.36, 0.68, 0.36, 0.50]);
    ctx.fill();
    box(ctx, s, x, y, 0.26, 0.70, 0.48, 0.10);
    ctx.fill();
  },
};

// Properties share a building language so ownership reads before type does.
function roof(ctx, x, y, s, ink, tall) {
  ctx.fillStyle = ink;
  const top = tall ? 0.16 : 0.34;
  box(ctx, s, x, y, 0.24, top, 0.52, 0.80 - top);
  ctx.fill();
}

export const PROPERTY_ICONS = {
  // HQ: a tower with a flag.
  512(ctx, x, y, s, ink) {
    roof(ctx, x, y, s, ink, true);
    ctx.fillStyle = ink;
    path(ctx, s, x, y, [0.50, 0.04, 0.78, 0.13, 0.50, 0.22]);
    ctx.fill();
    box(ctx, s, x, y, 0.47, 0.04, 0.05, 0.22);
    ctx.fill();
  },
  // City: two blocks of differing height with windows.
  1024(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    box(ctx, s, x, y, 0.16, 0.42, 0.30, 0.38); ctx.fill();
    box(ctx, s, x, y, 0.52, 0.26, 0.32, 0.54); ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    for (const [bx, by] of [[0.23, 0.52], [0.34, 0.52], [0.59, 0.36], [0.71, 0.36], [0.59, 0.52], [0.71, 0.52]]) {
      box(ctx, s, x, y, bx, by, 0.07, 0.09);
      ctx.fill();
    }
  },
  // Base: a hangar arch with a door.
  2048(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    ctx.beginPath();
    ctx.moveTo(x + 0.16 * s, y + 0.78 * s);
    ctx.lineTo(x + 0.16 * s, y + 0.46 * s);
    ctx.arc(x + 0.50 * s, y + 0.46 * s, 0.34 * s, Math.PI, 0);
    ctx.lineTo(x + 0.84 * s, y + 0.78 * s);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,0.6)';
    box(ctx, s, x, y, 0.40, 0.54, 0.20, 0.24);
    ctx.fill();
  },
  // Airport: a plan-view aircraft.
  4096(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    path(ctx, s, x, y, [0.50, 0.14, 0.58, 0.44, 0.88, 0.60, 0.88, 0.68,
                        0.56, 0.60, 0.56, 0.74, 0.66, 0.82, 0.66, 0.88,
                        0.34, 0.88, 0.34, 0.82, 0.44, 0.74, 0.44, 0.60,
                        0.12, 0.68, 0.12, 0.60, 0.42, 0.44]);
    ctx.fill();
  },
  // Seaport: an anchor.
  8192(ctx, x, y, s, ink) {
    ctx.strokeStyle = ink;
    ctx.lineWidth = Math.max(1, s * 0.09);
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(x + 0.50 * s, y + 0.30 * s);
    ctx.lineTo(x + 0.50 * s, y + 0.80 * s);
    ctx.moveTo(x + 0.30 * s, y + 0.42 * s);
    ctx.lineTo(x + 0.70 * s, y + 0.42 * s);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x + 0.50 * s, y + 0.62 * s, 0.26 * s, 0.25 * Math.PI, 0.75 * Math.PI);
    ctx.stroke();
    ctx.fillStyle = ink;
    disc(ctx, s, x, y, 0.50, 0.24, 0.10);
    ctx.fill();
  },
  // Com Tower: a mast with signal arcs.
  134217728(ctx, x, y, s, ink) {
    ctx.fillStyle = ink;
    path(ctx, s, x, y, [0.40, 0.84, 0.47, 0.32, 0.53, 0.32, 0.60, 0.84]);
    ctx.fill();
    ctx.strokeStyle = ink;
    ctx.lineWidth = Math.max(1, s * 0.07);
    for (const r of [0.16, 0.27]) {
      ctx.beginPath();
      ctx.arc(x + 0.50 * s, y + 0.30 * s, r * s, 1.15 * Math.PI, 1.85 * Math.PI);
      ctx.stroke();
    }
  },
};

// --- units -----------------------------------------------------------------
//
// Grouped by silhouette: at a glance you should read "foot / vehicle / gun /
// plane / helicopter / ship", and only then which one. Within a group the
// shapes differ enough to tell apart when zoomed in.

function treads(ctx, x, y, s, ink) {
  ctx.fillStyle = ink;
  box(ctx, s, x, y, 0.10, 0.62, 0.80, 0.18);
  ctx.fill();
}

function foot(ctx, x, y, s, ink, pack) {
  ctx.fillStyle = ink;
  disc(ctx, s, x, y, 0.50, 0.26, 0.14); ctx.fill();
  path(ctx, s, x, y, [0.38, 0.84, 0.42, 0.44, 0.58, 0.44, 0.62, 0.84]);
  ctx.fill();
  if (pack) { box(ctx, s, x, y, 0.62, 0.44, 0.16, 0.22); ctx.fill(); }
}

function hull(ctx, x, y, s, ink, tower) {
  ctx.fillStyle = ink;
  path(ctx, s, x, y, [0.10, 0.54, 0.90, 0.54, 0.76, 0.80, 0.24, 0.80]);
  ctx.fill();
  if (tower) { box(ctx, s, x, y, 0.40, 0.28, 0.20, 0.26); ctx.fill(); }
}

function barrel(ctx, x, y, s, ink, len, rise) {
  ctx.fillStyle = ink;
  ctx.save();
  ctx.translate(x + 0.50 * s, y + 0.46 * s);
  ctx.rotate(-rise);
  ctx.fillRect(0, -0.055 * s, len * s, 0.11 * s);
  ctx.restore();
}

export const UNIT_ICONS = {
  9(c, x, y, s, k) { foot(c, x, y, s, k, false); },                    // Infantry
  11(c, x, y, s, k) { foot(c, x, y, s, k, true); },                    // Mech
  14(c, x, y, s, k) {                                                  // Recon
    c.fillStyle = k;
    path(c, s, x, y, [0.12, 0.62, 0.30, 0.38, 0.70, 0.38, 0.88, 0.62]); c.fill();
    disc(c, s, x, y, 0.28, 0.70, 0.12); c.fill();
    disc(c, s, x, y, 0.72, 0.70, 0.12); c.fill();
  },
  2(c, x, y, s, k) {                                                   // APC
    c.fillStyle = k;
    box(c, s, x, y, 0.14, 0.32, 0.72, 0.30); c.fill();
    treads(c, x, y, s, k);
  },
  17(c, x, y, s, k) { treads(c, x, y, s, k); barrel(c, x, y, s, k, 0.42, 0); hull(c, x, y, s, k, true); },
  12(c, x, y, s, k) { treads(c, x, y, s, k); barrel(c, x, y, s, k, 0.48, 0); hull(c, x, y, s, k, true);
                      c.fillStyle = k; box(c, s, x, y, 0.36, 0.20, 0.28, 0.14); c.fill(); },
  19(c, x, y, s, k) { treads(c, x, y, s, k); barrel(c, x, y, s, k, 0.50, 0.12);
                      barrel(c, x, y, s, k, 0.50, -0.06); hull(c, x, y, s, k, true); },
  3(c, x, y, s, k) { treads(c, x, y, s, k); barrel(c, x, y, s, k, 0.46, 0.55); hull(c, x, y, s, k, false); },
  15(c, x, y, s, k) {                                                  // Rocket
    treads(c, x, y, s, k); hull(c, x, y, s, k, false);
    c.fillStyle = k;
    c.save(); c.translate(x + 0.44 * s, y + 0.42 * s); c.rotate(-0.5);
    c.fillRect(0, -0.16 * s, 0.46 * s, 0.11 * s);
    c.fillRect(0, 0.02 * s, 0.46 * s, 0.11 * s);
    c.restore();
  },
  13(c, x, y, s, k) {                                                  // Missile
    treads(c, x, y, s, k); hull(c, x, y, s, k, false);
    c.fillStyle = k;
    c.save(); c.translate(x + 0.42 * s, y + 0.44 * s); c.rotate(-0.85);
    c.fillRect(0, -0.09 * s, 0.42 * s, 0.18 * s); c.restore();
  },
  1(c, x, y, s, k) {                                                   // Anti-Air
    treads(c, x, y, s, k); hull(c, x, y, s, k, false);
    barrel(c, x, y, s, k, 0.40, 0.95); barrel(c, x, y, s, k, 0.40, 0.70);
  },
  8(c, x, y, s, k) {                                                   // Fighter
    c.fillStyle = k;
    path(c, s, x, y, [0.50, 0.10, 0.66, 0.56, 0.92, 0.72, 0.50, 0.66,
                      0.08, 0.72, 0.34, 0.56]); c.fill();
  },
  6(c, x, y, s, k) {                                                   // Bomber
    c.fillStyle = k;
    path(c, s, x, y, [0.50, 0.14, 0.64, 0.48, 0.94, 0.62, 0.94, 0.72,
                      0.50, 0.62, 0.06, 0.72, 0.06, 0.62, 0.36, 0.48]); c.fill();
    disc(c, s, x, y, 0.50, 0.62, 0.13); c.fill();
  },
  4(c, x, y, s, k) {                                                   // Battle Copter
    c.fillStyle = k;
    box(c, s, x, y, 0.10, 0.20, 0.80, 0.07); c.fill();
    path(c, s, x, y, [0.28, 0.44, 0.62, 0.40, 0.78, 0.54, 0.62, 0.72, 0.30, 0.70]); c.fill();
    box(c, s, x, y, 0.72, 0.50, 0.20, 0.06); c.fill();
  },
  18(c, x, y, s, k) {                                                  // Transport Copter
    c.fillStyle = k;
    box(c, s, x, y, 0.10, 0.20, 0.80, 0.07); c.fill();
    box(c, s, x, y, 0.28, 0.42, 0.44, 0.30); c.fill();
    box(c, s, x, y, 0.70, 0.50, 0.22, 0.06); c.fill();
  },
  5(c, x, y, s, k) {                                                   // Battleship
    hull(c, x, y, s, k, false);
    c.fillStyle = k;
    box(c, s, x, y, 0.40, 0.28, 0.18, 0.26); c.fill();
    barrel(c, x, y, s, k, 0.40, 0.45);
  },
  7(c, x, y, s, k) {                                                   // Cruiser
    hull(c, x, y, s, k, false);
    c.fillStyle = k;
    box(c, s, x, y, 0.42, 0.24, 0.14, 0.30); c.fill();
    disc(c, s, x, y, 0.68, 0.42, 0.09); c.fill();
  },
  16(c, x, y, s, k) {                                                  // Submarine
    c.fillStyle = k;
    ctxEllipse(c, x + 0.50 * s, y + 0.62 * s, 0.40 * s, 0.16 * s); c.fill();
    box(c, s, x, y, 0.44, 0.34, 0.14, 0.18); c.fill();
    box(c, s, x, y, 0.49, 0.22, 0.04, 0.14); c.fill();
  },
  10(c, x, y, s, k) {                                                  // Lander
    c.fillStyle = k;
    path(c, s, x, y, [0.08, 0.46, 0.92, 0.46, 0.80, 0.78, 0.20, 0.78]); c.fill();
    box(c, s, x, y, 0.30, 0.32, 0.40, 0.14); c.fill();
  },
};

function ctxEllipse(c, cx, cy, rx, ry) {
  c.beginPath();
  c.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
}
