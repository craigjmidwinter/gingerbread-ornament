# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Craig Midwinter
"""
Pure-numpy image -> gingerbread ornament geometry core.

No bpy imports in here so the pipeline can be unit-tested headless. Everything
works on a regular pixel grid ("working grid"); heights are computed from exact-ish
Euclidean distance fields (jump flooding) so icing gets a rounded, piped profile and
the cookie gets a rounded top edge.
"""
import math
import numpy as np


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------

DEFAULTS = dict(
    size_mm=80.0,            # longest side of the whole finished ornament outline (hanging-hole tab included)
    geometry=2,              # 2 (after the 0.5.0 test build): Size includes the tab, gaps kept between lines, one-piece strokes;
                             # 1 = the 0.5.0-and-earlier geometry (kept for re-analysing older .blend files)
    res_mm=0.15,             # working grid pixel size
    ink_threshold=0.5,       # luminance below this is a line
    line_boost_mm=0.30,      # grow every icing line by this much on each side
    gap_mm=0.42,             # ... but keep at least this much bare cookie between lines the drawing keeps apart
    gap_min_mm=0.3,          # gaps inside one line drawing narrower than this may close (hairlines, corners)
    dot_mm2=0.5,             # drawing pieces smaller than this are dots (may join each other into a beaded line)
    dot_claim_mm=0.2,        # a dot next to a line keeps this much more of the gap between them
    hole_keep_mm2=0.3,       # enclosed white cells of the drawing at least this big stay open (not iced over)
    min_detail_mm=0.5,       # stroke slivers narrower than this go to the neighbouring stroke
    min_part_width_mm=0.45,  # a whole stroke narrower than this joins its neighbour, grows into a dot, or goes
    min_part_floor_mm=0.34,  # ... a dot hemmed in by gaps stays if it is this wide (grid estimate; ~0.45 as meshed)
    min_region_mm2=0.8,      # enclosed regions smaller than this become icing
    cookie_margin_mm=2.2,    # cookie edge distance beyond the outermost line
    cookie_smooth_mm=2.5,    # rounding of concave notches in the cookie outline
    cookie_thickness_mm=4.0,
    cookie_bevel_mm=1.6,     # radius of the rounded top edge of the cookie
    line_height_mm=1.2,      # piped icing height above the cookie
    line_edge_mm=0.3,        # piped icing height at its edge
    smooth_edges=True,       # smooth pixel stair-steps out of every outline
    outline_smooth_mm=0.15,  # blur radius for the line outlines (removes raster stair-steps; 0 = off)
    line_split='STROKES',    # icing line parts: 'ONE' part, connected 'PIECES', or 'STROKES' (cut at junctions)
    split_lines=False,       # legacy alias for line_split='PIECES'
    # Painted (flush) icing: one flat surface across painted regions and the lines between them
    flush_height_mm=0.8,     # height of the painted surface above the cookie
    flush_edge_mm=0.4,       # height where the painted surface meets bare cookie
    flush_round_mm=0.4,      # width of that rounded-off edge
    seamless=False,          # Seamless look: painted surface dead flat (no rounding), every line flush with it
    max_filaments=0,         # merge region colours to fit one AMS (0 = no limit)
    line_round_mm=0.6,       # horizontal radius of the piped bead profile
    fill_height_mm=0.8,      # flooded (coloured) region height above the cookie
    fill_edge_mm=0.4,
    fill_round_mm=0.9,
    hole=True,
    hole_diameter_mm=4.5,
    hole_ring_mm=2.6,        # cookie wall around the hole
    hole_clearance_mm=1.0,   # gap between icing and hole edge
    white_cutoff=0.82,       # coloured-image colour counts as "uncoloured" above this
    colour_merge=0.18,       # RGB distance to merge region colours into one filament
)


# ----------------------------------------------------------------------------
# Distance transform (jump flooding, numpy vectorised)
# ----------------------------------------------------------------------------

def _shift(a, dy, dx, fill):
    """out[i, j] = a[i + dy, j + dx] (fill outside)."""
    h, w = a.shape
    out = np.full_like(a, fill)
    ys0, ys1 = max(0, -dy), min(h, h - dy)
    xs0, xs1 = max(0, -dx), min(w, w - dx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = a[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx]
    return out


def edt(seeds, return_index=False):
    """Euclidean distance (pixels) from every pixel to the nearest True seed.
    With return_index, also the (row, col) of that nearest seed."""
    h, w = seeds.shape
    BIG = np.int32(1 << 20)
    ny = np.where(seeds, np.arange(h, dtype=np.int32)[:, None], BIG).astype(np.int32)
    nx = np.where(seeds, np.arange(w, dtype=np.int32)[None, :], BIG).astype(np.int32)
    if not seeds.any():
        far = np.full((h, w), 1e9, dtype=np.float32)
        return (far, ny, nx) if return_index else far
    iy = np.arange(h, dtype=np.int64)[:, None]
    ix = np.arange(w, dtype=np.int64)[None, :]

    def d2(cy, cx):
        return (cy.astype(np.int64) - iy) ** 2 + (cx.astype(np.int64) - ix) ** 2

    best = d2(ny, nx)
    k = 1 << int(math.ceil(math.log2(max(h, w))))
    steps = []
    while k >= 1:
        k //= 2
        if k >= 1:
            steps.append(k)
    steps += [2, 1]
    for k in steps:
        for dy in (-k, 0, k):
            for dx in (-k, 0, k):
                if dy == 0 and dx == 0:
                    continue
                cy = _shift(ny, dy, dx, BIG)
                cx = _shift(nx, dy, dx, BIG)
                dd = d2(cy, cx)
                m = dd < best
                if m.any():
                    best = np.where(m, dd, best)
                    ny = np.where(m, cy, ny)
                    nx = np.where(m, cx, nx)
    dist = np.sqrt(best.astype(np.float64)).astype(np.float32)
    return (dist, ny, nx) if return_index else dist


def dilate(mask, r_px):
    return edt(mask) <= r_px


def erode(mask, r_px):
    return ~(edt(~mask) <= r_px)


def close(mask, r_px):
    return erode(dilate(mask, r_px), r_px)


def boundary_seeds(labels):
    """Pixels with a 4-neighbour of a different label."""
    b = np.zeros(labels.shape, dtype=bool)
    b[1:, :] |= labels[1:, :] != labels[:-1, :]
    b[:-1, :] |= labels[:-1, :] != labels[1:, :]
    b[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    b[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    return b


def inner_distance(labels):
    """Distance (px) from each pixel centre to the edge of its own label region."""
    return edt(boundary_seeds(labels)) + 0.5


# ----------------------------------------------------------------------------
# Connected components (run-length union-find, 4-connectivity)
# ----------------------------------------------------------------------------

def label_components(mask, diag=False):
    h, w = mask.shape
    g = 1 if diag else 0  # widen runs by one pixel when matching rows -> 8-connectivity
    parent = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    rows = []
    for i in range(h):
        r = np.concatenate(([0], mask[i].view(np.int8), [0]))
        d = np.diff(r)
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        ids = list(range(len(parent), len(parent) + len(starts)))
        parent.extend(ids)
        rows.append((starts, ends, ids))
        if i > 0:
            ps, pe, pid = rows[i - 1]
            a = b = 0
            while a < len(starts) and b < len(ps):
                if starts[a] - g < pe[b] and ps[b] < ends[a] + g:
                    ra, rb = find(ids[a]), find(pid[b])
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
                if ends[a] + g < pe[b]:
                    a += 1
                else:
                    b += 1
    labels = np.zeros((h, w), dtype=np.int32)
    remap = {}
    for i, (starts, ends, ids) in enumerate(rows):
        for s, e, rid in zip(starts, ends, ids):
            root = find(rid)
            lab = remap.get(root)
            if lab is None:
                lab = len(remap) + 1
                remap[root] = lab
            labels[i, s:e] = lab
    return labels, len(remap)


# ----------------------------------------------------------------------------
# Resampling
# ----------------------------------------------------------------------------

def _box_sample(img, ys, xs, half):
    """Average img (H,W[,C]) over boxes centred at (ys, xs) source coords, radius half."""
    h, w = img.shape[:2]
    if img.ndim == 2:
        img = img[:, :, None]
    ii = np.zeros((h + 1, w + 1, img.shape[2]), dtype=np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(img, axis=0), axis=1)
    y0 = np.clip(np.floor(ys - half).astype(np.int64), 0, h)
    y1 = np.clip(np.floor(ys + half).astype(np.int64) + 1, 0, h)
    x0 = np.clip(np.floor(xs - half).astype(np.int64), 0, w)
    x1 = np.clip(np.floor(xs + half).astype(np.int64) + 1, 0, w)
    Y0, X0 = np.meshgrid(y0, x0, indexing='ij')
    Y1, X1 = np.meshgrid(y1, x1, indexing='ij')
    s = ii[Y1, X1] - ii[Y0, X1] - ii[Y1, X0] + ii[Y0, X0]
    area = np.maximum((Y1 - Y0) * (X1 - X0), 1)[..., None]
    out = s / area
    # Outside the image: paper white.
    outside = (Y1 <= Y0) | (X1 <= X0)
    out[outside] = 1.0
    return out


def _bilinear(img, ys, xs):
    """Bilinear sample a 2D image at (ys, xs) source pixel coords; outside = paper white."""
    h, w = img.shape
    y = np.clip(ys, 0, h - 1)
    x = np.clip(xs, 0, w - 1)
    y0 = np.floor(y).astype(np.int64); x0 = np.floor(x).astype(np.int64)
    y1 = np.minimum(y0 + 1, h - 1); x1 = np.minimum(x0 + 1, w - 1)
    fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
    out = (img[y0][:, x0] * (1 - fy) * (1 - fx) + img[y0][:, x1] * (1 - fy) * fx +
           img[y1][:, x0] * fy * (1 - fx) + img[y1][:, x1] * fy * fx)
    out[(ys < -0.5) | (ys > h - 0.5), :] = 1.0
    out[:, (xs < -0.5) | (xs > w - 0.5)] = 1.0
    return out


def gaussian_blur(a, sigma):
    """Separable Gaussian blur (edge-clamped), sigma in pixels."""
    r = int(math.ceil(3 * sigma))
    if r < 1:
        return a
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    h, w = a.shape
    p = np.pad(a, ((0, 0), (r, r)), mode='edge')
    a = sum(k[i] * p[:, i:i + w] for i in range(2 * r + 1))
    p = np.pad(a, ((r, r), (0, 0)), mode='edge')
    return sum(k[i] * p[i:i + h, :] for i in range(2 * r + 1))


def lattice_dist(mask, lat, px):
    """Distance (mm) from every interior corner of mask to the mask's outline, measured on the
    smoothed corner lattice, so icing heights follow the smooth outline, not the pixel steps.

    Corners on the outline (and outside) get 0. Interior corners stay on the pixel grid, so
    the result is a smooth function of a smooth boundary: no ribs along the piping.
    """
    cc = corner_count(mask)
    seeds = (cc > 0) & (cc < 4)
    if lat is None:
        Y, X = np.mgrid[0:cc.shape[0], 0:cc.shape[1]].astype(np.float64)
    else:
        X, Y = lat
    _, ny, nx = edt(seeds, return_index=True)
    h, w = cc.shape
    ny = np.clip(ny, 0, h - 1); nx = np.clip(nx, 0, w - 1)
    ax, ay = X[ny, nx], Y[ny, nx]
    best = np.hypot(X - ax, Y - ay)
    # refine against the outline segments leaving the nearest outline corner
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if not (dy or dx):
                continue
            by_ = np.clip(ny + dy, 0, h - 1); bx_ = np.clip(nx + dx, 0, w - 1)
            ok = seeds[by_, bx_]
            bx, by = X[by_, bx_], Y[by_, bx_]
            ex, ey = bx - ax, by - ay
            L2 = np.maximum(ex * ex + ey * ey, 1e-12)
            t = np.clip(((X - ax) * ex + (Y - ay) * ey) / L2, 0, 1)
            dseg = np.hypot(X - ax - t * ex, Y - ay - t * ey)
            best = np.where(ok, np.minimum(best, dseg), best)
    return np.where(cc == 4, best * px, 0.0)


def smooth_mask(mask, sigma):
    """Smooth a mask's outline: blur its signed distance field and re-threshold at 0.

    Rounds off stair-steps (from a low-res or jaggy source) without the shrinkage a plain
    blur gives. The eroded core of the original is kept so thin lines can never break.
    """
    if sigma <= 0 or not mask.any():
        return mask
    sd = edt(mask).astype(np.float64) - edt(~mask)   # >0 outside, <0 inside (pixels)
    out = gaussian_blur(sd, sigma) < 0
    lost = mask & ~out
    if lost.any():
        out |= skeletonize(mask) & mask
    return out


def separation_carve(ink, grow_px, gap_px, wmin_px, small_px=0, dot_claim_px=0.0, sharp=0.6,
                     min_len_px=6, pieces=None, hole_px=0, debug=None):
    """Constrained dilation: where thickening `ink` by grow_px would close a gap that the drawing
    keeps open, the pixels to keep bare so that a gap of gap_px remains. Returns a bool mask.

    The gaps follow the medial axis of the drawing's background (feature transforms):
      * between two different ink pieces (`pieces`: 8-connected parts of the drawing at its own
        resolution, so a dot that touches a line only after resampling is still its own piece;
        default: 8-connected parts of `ink`): always kept apart, eating into the ink
        when the drawing's own gap is narrower than gap_px (a smile dot next to a nose, dotted
        arcs next to an outline). Between a dot (a piece under small_px pixels) and a bigger
        piece the split is moved dot_claim_px towards the bigger one, so the dot survives.
        Two dots at least gap_px apart in the drawing stay apart; dots closer to each other than
        that may join (a row of dots too tight to print one by one becomes a beaded line, but stays
        apart from the outline next to it);
      * inside one piece, where two neighbouring background pixels see their nearest ink in
        opposite directions (cosine <= -sharp: two near-parallel lines, or a corner sharper than
        ~50 degrees) and the drawing's gap there is at least wmin_px: the channel between two
        zigzags or between fringe strands; and the deepest point of every small hole in the
        drawing at least wmin_px across (a berry's highlight). Only the drawing's own background is
        kept there (the ink is not eaten); ridges shorter than min_len_px (corner specks) are ignored.
    Hairline gaps (< wmin_px) and wider corners close as before. Only places that the
    thickening actually threatens (distance to ink < grow_px + gap_px / 2 + 1) are cut."""
    if not ink.any() or grow_px <= 0:
        return np.zeros(ink.shape, bool)
    h, w = ink.shape
    INF = np.float32(1e9)
    d, ny, nx = edt(ink, return_index=True)
    ny = np.clip(ny, 0, h - 1)
    nx = np.clip(nx, 0, w - 1)
    if pieces is None:
        comp, ncomp = label_components(ink, diag=True)
    else:
        comp = np.where(ink, pieces, 0).astype(np.int32)
        ncomp = int(comp.max())
    small = np.bincount(comp.ravel(), minlength=ncomp + 1) < small_px
    small[0] = False
    dots = small[comp]
    big_ink = ink & ~dots
    if big_ink.any():
        db, by, bx = edt(big_ink, return_index=True)
        bid = comp[np.clip(by, 0, h - 1), np.clip(bx, 0, w - 1)]
    else:
        db, bid = np.full(ink.shape, INF), np.zeros(ink.shape, np.int32)
    ds = edt(dots) if dots.any() else np.full(ink.shape, INF)
    cid = comp[ny, nx]
    reach = grow_px + gap_px / 2.0 + 1.0
    zone = ~ink & (d <= reach)
    near = d <= reach                          # includes ink: pieces may touch on the grid
    near_b = near & (db <= reach + dot_claim_px)
    f = np.where(near & (ds <= reach + dot_claim_px) & (db <= reach + dot_claim_px),
                 ds - dot_claim_px - db, np.nan)
    iy = np.arange(h)[:, None]
    ix = np.arange(w)[None, :]
    ridge_c = np.zeros(ink.shape, bool)       # between different pieces
    ridge_s = np.zeros(ink.shape, bool)       # inside one piece
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        both = zone & _shift(zone, dy, dx, False)
        ob = _shift(bid, dy, dx, 0)
        ridge_c |= near_b & _shift(near_b, dy, dx, False) & (ob != bid) & (ob > 0) & (bid > 0)
        of = _shift(f, dy, dx, np.nan)
        with np.errstate(invalid='ignore'):
            ridge_c |= ((f <= 0) != (of <= 0)) & ~np.isnan(f) & ~np.isnan(of)
        # unit vectors from each pixel to its nearest ink: opposite on the two sides of a channel,
        # parallel along a plain line edge
        oy, ox = _shift(ny, dy, dx, 0), _shift(nx, dy, dx, 0)
        od = np.maximum(_shift(d, dy, dx, 0), 1e-6)
        # two dots the drawing keeps at least gap_px apart stay apart (closer ones may join)
        oc = _shift(cid, dy, dx, 0)
        ridge_c |= both & (oc != cid) & (oc > 0) & small[cid] & small[oc] & (d + od >= gap_px)
        cosv = ((ny - iy) * (oy - iy - dy) + (nx - ix) * (ox - ix - dx)) / (np.maximum(d, 1e-6) * od)
        ridge_s |= both & (_shift(cid, dy, dx, 0) == cid) & (cosv <= -sharp) & (d + od >= wmin_px)
    if ridge_s.any():                          # a real channel is long; drop corner specks
        rl, nr = label_components(ridge_s, diag=True)
        big = np.bincount(rl.ravel(), minlength=nr + 1) >= min_len_px
        big[0] = False
        ridge_s = big[rl]
    # Small holes in the drawing (a berry's highlight, a ring) have no long ridge: keep a hole at
    # their deepest point if they are at least wmin_px across or hole_px in area and the
    # thickening would fill them.
    bl, nbl = label_components(~ink)
    border = np.unique(np.concatenate([bl[0], bl[-1], bl[:, 0], bl[:, -1]]))
    if nbl:
        dmax = np.zeros(nbl + 1)
        np.maximum.at(dmax, bl.ravel(), d.ravel())
        area = np.bincount(bl.ravel(), minlength=nbl + 1)
        ok = ((dmax * 2.0 >= wmin_px) | ((area >= hole_px) & (hole_px > 0))) & (dmax < reach)
        ok[border] = False
        ok[0] = False
        if ok.any():
            ridge_s |= ok[bl] & (d >= dmax[bl] - 0.5)
    if debug is not None:
        debug.update(ridge_c=ridge_c, ridge_s=ridge_s, d=d)
    cut = np.zeros(ink.shape, bool)
    r = gap_px / 2.0
    if ridge_c.any():
        cut |= edt(ridge_c) <= r
    if ridge_s.any():
        cut |= (edt(ridge_s) <= r) & ~ink
    return cut


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


# ----------------------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------------------

class Ornament:
    """Result of the 2D analysis: label maps, height fields and part metadata."""
    pass


def _layout(lum, ink_src, bbox, src_mm, p, carve=True):
    """Grid sampling, line thickening, regions, cookie outline and hanging hole at a given scale
    (src_mm = mm per source pixel). Returns a dict; 'extent_mm' = (width, height) of the cookie."""
    by0, by1, bx0, bx1 = bbox
    res = p['res_mm']
    pad_mm = p['cookie_margin_mm'] + p['cookie_smooth_mm'] + \
        (p['hole_diameter_mm'] + 2 * p['hole_ring_mm'] + p['hole_clearance_mm'] + 2.0 if p['hole'] else 0) + 2.0
    gw = int(math.ceil(((bx1 - bx0) * src_mm + 2 * pad_mm) / res))
    gh = int(math.ceil(((by1 - by0) * src_mm + 2 * pad_mm) / res))
    # grid pixel centre -> source coordinates
    cx_src = (bx0 + bx1) / 2.0
    cy_src = (by0 + by1) / 2.0
    xs = cx_src + (np.arange(gw) + 0.5 - gw / 2.0) * res / src_mm
    ys = cy_src + (np.arange(gh) + 0.5 - gh / 2.0) * res / src_mm
    half = max(0.5, 0.5 * res / src_mm)
    if src_mm > res * 1.05 and p.get('outline_smooth_mm', 0) > 0:
        # Coarse source: interpolate between source pixels so the outlines don't step.
        lum_g = _bilinear(lum.astype(np.float64), ys - 0.5, xs - 0.5)
    else:
        lum_g = _box_sample(lum.astype(np.float64), ys - 0.5, xs - 0.5, half)[..., 0]
    ink = lum_g < p['ink_threshold']
    ink_raw = ink

    # Thicken lines so the icing is printable / reads as piped, but keep a printable gap between
    # lines that the drawing keeps apart (the gap is cut back in below, after the regions are found).
    keep_gap = np.zeros(ink.shape, bool)
    if p['line_boost_mm'] > 0:
        if carve and p.get('keep_gaps', p.get('geometry', 2) >= 2) and p.get('gap_mm', 0.42) > 0:
            # which piece of the drawing (8-connected, at the drawing's own resolution) each grid
            # ink pixel comes from
            src_comp, _ = label_components(ink_src, diag=True)
            yi = np.clip(np.floor(ys).astype(np.int64), 0, ink_src.shape[0] - 1)
            xi = np.clip(np.floor(xs).astype(np.int64), 0, ink_src.shape[1] - 1)
            pc = src_comp[yi[:, None], xi[None, :]]
            if (ink & (pc == 0)).any() and (pc > 0).any():
                _, qy, qx = edt(pc > 0, return_index=True)
                pc = np.where(pc > 0, pc, pc[np.clip(qy, 0, gh - 1), np.clip(qx, 0, gw - 1)])
            keep_gap = separation_carve(ink, p['line_boost_mm'] / res, p.get('gap_mm', 0.42) / res,
                                        p.get('gap_min_mm', 0.3) / res, p.get('dot_mm2', 0.5) / res ** 2,
                                        p.get('dot_claim_mm', 0.2) / res, pieces=pc,
                                        hole_px=p.get('hole_keep_mm2', 0.3) / res ** 2)
        ink = edt(ink) <= p['line_boost_mm'] / res
    sig_mm = p.get('outline_smooth_mm', 0)
    if sig_mm > 0:
        ink = smooth_mask(ink, max(sig_mm, 0.8 * src_mm) / res)

    # Enclosed regions.
    labels, n = label_components(~ink)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    border.discard(0)
    areas = np.bincount(labels.ravel(), minlength=n + 1) * res * res
    region_ids = [l for l in range(1, n + 1) if l not in border]
    small = [l for l in region_ids if areas[l] < p['min_region_mm2']]
    keep = [l for l in region_ids if areas[l] >= p['min_region_mm2']]
    if small and carve and p.get('keep_gaps', p.get('geometry', 2) >= 2) and p.get('hole_keep_mm2', 0.3) > 0:
        # A small enclosed area that is what is left of a real hole in the drawing (an enclosed
        # white cell of at least hole_keep_mm2, e.g. a button's highlight) stays open as bare
        # cookie instead of being filled with icing.
        hl, nh = label_components(~ink_raw)
        hb = set(np.unique(np.concatenate([hl[0], hl[-1], hl[:, 0], hl[:, -1]])).tolist())
        ha = np.bincount(hl.ravel(), minlength=nh + 1) * res * res
        big = (ha >= p['hole_keep_mm2'])
        big[0] = False
        big[list(hb)] = False
        hit = np.zeros(n + 1, bool)
        hit[labels[big[hl]]] = True
        small = [l for l in small if not hit[l]]
    lines = ink.copy()
    if small:
        lines |= np.isin(labels, small)

    lines_full = lines.copy()
    lines &= ~keep_gap          # regions and the cookie outline are found as before

    top = np.zeros((gh, gw), dtype=np.int32)
    top[lines] = 1
    for k, l in enumerate(keep):
        top[labels == l] = k + 2
    silhouette = (top > 0) | lines_full

    # Cookie outline: grow silhouette by the margin, round off the notches.
    cookie = edt(silhouette) <= p['cookie_margin_mm'] / res
    sm = p['cookie_smooth_mm'] / res
    if sm > 0:
        cookie = close(cookie, sm)
    cookie |= silhouette

    hole_info = None
    if p['hole']:
        r_hole = p['hole_diameter_mm'] / 2.0 / res
        r_ring = r_hole + p['hole_ring_mm'] / res
        jj = np.arange(gw)
        col_mass = cookie.sum(axis=0).astype(np.float64)
        cxg = float((col_mass * jj).sum() / col_mass.sum())
        band = (jj >= cxg - r_hole - 1) & (jj <= cxg + r_hole + 1)
        sil_rows = np.flatnonzero(silhouette[:, band].any(axis=1))
        top_row = sil_rows[0] if len(sil_rows) else gh / 2
        cyg = top_row - (p['hole_clearance_mm'] / res + r_hole)
        ii, jg = np.mgrid[0:gh, 0:gw]
        rr = np.hypot(ii + 0.5 - cyg, jg + 0.5 - cxg)
        cookie |= rr <= r_ring
        if sm > 0:
            cookie = close(cookie, min(sm, r_ring))
        cookie |= silhouette
        cookie &= rr > r_hole
        hole_info = (cxg, cyg, r_hole)

    # Trim grid to the cookie bounding box (+1 px border).
    rr_ = np.flatnonzero(cookie.any(axis=1))
    cc_ = np.flatnonzero(cookie.any(axis=0))
    r0, r1 = max(rr_[0] - 2, 0), min(rr_[-1] + 3, gh)
    c0, c1 = max(cc_[0] - 2, 0), min(cc_[-1] + 3, gw)
    cookie = cookie[r0:r1, c0:c1]
    top = top[r0:r1, c0:c1]
    gh, gw = cookie.shape
    ys = ys[r0:r1]
    xs = xs[c0:c1]

    return dict(res=res, ys=ys, xs=xs, top=top, cookie=cookie, hole_info=hole_info, r0=r0, c0=c0,
                gh=gh, gw=gw, keep=keep, extent_mm=(float(len(cc_)) * res, float(len(rr_)) * res))


def analyse(line_rgb, colour_rgb=None, **kw):
    """line_rgb / colour_rgb: float arrays (H, W, 3) in 0..1, row 0 = top of image.

    Returns an Ornament with:
      px            grid pixel size (mm)
      cookie        bool mask
      top_labels    int map: 0 = no icing, 1 = piped lines, 2.. = regions
      regions       list of dict(label, area_mm2, colour (rgb or None), centroid)
      cookie_top    corner height field (H+1, W+1) of the cookie top
      icing_h       per-pixel icing height above the cookie
    """
    p = dict(DEFAULTS)
    p.update({k: v for k, v in kw.items() if v is not None})
    if line_rgb is None:
        line_rgb = colour_rgb
    lum = luminance(line_rgb)
    ink_src = lum < p['ink_threshold']
    if not ink_src.any():
        raise ValueError("No dark line-art found in the image (try raising the ink threshold).")
    rows = np.flatnonzero(ink_src.any(axis=1))
    cols = np.flatnonzero(ink_src.any(axis=0))
    by0, by1, bx0, bx1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    content_mm = p['size_mm'] - 2.0 * p['cookie_margin_mm']
    nw, nh = bx1 - bx0, by1 - by0
    src_mm = content_mm / float(max(nw, nh))   # mm per source pixel
    bbox = (by0, by1, bx0, bx1)
    whole = p.get('size_whole', p.get('geometry', 2) >= 2)

    def rescale(L, s):
        # outline = drawing * scale + a fixed margin / tab: solve for the scale whose longest side is Size
        W, H = L['extent_mm']
        a_w, a_h = W - nw * s, H - nh * s
        return max(1e-6, min((p['size_mm'] - a_w) / nw, (p['size_mm'] - a_h) / nh)), max(W, H) - p['size_mm']

    if whole:
        # Size = the longest side of the whole finished outline, hanging-hole tab included.
        # First guess from a quick outline on a coarse grid, then check on the real one.
        coarse = dict(p, res_mm=max(p['res_mm'], 0.3))
        src_mm, _ = rescale(_layout(lum, ink_src, bbox, src_mm, coarse, carve=False), src_mm)
    for _ in range(3):
        L = _layout(lum, ink_src, bbox, src_mm, p)
        if not whole:
            break
        new_mm, err = rescale(L, src_mm)
        if abs(err) <= max(p['res_mm'], 0.25):
            break
        src_mm = new_mm
    res, ys, xs, top, cookie = L['res'], L['ys'], L['xs'], L['top'], L['cookie']
    hole_info, r0, c0, gh, gw, keep = L['hole_info'], L['r0'], L['c0'], L['gh'], L['gw'], L['keep']

    # ---- heights ----
    T = p['cookie_thickness_mm']
    Rb = min(p['cookie_bevel_mm'], T * 0.9)
    d_cookie = inner_distance(cookie.astype(np.int32)) * res
    t = np.clip(d_cookie / max(Rb, 1e-6), 0, 1)
    cookie_px = np.where(cookie, T - Rb + Rb * np.sqrt(1 - (1 - t) ** 2), 0.0)

    d_top = inner_distance(top) * res

    def bead(d, hmax, hmin, r):
        tt = np.clip(d / max(r, 1e-6), 0, 1)
        return hmin + (hmax - hmin) * np.sqrt(1 - (1 - tt) ** 2)

    icing_px = np.zeros((gh, gw))
    lm = top == 1
    icing_px[lm] = bead(d_top[lm], p['line_height_mm'], p['line_edge_mm'], p['line_round_mm'])
    rm = top >= 2
    icing_px[rm] = bead(d_top[rm], p['fill_height_mm'], p['fill_edge_mm'], p['fill_round_mm'])

    # Region colours from the coloured image.
    regions = []
    col_g = None
    if colour_rgb is not None:
        if colour_rgb.shape[:2] != line_rgb.shape[:2]:
            raise ValueError("Coloured image must have the same pixel size as the line-art image.")
        # nearest sampling (no blending across lines)
        yi = np.clip(np.round(ys - 0.5).astype(int), 0, colour_rgb.shape[0] - 1)
        xi = np.clip(np.round(xs - 0.5).astype(int), 0, colour_rgb.shape[1] - 1)
        col_g = colour_rgb[yi[:, None], xi[None, :], :3]
    jj, ii = np.meshgrid(np.arange(gw), np.arange(gh))
    for k in range(len(keep)):
        lab = k + 2
        m = top == lab
        area = float(m.sum() * res * res)
        cy = float(ii[m].mean())
        cx = float(jj[m].mean())
        colour = None
        if col_g is not None:
            inner = m & (d_top >= 1.5 * res + 0.5 * res)
            sel = inner if inner.sum() >= 3 else m
            c = np.median(col_g[sel], axis=0)
            if float(c.min()) < p['white_cutoff'] and float(luminance(c)) > 0.12:
                colour = tuple(float(v) for v in c)
        regions.append(dict(label=lab, area_mm2=area, colour=colour, centroid=(cy, cx)))

    o = Ornament()
    o.params = p
    o.px = res
    o.cookie = cookie
    o.top = top
    o.regions = regions
    o.cookie_px = cookie_px
    o.icing_px = icing_px
    o.d_cookie = d_cookie
    o.d_top = d_top
    o.hole = None if hole_info is None else (hole_info[0] - c0, hole_info[1] - r0, hole_info[2])
    o.shape = (gh, gw)
    o.src_ys, o.src_xs = ys, xs         # grid row/col centre -> source image pixel coords
    o.src_mm = src_mm                   # mm per source image pixel (the drawing's scale)
    return o


# ----------------------------------------------------------------------------
# Colour -> filament palette
# ----------------------------------------------------------------------------

def build_palette(regions, merge=0.18, cookie_rgb=(0.682, 0.514, 0.357), icing_rgb=(1.0, 1.0, 1.0),
                  max_filaments=0):
    """Assign region colours to filament slots. Slot 0 = cookie, 1 = icing.
    Returns (palette list of rgb, list of slot per region or None for bare cookie)."""
    palette = [tuple(cookie_rgb), tuple(icing_rgb)]
    slots = []
    for r in regions:
        c = r['colour']
        if c is None:
            slots.append(None)
            continue
        best, bd = None, 1e9
        for i, pc in enumerate(palette):
            d = math.dist(c, pc)
            if d < bd:
                best, bd = i, d
        if bd <= merge:
            slots.append(best)
        else:
            palette.append(tuple(c))
            slots.append(len(palette) - 1)
    # Fit the AMS: merge the closest pair of region colours (or a colour into the icing)
    # until the palette is small enough. The cookie slot is never merged away.
    while max_filaments and len(palette) > max(2, max_filaments):
        best = None
        for i in range(1, len(palette)):
            for j in range(max(i + 1, 2), len(palette)):
                d = math.dist(palette[i], palette[j])
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        slots = [i if s == j else (s - 1 if (s is not None and s > j) else s) for s in slots]
        del palette[j]
    return palette, slots


# ----------------------------------------------------------------------------
# Icing line segmentation (each piped stroke between junctions = its own part)
# ----------------------------------------------------------------------------

def _nbrs(a):
    """P2..P9 (N, NE, E, SE, S, SW, W, NW) neighbour arrays of a bool/int image."""
    return [_shift(a, dy, dx, 0) for dy, dx in
            ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))]


def skeletonize(mask, max_iter=200):
    """Zhang-Suen thinning, vectorised. Returns a 1-px-wide, 8-connected centre-line."""
    img = mask.astype(np.uint8).copy()
    for _ in range(max_iter):
        changed = False
        for step in (0, 1):
            P = _nbrs(img)
            B = sum(P)
            seq = P + [P[0]]
            A = sum(((seq[k] == 0) & (seq[k + 1] == 1)).astype(np.uint8) for k in range(8))
            p2, p3, p4, p5, p6, p7, p8, p9 = P
            if step == 0:
                c = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                c = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            rm = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any():
                img[rm] = 0
                changed = True
        if not changed:
            break
    return img.astype(bool)


def _fix_pinches(lab, max_iter=20):
    """A part whose pixels touch only corner-to-corner would mesh to a pinched (non-manifold)
    vertex. Hand one of the two pixels to the neighbouring part across the pinch."""
    for _ in range(max_iter):
        changed = False
        for flip in (False, True):
            L = lab[:, ::-1] if flip else lab
            a, b = L[:-1, :-1], L[1:, 1:]
            c, d = L[1:, :-1], L[:-1, 1:]
            pin = (a != 0) & (a == b) & (c != a) & (d != a)
            take = np.where(c != 0, c, d)
            pin &= take != 0
            if pin.any():
                i, j = np.nonzero(pin)
                L = L.copy()
                L[i, j] = take[i, j]
                lab = L[:, ::-1] if flip else L
                changed = True
        if not changed:
            break
    return lab


def _label_boxes(lab):
    """{label: (r0, r1, c0, c1)} bounding boxes (end exclusive) of every non-zero label."""
    ii, jj = np.nonzero(lab)
    if not len(ii):
        return {}
    v = lab[ii, jj].astype(np.int64)
    off = int(v.min())
    v = v - off
    n = int(v.max()) + 1
    big = 1 << 30
    r0 = np.full(n, big); r1 = np.full(n, -1); c0 = np.full(n, big); c1 = np.full(n, -1)
    np.minimum.at(r0, v, ii); np.maximum.at(r1, v, ii)
    np.minimum.at(c0, v, jj); np.maximum.at(c1, v, jj)
    return {int(k + off): (int(r0[k]), int(r1[k]) + 1, int(c0[k]), int(c1[k]) + 1)
            for k in np.flatnonzero(r1 >= 0)}


def _ring4(m):
    ring = np.zeros_like(m)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ring |= _shift(m, dy, dx, False)
    return ring & ~m


def _best_neighbour(lab, m, own):
    """The non-zero label (other than `own`) sharing the most 4-neighbour contact with mask m, or 0."""
    nb = lab[_ring4(m)]
    nb = nb[(nb > 0) & (nb != own)]
    if not nb.size:
        return 0
    u, cnt = np.unique(nb, return_counts=True)
    return int(u[np.argmax(cnt)])


def _find_pinches(lab):
    """2x2 blocks where one non-zero label touches itself only corner-to-corner.
    Returns a list of ((ra, ca), (rb, cb), (rc, cc), (rd, cd)): a, b the pinched pair, c, d the others."""
    out = []
    a, b = lab[:-1, :-1], lab[1:, 1:]
    c, d = lab[1:, :-1], lab[:-1, 1:]
    for i, j in zip(*np.nonzero((a != 0) & (a == b) & (c != a) & (d != a))):
        out.append(((i, j), (i + 1, j + 1), (i + 1, j), (i, j + 1)))
    for i, j in zip(*np.nonzero((d != 0) & (d == c) & (a != d) & (b != d))):
        out.append(((i, j + 1), (i + 1, j), (i, j), (i + 1, j + 1)))
    return out


def _ncomp_window(lab, i, j, label, r=4):
    h, w = lab.shape
    win = lab[max(i - r, 0):min(i + r + 1, h), max(j - r, 0):min(j + r + 1, w)]
    return label_components(win == label)[1] if label else 0


def _fix_stroke_pinches(lab, max_iter=40):
    """Remove corner-only self contacts without splitting any stroke: of the four ways to fix a
    pinch (hand a or b to a neighbour, or hand c or d to the pinched stroke), take the first that
    adds no connected piece to either label in a local window; 0 (no line) never grows."""
    lab = lab.copy()
    for _ in range(max_iter):
        pins = _find_pinches(lab)
        if not pins:
            break
        for pa, pb, pc, pd in pins:
            L = lab[pa]
            if lab[pb] != L or lab[pc] == L or lab[pd] == L:
                continue                       # already resolved by an earlier fix
            cands = [(q, L) for q in (pc, pd) if lab[q] != 0]
            for q in (pa, pb):
                for t in (pc, pd):
                    cands.append((q, lab[t]))
            done = False
            for q, new in cands:
                old = lab[q]
                before = _ncomp_window(lab, q[0], q[1], old) + _ncomp_window(lab, q[0], q[1], new)
                lab[q] = new
                after = _ncomp_window(lab, q[0], q[1], old) + _ncomp_window(lab, q[0], q[1], new)
                if after <= before:
                    done = True
                    break
                lab[q] = old
            if not done:
                q, new = cands[-1] if cands else (pa, 0)
                lab[q] = new
    return lab


def _opened(m, r):
    """Morphological opening of mask m with a disc of radius r px, evaluated on a 2x finer grid
    (on the working grid itself a 3-px and a 4-px wide band look the same to a pixel-centred disc).
    A pixel is kept when at least 2 of its 4 sub-pixels are."""
    f = np.repeat(np.repeat(m, 2, axis=0), 2, axis=1)
    f = np.pad(f, 2)
    r2 = 2.0 * r
    core_ = (edt(~f) - 0.5) >= r2
    if not core_.any():
        return np.zeros_like(m)
    op = (edt(core_) <= r2 + 0.5) & f
    op = op[2:-2, 2:-2]
    h, w = m.shape
    cnt = op.reshape(h, 2, w, 2).sum(axis=(1, 3))
    return (cnt >= 2) & m


def part_width_px(m):
    """Widest inscribed circle of mask m, in px (as tools/qa/measure.py's max_width, evaluated on a
    2x finer grid): 2 * (max distance to the outside - half a fine pixel)."""
    if not m.any():
        return 0.0
    rows = np.flatnonzero(m.any(axis=1))
    cols = np.flatnonzero(m.any(axis=0))
    c = m[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    f = np.pad(np.repeat(np.repeat(c, 2, axis=0), 2, axis=1), 2)
    return max(float(edt(~f)[f].max()) - 0.5, 0.0)          # 2 * (dt - 0.5) fine px = that in px


def fix_thin_strokes(top, strokes, cookie, px, min_w_mm, gap_mm, floor_mm=0.34, crumb_mm2=0.05):
    """Every stroke whose widest point is under min_w_mm (it would not print as a dot) either
    joins the stroke it touches most, or - if it touches none - grows (away from its neighbours,
    only where gap_mm of bare cookie stays to every other icing line; it may take pixels of the
    region around it) until it is a min_w_mm dot; if its neighbours' gaps stop it short of that,
    it stays unchanged if it was already floor_mm wide, else it is joined by a bridge to the
    nearest stroke within about gap_mm (a dot in a row too tight to print one by one). Only a
    stray crumb under crumb_mm2 with nothing near is dropped (bare cookie).
    Returns (top, strokes, changed). top: 1 = line, >= 2 region, 0 bare."""
    changed = False
    min_w = min_w_mm / px
    gap = gap_mm / px
    h, w = strokes.shape
    for L in sorted(_label_boxes(strokes)):
        m = strokes == L
        if not m.any() or part_width_px(m) >= min_w:
            continue
        changed = True
        nb = _best_neighbour(strokes, m, L)
        if nb:
            strokes = np.where(m, nb, strokes)
            continue
        # isolated: grow a dot around its deepest point
        rows = np.flatnonzero(m.any(axis=1))
        cols = np.flatnonzero(m.any(axis=0))
        pad = int(math.ceil(min_w + gap)) + 3
        r0, r1 = max(rows[0] - pad, 0), min(rows[-1] + 1 + pad, h)
        c0, c1 = max(cols[0] - pad, 0), min(cols[-1] + 1 + pad, w)
        sm = m[r0:r1, c0:c1]
        others = (top[r0:r1, c0:c1] == 1) & ~sm
        # grow only where gap px of bare cookie stays to every other line (so away from them)
        allowed = cookie[r0:r1, c0:c1] & ((edt(others) - 1.0 >= gap) if others.any() else True)
        dsm = edt(sm)
        w0 = part_width_px(sm)
        dot, best = sm, w0
        for grow in np.arange(0.5, min_w + 0.5, 0.25):
            cand = sm | ((dsm <= grow) & allowed)
            wc = part_width_px(cand)
            if wc > best:
                dot, best = cand, wc
            if wc >= min_w:
                break
        # Hemmed in by its neighbours' gaps before reaching min_w: a dot that already was floor wide
        # stays as it is (this grid estimate runs ~0.1 mm under the smoothed mesh's width);
        # anything else is dropped.
        ok = best >= min_w
        if not ok and w0 >= min(floor_mm / px, min_w):
            dot, ok = sm, True
        sub_t = top[r0:r1, c0:c1]
        sub_s = strokes[r0:r1, c0:c1]
        if ok:
            sub_t[dot] = 1
            sub_s[dot] = L
            continue
        # Still too thin: it is a drawn dot closer than the gap to a neighbour (a tight dotted row),
        # so join it to the nearest stroke with a min_w wide bridge (the drawing allows fusing dots
        # under gap_mm apart; deleting one is not allowed). Only a stray crumb with nobody near
        # is dropped.
        if others.any():
            d_o, oy, ox = edt(others, return_index=True)
            k = np.argmin(np.where(sm, d_o, np.inf))
            D = float(d_o.ravel()[k])
            if D - 1.0 <= gap + 1.0:
                nb = int(sub_s[np.clip(oy.ravel()[k], 0, sm.shape[0] - 1), np.clip(ox.ravel()[k], 0, sm.shape[1] - 1)])
                nbm = sub_s == nb
                rest = others & ~nbm
                ok_b = cookie[r0:r1, c0:c1] & ((edt(rest) - 1.0 >= gap) if rest.any() else True)
                bridge = (edt(sm) + edt(nbm) <= D + min_w) & ok_b
                # it joins nb anyway, so it may now grow towards nb too: a full dot at its own spot
                grown = sm
                for grow in np.arange(0.5, min_w + 0.5, 0.25):
                    grown = sm | ((dsm <= grow) & ok_b)
                    if part_width_px(grown) >= min_w:
                        break
                keep = grown | bridge
                sub_t[keep] = 1
                sub_s[keep] = nb
                continue
        if sm.sum() * px * px < crumb_mm2:
            sub_t[sm] = 0
            sub_s[sm] = 0
    return top, strokes, changed


def clean_strokes(strokes, px, min_detail_mm=0.5, sliver_mm2=0.1, crumb_mm2=0.1, max_iter=8):
    """Make every stroke one printable piece.

    * A sliver of a stroke narrower than min_detail_mm (what a morphological opening with a disc of
      that diameter removes, e.g. the crescent left where two strokes meet), at least sliver_mm2 in
      area and touching another stroke, is handed to that stroke: no part keeps an unprintable
      feature and no gap appears. Each pixel is handed over this way at most once.
    * A stroke made of several 4-connected pieces keeps its largest; every other piece goes to the
      neighbouring stroke it touches most (no gap appears), or becomes its own stroke if it touches
      none. An isolated crumb smaller than crumb_mm2 (unprintable anyway) is dropped.
    * Corner-only self contacts (non-manifold pinches) are resolved without splitting a stroke.
    Returns (labels renumbered 1..n largest first, n). Pixels dropped as crumbs become 0."""
    lab = strokes.astype(np.int32).copy()
    h, w = lab.shape
    r_open = min_detail_mm / 2.0 / px
    sliver_px = sliver_mm2 / (px * px)
    crumb_px = crumb_mm2 / (px * px)
    pad = int(math.ceil(r_open)) + 3
    frozen = np.zeros(lab.shape, bool)
    dirty = set(_label_boxes(lab))
    for _ in range(max_iter):
        changed = False
        prev = lab.copy()
        next_id = int(lab.max()) + 1
        for L in sorted(_label_boxes(lab)):
            # box from the current labels: earlier hand-overs may have grown this stroke
            rows = np.flatnonzero((lab == L).any(axis=1))
            if not len(rows):
                continue
            cols = np.flatnonzero((lab[rows[0]:rows[-1] + 1] == L).any(axis=0))
            r0, r1 = max(rows[0] - pad, 0), min(rows[-1] + 1 + pad, h)
            c0, c1 = max(cols[0] - pad, 0), min(cols[-1] + 1 + pad, w)
            sub = lab[r0:r1, c0:c1]          # views: edits go straight into lab / frozen
            fz = frozen[r0:r1, c0:c1]
            m = sub == L
            # 1. thin slivers touching another stroke
            if r_open > 0 and L in dirty:
                rem = m & ~_opened(m, r_open) & ~fz
                if rem.any():
                    cl, nc = label_components(rem, diag=True)
                    cnt = np.bincount(cl.ravel(), minlength=nc + 1)
                    for k in range(1, nc + 1):
                        if cnt[k] < sliver_px:
                            continue
                        piece = cl == k
                        nb = _best_neighbour(sub, piece, L)
                        if nb:
                            sub[piece] = nb
                            fz[piece] = True
                            changed = True
                    m = sub == L
                    if not m.any():
                        continue
            # 2. extra islands
            cl, nc = label_components(m)
            if nc > 1:
                sizes = np.bincount(cl.ravel(), minlength=nc + 1)
                sizes[0] = -1
                main = int(np.argmax(sizes))
                for k in range(1, nc + 1):
                    if k == main:
                        continue
                    piece = cl == k
                    nb = _best_neighbour(sub, piece, L)
                    if nb:
                        sub[piece] = nb
                    elif sizes[k] < crumb_px:
                        sub[piece] = 0
                    else:
                        sub[piece] = next_id
                        next_id += 1
                    changed = True
        fixed = _fix_stroke_pinches(lab)
        if (fixed != lab).any():
            lab = fixed
            changed = True
        if not changed:
            break
        diff = prev != lab
        dirty = set(np.unique(prev[diff]).tolist()) | set(np.unique(lab[diff]).tolist())
        dirty.discard(0)
    vals, inv = np.unique(lab, return_inverse=True)
    inv = inv.reshape(lab.shape)
    sizes = np.bincount(inv.ravel()).astype(np.int64)
    sizes[vals == 0] = -1
    rank = np.empty(len(vals), np.int32)
    rank[np.argsort(-sizes, kind='stable')] = np.arange(len(vals), dtype=np.int32)
    out = np.where(lab == 0, 0, rank[inv] + 1).astype(np.int32)
    return out, int((vals != 0).sum())


def segment_lines(lines, px, min_len_mm=1.5, straight_cos=-0.8):
    """Split the icing-line mask into strokes at junctions.

    Centre-line -> cut at junctions -> branches. At each junction the pair of branches that
    carries straight on (most opposite directions) is re-joined, so an outline running through
    a T or X stays one stroke and owns the junction; the side branches become their own strokes.
    Short spurs are absorbed. Every line pixel then goes to its nearest stroke centre-line.
    Returns (labels int32 with 0 = not a line, count)."""
    if not lines.any():
        return np.zeros(lines.shape, np.int32), 0
    comp, ncomp = label_components(lines)
    sk = skeletonize(lines)
    P = _nbrs(sk.astype(np.uint8))
    seq = P + [P[0]]
    A = sum(((seq[k] == 0) & (seq[k + 1] == 1)).astype(np.uint8) for k in range(8))
    B = sum(P)
    junc = sk & ((A >= 3) | (B >= 4))
    half = float(np.median(edt(~lines)[sk])) if sk.any() else 2.0
    jr = max(1.5, half + 1.0)
    jzone = sk & (edt(junc) <= jr) if junc.any() else np.zeros_like(sk)
    branches, nb = label_components(sk & ~jzone, diag=True)
    jl, nj = label_components(jzone, diag=True)
    if nb == 0:
        return comp.astype(np.int32), ncomp

    # branch lengths and which line component each belongs to
    blen = np.bincount(branches.ravel(), minlength=nb + 1).astype(np.float64)
    bcomp = np.zeros(nb + 1, np.int64)
    bcomp[branches.ravel()] = comp.ravel()
    min_len = max(3.0, min_len_mm / px)

    # union-find over branches
    parent = list(range(nb + 1))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    # which branches touch which junction zone (8-neighbourhood contact)
    jl_grown = jl.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            sh = _shift(jl, dy, dx, 0)
            jl_grown = np.where((jl_grown == 0) & (sh > 0), sh, jl_grown)
    touch = (branches > 0) & (jl_grown > 0)
    pairs = {}
    for j, b in zip(jl_grown[touch].tolist(), branches[touch].tolist()):
        pairs.setdefault(j, set()).add(b)
    jy, jx = np.nonzero(jl)
    jlab = jl[jy, jx]
    jcy = np.bincount(jlab, weights=jy, minlength=nj + 1) / np.maximum(np.bincount(jlab, minlength=nj + 1), 1)
    jcx = np.bincount(jlab, weights=jx, minlength=nj + 1) / np.maximum(np.bincount(jlab, minlength=nj + 1), 1)
    by, bx = np.nonzero(branches)
    blab = branches[by, bx]
    order = np.argsort(blab, kind='stable')
    by, bx, blab = by[order], bx[order], blab[order]
    starts = np.searchsorted(blab, np.arange(nb + 2))
    R = max(6.0, 3 * half)
    owner = {}  # junction -> branch that owns its pixels
    for j, bs in pairs.items():
        bs = [b for b in bs if blen[b] >= min_len] or sorted(bs, key=lambda b: -blen[b])[:1]
        dirs = {}
        for b in bs:
            ys, xs = by[starts[b]:starts[b + 1]], bx[starts[b]:starts[b + 1]]
            d = np.hypot(ys - jcy[j], xs - jcx[j])
            near = d <= R + jr
            if not near.any():
                near = d <= d.min() + 1
            v = np.array([ys[near].mean() - jcy[j], xs[near].mean() - jcx[j]])
            n = np.linalg.norm(v)
            if n > 1e-6:
                dirs[b] = v / n
        cand = []
        bl = list(dirs)
        for i in range(len(bl)):
            for k in range(i + 1, len(bl)):
                c = float(dirs[bl[i]] @ dirs[bl[k]])
                if c < straight_cos:
                    cand.append((c, bl[i], bl[k]))
        cand.sort()
        used = set()
        for c, b1, b2 in cand:
            if b1 in used or b2 in used:
                continue
            used.update((b1, b2))
            parent[find(b2)] = find(b1)
            owner.setdefault(j, b1)
        if j not in owner and bs:
            owner[j] = max(bs, key=lambda b: blen[b])

    # absorb short spurs: only keep branches whose merged stroke is long enough
    root = np.array([find(b) for b in range(nb + 1)])
    slen = np.bincount(root, weights=blen, minlength=nb + 1)
    keep_b = (slen[root] >= min_len)
    keep_b[0] = False
    # a line component with nothing long enough keeps its longest branch
    for c in range(1, ncomp + 1):
        bs = np.flatnonzero((bcomp == c) & (np.arange(nb + 1) > 0))
        if len(bs) and not keep_b[bs].any():
            keep_b[bs[np.argmax(slen[root[bs]])]] = True
    seed_lab = np.where(branches > 0, np.where(keep_b[branches], root[branches], 0), 0)
    for j, b in owner.items():
        if keep_b[b]:
            seed_lab = np.where(jl == j, root[b], seed_lab)
    seeds = seed_lab > 0
    _, ny, nx = edt(seeds, return_index=True)
    lab = np.where(lines, seed_lab[np.clip(ny, 0, lines.shape[0] - 1), np.clip(nx, 0, lines.shape[1] - 1)], 0)
    # never let a stroke jump across a gap into another line component
    scomp = np.zeros(nb + 1, np.int64)
    scomp[root[1:]] = bcomp[1:]
    bad = lines & ((lab == 0) | (scomp[lab] != comp))
    if bad.any():
        lab = np.where(bad, -comp, lab)  # orphan pixels: their own component stroke
    # fold tiny fragments into the stroke they touch most
    min_area = max(12.0, (min_len_mm / px) * half)
    vals, counts = np.unique(lab[lab != 0], return_counts=True)
    for v, c in zip(vals.tolist(), counts.tolist()):
        if c >= min_area:
            continue
        m = lab == v
        ring = np.zeros_like(m)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ring |= _shift(m, dy, dx, False)
        nb_labels = lab[ring & ~m & (lab != 0)]
        if nb_labels.size:
            u, cnt = np.unique(nb_labels, return_counts=True)
            lab = np.where(m, u[np.argmax(cnt)], lab)
    lab = _fix_pinches(lab)
    # renumber 1..n, largest first
    vals, inv = np.unique(lab, return_inverse=True)
    inv = inv.reshape(lab.shape)
    sizes = np.bincount(inv.ravel()).astype(np.int64)
    sizes[vals == 0] = -1
    rank = np.empty(len(vals), np.int32)
    rank[np.argsort(-sizes, kind='stable')] = np.arange(len(vals), dtype=np.int32)
    out = np.where(lab == 0, 0, rank[inv] + 1).astype(np.int32)
    return out, int((vals != 0).sum())


# ----------------------------------------------------------------------------
# Meshing
# ----------------------------------------------------------------------------

def corner_average(values, mask):
    """Average per-pixel values onto the (H+1, W+1) corner lattice using only mask pixels."""
    h, w = mask.shape
    v = np.where(mask, values, 0.0)
    m = mask.astype(np.float64)
    sv = np.zeros((h + 1, w + 1))
    sm = np.zeros((h + 1, w + 1))
    for dy in (0, 1):
        for dx in (0, 1):
            sv[dy:dy + h, dx:dx + w] += v
            sm[dy:dy + h, dx:dx + w] += m
    return np.where(sm > 0, sv / np.maximum(sm, 1), 0.0)


def smooth_lattice(combined, iters=25, lam=0.6, mu=-0.63, clamp=0.6, min_sep=0.1):
    """Taubin-smooth the pixel-corner lattice along label boundaries.

    Returns (X, Y) corner positions in pixel units, shape (H+1, W+1). Only corners on a
    simple boundary (exactly two boundary edges) move, so junctions stay put and every
    part built from the same lattice keeps exactly coincident shared walls.

    Every corner moves at most `clamp` px per axis, and two neighbouring corners always stay at
    least min_sep px apart (diagonal neighbours used to meet within 1e-5 mm, which a slicer welds
    into a non-manifold edge).
    """
    h, w = combined.shape
    Lp = np.zeros((h + 2, w + 2), dtype=combined.dtype)
    Lp[1:-1, 1:-1] = combined
    He = Lp[0:h + 1, 1:w + 1] != Lp[1:h + 2, 1:w + 1]       # (h+1, w): edge (i,j)-(i,j+1)
    Ve = Lp[1:h + 1, 0:w + 1] != Lp[1:h + 1, 1:w + 2]       # (h, w+1): edge (i,j)-(i+1,j)
    hl = np.zeros((h + 1, w + 1), bool); hl[:, 1:] = He     # edge to the left neighbour
    hr = np.zeros((h + 1, w + 1), bool); hr[:, :-1] = He    # edge to the right neighbour
    vu = np.zeros((h + 1, w + 1), bool); vu[1:, :] = Ve     # edge to the corner above
    vd = np.zeros((h + 1, w + 1), bool); vd[:-1, :] = Ve    # edge to the corner below
    deg = hl.astype(np.int8) + hr + vu + vd
    movable = deg == 2
    Y0, X0 = np.mgrid[0:h + 1, 0:w + 1].astype(np.float64)
    X, Y = X0.copy(), Y0.copy()

    def nbr_avg(A):
        s = np.zeros_like(A)
        s[:, 1:] += np.where(hl[:, 1:], A[:, :-1], 0)
        s[:, :-1] += np.where(hr[:, :-1], A[:, 1:], 0)
        s[1:, :] += np.where(vu[1:, :], A[:-1, :], 0)
        s[:-1, :] += np.where(vd[:-1, :], A[1:, :], 0)
        return s / np.maximum(deg, 1)

    for _ in range(iters):
        for f in (lam, mu):
            ax, ay = nbr_avg(X), nbr_avg(Y)
            X = np.where(movable, X + f * (ax - X), X)
            Y = np.where(movable, Y + f * (ay - Y), Y)
    dX = np.clip(X - X0, -clamp, clamp)
    dY = np.clip(Y - Y0, -clamp, clamp)
    # Two neighbouring corners must never (nearly) meet: a slicer welds them into a non-manifold
    # edge. Pull any such pair halfway back towards the grid until they are min_sep px apart.
    for _ in range(8):
        X, Y = X0 + dX, Y0 + dY
        close_ = np.zeros(X.shape, bool)
        for sy, sx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            ox, oy = _shift(X, sy, sx, np.inf), _shift(Y, sy, sx, np.inf)
            c = np.hypot(X - ox, Y - oy) < min_sep
            close_ |= c | _shift(c, -sy, -sx, False)
        if not close_.any():
            break
        dX = np.where(close_, dX * 0.5, dX)
        dY = np.where(close_, dY * 0.5, dY)
    X, Y = X0 + dX, Y0 + dY
    # Relax interior corners a little so the first row of faces follows the smoothed edge.
    free = deg == 0
    free[0, :] = free[-1, :] = False
    free[:, 0] = free[:, -1] = False
    for _ in range(4):
        for A in (X, Y):
            avg = np.zeros_like(A)
            avg[1:-1, 1:-1] = (A[:-2, 1:-1] + A[2:, 1:-1] + A[1:-1, :-2] + A[1:-1, 2:]) / 4.0
            A[free] = avg[free]
    return X, Y


def corner_count(mask):
    h, w = mask.shape
    c = np.zeros((h + 1, w + 1), dtype=np.int8)
    for dy in (0, 1):
        for dx in (0, 1):
            c[dy:dy + h, dx:dx + w] += mask
    return c


def mesh_from_mask(mask, ztop, zbot, px, origin, lattice=None):
    """Closed 2.5D solid for a pixel mask.

    ztop / zbot: corner height fields (H+1, W+1).
    origin: (row, col) of the grid point that maps to x=y=0.
    Returns (verts (N,3) float, faces (M,4) int) with outward-facing quads.
    """
    h, w = mask.shape
    pm = np.zeros((h + 2, w + 2), dtype=bool)
    pm[1:-1, 1:-1] = mask
    used = pm[:-1, :-1] | pm[:-1, 1:] | pm[1:, :-1] | pm[1:, 1:]   # (h+1, w+1)
    ci, cj = np.nonzero(used)
    n = len(ci)
    vid = np.full((h + 1, w + 1), -1, dtype=np.int64)
    vid[ci, cj] = np.arange(n)
    if lattice is None:
        x = (cj - origin[1]) * px
        y = (origin[0] - ci) * px
    else:
        x = (lattice[0][ci, cj] - origin[1]) * px
        y = (origin[0] - lattice[1][ci, cj]) * px
    verts = np.concatenate([
        np.stack([x, y, ztop[ci, cj]], axis=1),
        np.stack([x, y, zbot[ci, cj]], axis=1),
    ])
    T = vid            # top ids
    B = vid + n        # bottom ids (only valid where vid >= 0)
    pi, pj = np.nonzero(mask)
    # top quad CCW seen from +z: (i,j) (i+1,j) (i+1,j+1) (i,j+1) in (row, col) with y = -row
    top = np.stack([T[pi, pj], T[pi + 1, pj], T[pi + 1, pj + 1], T[pi, pj + 1]], axis=1)
    bot = np.stack([B[pi, pj], B[pi, pj + 1], B[pi + 1, pj + 1], B[pi + 1, pj]], axis=1)
    walls = []
    # right edge: neighbour (i, j+1) outside -> outward +x; corners (i,j+1) -> (i+1,j+1)
    m = mask & ~pm[1:-1, 2:]
    a, b = np.nonzero(m)
    walls.append(np.stack([B[a, b + 1], T[a, b + 1], T[a + 1, b + 1], B[a + 1, b + 1]], axis=1))
    # left edge: outward -x; corners (i,j), (i+1,j)
    m = mask & ~pm[1:-1, :-2]
    a, b = np.nonzero(m)
    walls.append(np.stack([B[a, b], B[a + 1, b], T[a + 1, b], T[a, b]], axis=1))
    # upper edge (row i-1 outside): outward +y; corners (i,j), (i,j+1)
    m = mask & ~pm[:-2, 1:-1]
    a, b = np.nonzero(m)
    walls.append(np.stack([B[a, b], T[a, b], T[a, b + 1], B[a, b + 1]], axis=1))
    # lower edge: outward -y; corners (i+1,j), (i+1,j+1)
    m = mask & ~pm[2:, 1:-1]
    a, b = np.nonzero(m)
    walls.append(np.stack([B[a + 1, b], B[a + 1, b + 1], T[a + 1, b + 1], T[a + 1, b]], axis=1))
    faces = np.concatenate([top, bot] + walls).astype(np.int64)
    return verts, faces


REGION_STYLES = ('PUFFED', 'PAINTED')
LINE_STYLES = ('AUTO', 'RAISED', 'FLUSH')


def _pairs(a, b, amask, bmask):
    """Unique (a, b) label pairs over 4-neighbour pixel contacts."""
    out = set()
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        bb = _shift(b, dy, dx, 0)
        bm = _shift(bmask, dy, dx, False)
        m = amask & bm
        if m.any():
            key = np.unique(a[m].astype(np.int64) * (1 << 31) + bb[m].astype(np.int64))
            out.update(zip((key >> 31).tolist(), (key & ((1 << 31) - 1)).tolist()))
    return out


def prepare(o):
    """Everything the per-part mesher needs that doesn't depend on styles (cached on o.ctx)."""
    px = o.px
    p = o.params
    T = p['cookie_thickness_mm']
    Rb = min(p['cookie_bevel_mm'], T * 0.9)
    dcc = _corner_dist(o.d_cookie, o.cookie, px)
    tt = np.clip(dcc / max(Rb, 1e-6), 0, 1)
    cookie_top_c = T - Rb + Rb * np.sqrt(1 - (1 - tt) ** 2)
    lines = o.top == 1
    mode = p.get('line_split') or 'ONE'
    if p.get('split_lines') and mode == 'ONE':
        mode = 'PIECES'
    if mode == 'STROKES' and lines.any():
        strokes, ns = segment_lines(lines, px)
    elif mode == 'PIECES' and lines.any():
        strokes, ns = label_components(lines)
    else:
        strokes, ns = lines.astype(np.int32), int(lines.any())
    LBASE = 1 << 20
    exact = p.get('outline_smooth_mm', 0) > 0      # heights from the smoothed outline geometry
    for it in range(6):
        combined = np.where(o.top > 1, o.top, np.where(lines, LBASE + strokes,
                                                       np.where(o.cookie, -1, 0))).astype(np.int64)
        if exact:
            # No part may touch itself only corner-to-corner (a non-manifold pinch), lines or regions.
            fixed = _fix_pinches(combined)
            if (fixed != combined).any():
                combined = fixed
                o.top = np.where(combined >= LBASE, 1, np.where(combined > 1, combined, 0)).astype(o.top.dtype)
                strokes = np.where(combined >= LBASE, combined - LBASE, 0).astype(strokes.dtype)
                lines = o.top == 1
        if mode not in ('STROKES', 'PIECES') or not lines.any() or p.get('geometry', 2) < 2:
            break
        # Every stroke one piece, no unprintable slivers (pinch fixes above can split a stroke too).
        n_old = len(np.unique(strokes[strokes > 0]))
        # (slivers once: later rounds only re-join pieces a pinch fix split off)
        cleaned, ns = clean_strokes(strokes, px, min_detail_mm=p.get('min_detail_mm', 0.5) if it == 0 else 0.0)
        same = ns == n_old and np.array_equal(cleaned > 0, strokes > 0) and \
            len(np.unique(cleaned.astype(np.int64) * (1 << 24) + strokes)) == ns + 1
        strokes = cleaned
        if not np.array_equal(strokes > 0, lines):
            o.top = np.where(lines & (strokes == 0), 0, o.top).astype(o.top.dtype)
            lines = o.top == 1
        # No whole part narrower than a printable dot (a stray bit or a drawn dot cut down by a gap)
        o.top, strokes, thin_changed = fix_thin_strokes(
            o.top, strokes, o.cookie, px, p.get('min_part_width_mm', 0.45), p.get('gap_mm', 0.42),
            p.get("min_part_floor_mm", 0.34))
        if thin_changed:
            lines = o.top == 1
            ns = len(np.unique(strokes[strokes > 0]))
            same = False
        if same:
            break
    combined = np.where(o.top > 1, o.top, np.where(lines, LBASE + strokes,
                                                   np.where(o.cookie, -1, 0))).astype(np.int64)
    lat = smooth_lattice(combined) if p.get("smooth_edges", True) else None
    regmask_ = o.top > 1
    sizes = np.bincount(strokes.ravel(), minlength=ns + 1)
    regmask = o.top > 1
    o.strokes = strokes
    o.ctx = dict(
        cookie_top_c=cookie_top_c, lat=lat, lines=lines, n_strokes=ns,
        stroke_order=sorted(range(1, ns + 1), key=lambda k: -sizes[k]),
        line_dc=(lattice_dist(lines, lat, px) if exact else _corner_dist(o.d_top, lines, px))
        if lines.any() else None,
        region_dc=lattice_dist(regmask_, lat, px) if exact and regmask_.any() else None,
        stroke_regions=_pairs(strokes, o.top, lines, regmask),       # (stroke, region label)
        stroke_strokes={(a, b) for a, b in _pairs(strokes, strokes, lines, lines) if a != b},
    )
    return o.ctx


def _corner_dist(d, m, px):
    """Pixel distance field -> corner lattice; corners on the mask edge get exactly 0."""
    dc = corner_average(d, m)
    full = corner_count(m) == 4
    return np.where(full, np.maximum(dc - 0.5 * px, 0.0), 0.0)


def _bead(d, hmax, hmin, r):
    tt = np.clip(d / max(r, 1e-6), 0, 1)
    return hmin + (hmax - hmin) * np.sqrt(1 - (1 - tt) ** 2)


def resolve_styles(o, region_style=None, region_bare=None, stroke_style=None):
    """Fill in defaults and resolve AUTO lines. Returns (region_style, region_bare, flush_strokes set)."""
    ctx = o.ctx if getattr(o, "ctx", None) else prepare(o)
    region_style = dict(region_style or {})
    region_bare = dict(region_bare or {})
    stroke_style = dict(stroke_style or {})
    touching = {}
    for st, lab in ctx['stroke_regions']:
        touching.setdefault(st, set()).add(lab)
    flush = set()
    for st in range(1, ctx['n_strokes'] + 1):
        style = stroke_style.get(st, 'AUTO')
        if style == 'FLUSH':
            flush.add(st)
        elif style == 'AUTO':
            col = [l for l in touching.get(st, ()) if not region_bare.get(l, False)]
            if o.params.get('seamless'):
                # Seamless: every line lies in the one surface unless it borders a puffed region
                if all(region_style.get(l, 'PUFFED') == 'PAINTED' for l in col):
                    flush.add(st)
            elif col and all(region_style.get(l, 'PUFFED') == 'PAINTED' for l in col):
                flush.add(st)
    return region_style, region_bare, flush


def p_seamless(o):
    return bool(o.params.get('seamless'))


def is_flat(verts):
    """True if the part's top is a constant height above its bottom (a seamless/flat part)."""
    n = len(verts) // 2
    d = verts[:n, 2] - verts[n:, 2]
    return n > 0 and float(np.ptp(d)) < 1e-6


def flush_field(o, region_style, region_bare, flush_strokes):
    """Corner height field (above the cookie) of the single painted surface, or None."""
    ctx = o.ctx
    painted = [l for l, s in region_style.items() if s == 'PAINTED' and not region_bare.get(l, False)]
    F = np.isin(o.top, painted) if painted else np.zeros(o.top.shape, bool)
    if flush_strokes:
        F |= ctx['lines'] & np.isin(o.strokes, list(flush_strokes))
    if not F.any():
        return None
    if p_seamless(o):
        return np.full(ctx['cookie_top_c'].shape, float(o.params['flush_height_mm']))
    bare = [l for l, b in region_bare.items() if b]
    open_ = (o.top == 0) | (np.isin(o.top, bare) if bare else False)
    p = o.params
    d = edt(open_) - 0.5
    dc = corner_average(d, F) * o.px
    dc = np.where(corner_count(open_) > 0, 0.0, np.maximum(dc - 0.5 * o.px, 0.0))
    return _bead(dc, p['flush_height_mm'], p['flush_edge_mm'], p['flush_round_mm'])


def part_mesh(o, kind, ident, region_style, flush_strokes, fflush):
    """(verts, quads) for one part. kind 'LINES' -> ident = stroke id, 'REGION' -> region label."""
    ctx = o.ctx
    p = o.params
    gh, gw = o.shape
    origin = (gh / 2.0, gw / 2.0)
    base = ctx['cookie_top_c']
    if kind == 'LINES':
        m = o.strokes == ident
        if ident in flush_strokes and fflush is not None:
            hc = fflush
        else:
            hc = _bead(ctx['line_dc'], p['line_height_mm'], p['line_edge_mm'], p['line_round_mm'])
    else:
        m = o.top == ident
        if region_style.get(ident, 'PUFFED') == 'PAINTED' and fflush is not None:
            hc = fflush
        else:
            rdc = ctx.get('region_dc')
            dc = np.where(corner_count(m) == 4, rdc, 0.0) if rdc is not None else _corner_dist(o.d_top, m, o.px)
            hc = _bead(dc, p['fill_height_mm'], p['fill_edge_mm'], p['fill_round_mm'])
    return mesh_from_mask(m, base + hc, base, o.px, origin, ctx['lat'])


def affected_parts(o, kind, ident):
    """Parts whose geometry can change when (kind, ident)'s style or bareness changes."""
    ctx = o.ctx
    regs, strs = set(), set()
    if kind == 'REGION':
        regs.add(ident)
        strs |= {s for s, l in ctx['stroke_regions'] if l == ident}
    else:
        strs.add(ident)
        strs |= {b for a, b in ctx['stroke_strokes'] if a == ident}
    regs |= {l for s, l in ctx['stroke_regions'] if s in strs}
    return regs, strs


def build_meshes(o, region_style=None, region_bare=None, stroke_style=None):
    """List of (kind, ident, verts, quads): cookie, every line stroke, every region."""
    ctx = prepare(o)
    rs, rb, fl = resolve_styles(o, region_style, region_bare, stroke_style)
    ff = flush_field(o, rs, rb, fl)
    gh, gw = o.shape
    zero = np.zeros_like(ctx['cookie_top_c'])
    v, f = mesh_from_mask(o.cookie, ctx['cookie_top_c'], zero, o.px, (gh / 2.0, gw / 2.0), ctx['lat'])
    out = [('COOKIE', 0, v, f)]
    for st in ctx['stroke_order']:
        v, f = part_mesh(o, 'LINES', st, rs, fl, ff)
        out.append(('LINES', st, v, f))
    for r in o.regions:
        if (o.top == r['label']).any():
            v, f = part_mesh(o, 'REGION', r['label'], rs, fl, ff)
            out.append(('REGION', r['label'], v, f))
    return out
