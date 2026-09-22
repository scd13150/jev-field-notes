"""SVG line geometry: parse, flatten, and measure.

Pure standard library. Everything here is *exact* code work; nothing is
heuristic guesswork, because these numbers are the ground truth the Jev
judgments are scored against.

Any attribute named ``data-truth*`` is dropped from the records that leave this
module, so labels authored in a fixture can never reach the model.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable, Sequence

Point = tuple[float, float]
Matrix = tuple[float, float, float, float, float, float]  # a b c d e f
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)

TRUTH_PREFIX = "data-truth"
NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


# --------------------------------------------------------------------------- #
# transforms
# --------------------------------------------------------------------------- #

def mat_mul(m1: Matrix, m2: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def mat_apply(m: Matrix, p: Point) -> Point:
    a, b, c, d, e, f = m
    x, y = p
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(spec: str | None) -> Matrix:
    """Support the transforms a hand-written line drawing actually uses."""
    if not spec:
        return IDENTITY
    m = IDENTITY
    for name, args in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", spec):
        v = [float(x) for x in NUMBER_RE.findall(args)]
        name = name.lower()
        if name == "translate":
            dx, dy = v[0], (v[1] if len(v) > 1 else 0.0)
            cand = (1, 0, 0, 1, dx, dy)
        elif name == "scale":
            sx, sy = v[0], (v[1] if len(v) > 1 else v[0])
            cand = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate":
            ang = math.radians(v[0])
            cx, cy = (v[1], v[2]) if len(v) >= 3 else (0.0, 0.0)
            ca, sa = math.cos(ang), math.sin(ang)
            cand = mat_mul(
                mat_mul((1, 0, 0, 1, cx, cy), (ca, sa, -sa, ca, 0, 0)),
                (1, 0, 0, 1, -cx, -cy),
            )
        elif name == "skewx":
            t = math.tan(math.radians(v[0]))
            cand = (1, 0, t, 1, 0, 0)
        elif name == "skewy":
            t = math.tan(math.radians(v[0]))
            cand = (1, t, 0, 1, 0, 0)
        elif name == "matrix" and len(v) == 6:
            cand = tuple(v)  # type: ignore[arg-type]
        else:
            continue
        m = mat_mul(m, cand)
    return m


# --------------------------------------------------------------------------- #
# path flattening
# --------------------------------------------------------------------------- #

def _cubic(p0, p1, p2, p3, n=16) -> list[Point]:
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        a, b, c, d = mt**3, 3 * mt * mt * t, 3 * mt * t * t, t**3
        out.append(
            (
                a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
            )
        )
    return out


def _quad(p0, p1, p2, n=12) -> list[Point]:
    out = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        out.append(
            (
                mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1],
            )
        )
    return out


def _arc_to_cubits(p0, rx, ry, phi, large, sweep, p1):
    """Endpoint form -> centre form -> cubic segments (SVG impl spec F.6)."""
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [(p1,)]
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = max(rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p, 0.0)
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(num / den) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (p0[1] + p1[1]) / 2.0

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        length = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / length))) if length else 0.0
        return -a if ux * vy - uy * vx < 0 else a

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle(
        (x1p - cxp) / rx,
        (y1p - cyp) / ry,
        (-x1p - cxp) / rx,
        (-y1p - cyp) / ry,
    )
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    segs = []
    n = max(1, int(math.ceil(abs(delta) / (math.pi / 2 - 1e-9))))
    d = delta / n
    hoff = 4.0 / 3.0 * math.tan(d / 4.0)
    for _ in range(n):
        cos1, sin1 = math.cos(theta1), math.sin(theta1)
        theta2 = theta1 + d
        cos2, sin2 = math.cos(theta2), math.sin(theta2)
        pe1 = (cx + rx * cos1 * cos_phi - ry * sin1 * sin_phi,
               cy + rx * cos1 * sin_phi + ry * sin1 * cos_phi)
        pe2 = (cx + rx * cos2 * cos_phi - ry * sin2 * sin_phi,
               cy + rx * cos2 * sin_phi + ry * sin2 * cos_phi)
        t1 = (-rx * sin1 * cos_phi - ry * cos1 * sin_phi,
              -rx * sin1 * sin_phi + ry * cos1 * cos_phi)
        t2 = (-rx * sin2 * cos_phi - ry * cos2 * sin_phi,
              -rx * sin2 * sin_phi + ry * cos2 * cos_phi)
        segs.append(_cubic(pe1, (pe1[0] + hoff * t1[0], pe1[1] + hoff * t1[1]),
                           (pe2[0] - hoff * t2[0], pe2[1] - hoff * t2[1]), pe2, n=8))
        theta1 = theta2
    return [pt for seg in segs for pt in seg]


def flatten_path(d: str) -> list[list[Point]]:
    """Return subpaths (lists of points in user units of the element)."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", d)
    subs: list[list[Point]] = []
    cur: list[Point] = []
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    cmd = ""
    prev_ctrl: Point | None = None
    i = 0

    def num() -> float:
        nonlocal i
        val = float(tokens[i])
        i += 1
        return val

    def take() -> float | None:
        nonlocal i
        if i < len(tokens) and not re.match(r"[A-Za-z]", tokens[i]):
            return num()
        return None

    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"[A-Za-z]", tok):
            cmd = tok
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(start)
                    subs.append(cur)
                    cur = []
                pos = start
                cmd = ""
                continue
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = take(), take()
            if x is None or y is None:
                break
            pos = (x + pos[0] if rel else x, y + pos[1] if rel else y)
            if cur:
                subs.append(cur)
            cur = [pos]
            start = pos
            cmd = "l" if rel else "L"
            prev_ctrl = None
        elif c == "H":
            x = take()
            if x is None:
                break
            pos = (x + pos[0] if rel else x, pos[1])
            cur.append(pos)
            prev_ctrl = None
        elif c == "V":
            y = take()
            if y is None:
                break
            pos = (pos[0], y + pos[1] if rel else y)
            cur.append(pos)
            prev_ctrl = None
        elif c == "L":
            x, y = take(), take()
            if x is None or y is None:
                break
            pos = (x + pos[0] if rel else x, y + pos[1] if rel else y)
            cur.append(pos)
            prev_ctrl = None
        elif c == "C":
            vals = [take() for _ in range(6)]
            if any(v is None for v in vals):
                break
            p1, p2, p3 = _abs_rel(vals[:2], pos, rel), _abs_rel(vals[2:4], pos, rel), _abs_rel(vals[4:6], pos, rel)
            cur.extend(_cubic(pos, p1, p2, p3))
            pos, prev_ctrl = p3, p2
        elif c == "S":
            vals = [take() for _ in range(4)]
            if any(v is None for v in vals):
                break
            refl = prev_ctrl if prev_ctrl else pos
            p1 = (2 * pos[0] - refl[0], 2 * pos[1] - refl[1])
            p2, p3 = _abs_rel(vals[:2], pos, rel), _abs_rel(vals[2:4], pos, rel)
            cur.extend(_cubic(pos, p1, p2, p3))
            pos, prev_ctrl = p3, p2
        elif c == "Q":
            vals = [take() for _ in range(4)]
            if any(v is None for v in vals):
                break
            p1, p2 = _abs_rel(vals[:2], pos, rel), _abs_rel(vals[2:4], pos, rel)
            cur.extend(_quad(pos, p1, p2))
            pos, prev_ctrl = p2, p1
        elif c == "T":
            vals = [take() for _ in range(2)]
            if any(v is None for v in vals):
                break
            refl = prev_ctrl if prev_ctrl else pos
            p1 = (2 * pos[0] - refl[0], 2 * pos[1] - refl[1])
            p2 = _abs_rel(vals, pos, rel)
            cur.extend(_quad(pos, p1, p2))
            pos, prev_ctrl = p2, p1
        elif c == "A":
            vals = [take() for _ in range(7)]
            if any(v is None for v in vals):
                break
            rx, ry, rot, large, sweep = vals[:5]
            p1 = _abs_rel(vals[5:7], pos, rel)
            phi = math.radians(rot)
            cur.extend(
                _arc_to_cubits(
                    pos, rx, ry, phi, bool(int(large)), bool(int(sweep)), p1
                )
            )
            pos, prev_ctrl = p1, None
        else:
            i += 1
            continue
    if cur:
        subs.append(cur)
    return [s for s in subs if len(s) > 1]


def _abs_rel(pair, base: Point, rel: bool) -> Point:
    x, y = pair
    return (x + base[0] if rel else x, y + base[1] if rel else y)


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #

def polyline_len(pts: Sequence[Point]) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def bbox_of(polys: Iterable[Sequence[Point]]):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def polygon_area(pts: Sequence[Point]) -> float:
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def centroid(pts: Sequence[Point]) -> Point:
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def point_in_poly(pt: Point, poly: Sequence[Point]) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1) if y2 != y1 else x1
            if x < xin:
                inside = not inside
    return inside


def point_in_or_on_poly(pt: Point, poly: Sequence[Point], tol: float) -> bool:
    """Containment that forgives strokes landing exactly on a boundary, which is
    how window mullions, doors and floor lines are actually drawn."""
    if point_in_poly(pt, poly):
        return True
    for i in range(len(poly)):
        if point_seg_dist(pt, poly[i], poly[(i + 1) % len(poly)]) <= tol:
            return True
    return False


def resample(polys: Sequence[Sequence[Point]], step: float = 8.0) -> list[list[Point]]:
    """Re-space every stroke at a fixed arc-length step so curvature statistics
    do not depend on how densely a path command happened to be flattened."""
    out: list[list[Point]] = []
    for poly in polys:
        if len(poly) < 2:
            continue
        acc: list[Point] = [poly[0]]
        carry = 0.0
        for i in range(len(poly) - 1):
            a, b = poly[i], poly[i + 1]
            seg_len = math.dist(a, b)
            if seg_len == 0:
                continue
            travelled = carry
            while True:
                need = step - travelled
                if need > seg_len:
                    travelled += seg_len
                    break
                f = need / seg_len
                p = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                acc.append(p)
                a = p
                seg_len = math.dist(a, b)
                travelled = 0.0
                carry = 0.0
            carry = travelled
        if math.dist(acc[-1], poly[-1]) > step * 0.25:
            acc.append(poly[-1])
        out.append(acc)
    return out


def seg_intersect(a0, a1, b0, b1) -> bool:
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])

    d1, d2 = cross(b0, b1, a0), cross(b0, b1, a1)
    d3, d4 = cross(a0, a1, b0), cross(a0, a1, b1)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    return any(abs(v) < 1e-9 for v in (d1, d2, d3, d4))


def segments_of(polys: Sequence[Sequence[Point]]) -> list[tuple[Point, Point]]:
    return [(p[i], p[i + 1]) for p in polys for i in range(len(p) - 1)]


def min_distance(polys_a, polys_b) -> float:
    best = math.inf
    for a in segments_of(polys_a):
        for b in segments_of(polys_b):
            best = min(best, seg_seg_dist(a, b))
    return best


def seg_seg_dist(a, b) -> float:
    """Exact distance between two segments: 0 when they cross, else the nearest
    endpoint-to-segment distance."""
    if seg_intersect(a[0], a[1], b[0], b[1]):
        return 0.0
    return min(
        point_seg_dist(a[0], b[0], b[1]),
        point_seg_dist(a[1], b[0], b[1]),
        point_seg_dist(b[0], a[0], a[1]),
        point_seg_dist(b[1], a[0], a[1]),
    )


def seg_is_point(a, b) -> bool:
    return math.dist(a, b) < 1e-12


def point_seg_dist(p, a, b) -> float:
    if seg_is_point(a, b):
        return math.dist(p, a)
    vx, vy = b[0] - a[0], b[1] - a[1]
    t = ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / (vx * vx + vy * vy)
    t = max(0.0, min(1.0, t))
    return math.dist(p, (a[0] + t * vx, a[1] + t * vy))


def orientation_deg(polys: Sequence[Sequence[Point]]) -> float:
    """Length-weighted principal direction, folded to [0,180)."""
    x = y = 0.0
    wsum = 0.0
    for poly in polys:
        for i in range(len(poly) - 1):
            dx = poly[i + 1][0] - poly[i][0]
            dy = poly[i + 1][1] - poly[i][1]
            w = math.hypot(dx, dy)
            if w == 0:
                continue
            ang = math.atan2(dy, dx)
            x += w * math.cos(2 * ang)
            y += w * math.sin(2 * ang)
            wsum += w
    if wsum == 0:
        return 0.0
    return (math.degrees(math.atan2(y, x)) / 2.0) % 180.0


def turning_total(polys: Sequence[Sequence[Point]], min_seg: float = 1e-6) -> float:
    """Total absolute turning in degrees: 0 for a straight line, ~360 for a
    convex closed loop. Feed it a resampled polyline, not a raw flattening."""
    def turn(a, b, c) -> float:
        if math.dist(a, b) < min_seg or math.dist(b, c) < min_seg:
            return 0.0
        v1 = math.atan2(b[1] - a[1], b[0] - a[0])
        v2 = math.atan2(c[1] - b[1], c[0] - b[0])
        d = (v2 - v1 + math.pi) % (2 * math.pi) - math.pi
        return abs(math.degrees(d))

    total = 0.0
    for poly in polys:
        for i in range(1, len(poly) - 1):
            total += turn(poly[i - 1], poly[i], poly[i + 1])
        if len(poly) > 4 and math.dist(poly[0], poly[-1]) < 1e-6:
            # closed loop: the seam vertex is the one the range() above skips
            total += turn(poly[-2], poly[0], poly[1])
    return total


# --------------------------------------------------------------------------- #
# document model
# --------------------------------------------------------------------------- #

@dataclass
class Element:
    eid: str
    tag: str
    group_path: tuple[str, ...]
    depth: int
    polys: list[list[Point]]
    attrs: dict[str, str] = field(default_factory=dict)
    truth: dict[str, str] = field(default_factory=dict)

    # derived, filled by analyse()
    length: float = 0.0
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    centroid: Point = (0.0, 0.0)
    closed: bool = False
    area: float = 0.0
    orientation: float = 0.0
    turning: float = 0.0
    subpaths: int = 1
    enclosure_depth: int = 0
    enclosers: list[str] = field(default_factory=list)
    region: str = ""
    role: str = ""
    layer: str = ""
    object_: str = ""
    group: str = ""
    family: str = ""
    in_front_of: list[str] = field(default_factory=list)
    behind: str = ""

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class Drawing:
    name: str
    width: float
    height: float
    elements: list[Element]

    def by_id(self, eid: str) -> Element:
        return next(e for e in self.elements if e.eid == eid)


def _clean_attrs(el: ET.Element) -> tuple[dict[str, str], dict[str, str]]:
    attrs, truth = {}, {}
    for k, v in el.attrib.items():
        bare = k.split("}")[-1]
        if bare.startswith(TRUTH_PREFIX):
            truth[bare[len(TRUTH_PREFIX) + 1:] if len(bare) > len(TRUTH_PREFIX) else bare] = v
        else:
            attrs[bare] = v
    return attrs, truth


def _shape_polys(tag: str, a: dict[str, str], m: Matrix) -> list[list[Point]]:
    def T(p):
        return mat_apply(m, p)

    if tag == "rect":
        x, y = float(a.get("x", 0)), float(a.get("y", 0))
        w, h = float(a.get("width", 0)), float(a.get("height", 0))
        return [[T((x, y)), T((x + w, y)), T((x + w, y + h)), T((x, y + h)), T((x, y))]]
    if tag == "circle":
        cx, cy, r = float(a.get("cx", 0)), float(a.get("cy", 0)), float(a.get("r", 0))
        pts = [T((cx + r * math.cos(2 * math.pi * i / 64),
                  cy + r * math.sin(2 * math.pi * i / 64))) for i in range(65)]
        return [pts]
    if tag == "ellipse":
        cx, cy = float(a.get("cx", 0)), float(a.get("cy", 0))
        rx, ry = float(a.get("rx", 0)), float(a.get("ry", 0))
        pts = [T((cx + rx * math.cos(2 * math.pi * i / 64),
                  cy + ry * math.sin(2 * math.pi * i / 64))) for i in range(65)]
        return [pts]
    if tag == "line":
        return [[T((float(a.get("x1", 0)), float(a.get("y1", 0)))),
                 T((float(a.get("x2", 0)), float(a.get("y2", 0))))]]
    if tag in ("polyline", "polygon"):
        v = [float(x) for x in NUMBER_RE.findall(a.get("points", ""))]
        pts = [T((v[i], v[i + 1])) for i in range(0, len(v) - 1, 2)]
        if tag == "polygon" and len(pts) > 2:
            pts.append(pts[0])
        return [pts]
    if tag == "path":
        subs = flatten_path(a.get("d", ""))
        return [[T(p) for p in s] for s in subs]
    return []


SHAPE_TAGS = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"}


def load_svg(path: str) -> Drawing:
    root = ET.parse(path).getroot()
    vb = (root.attrib.get("viewBox") or "").split()
    if len(vb) == 4:
        w, h = float(vb[2]), float(vb[3])
    else:
        w = float((root.attrib.get("width") or "300").strip("px"))
        h = float((root.attrib.get("height") or "300").strip("px"))
    name = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]

    elements: list[Element] = []
    seen: set[str] = set()

    def walk(node: ET.Element, m: Matrix, gpath: tuple[str, ...], inherited: dict[str, str]):
        tag = node.tag.split("}")[-1]
        attrs, own_truth = _clean_attrs(node)
        truth = {**inherited, **own_truth}  # <g data-truth-behind="..."> applies to children
        local = mat_mul(m, parse_transform(attrs.get("transform")))
        path_here = gpath
        if tag == "g":
            gid = attrs.get("id") or f"group{len(gpath) + 1}"
            path_here = gpath + (gid,)
        for child in list(node):
            walk(child, local, path_here, truth)
        if tag in SHAPE_TAGS:
            polys = _shape_polys(tag, attrs, local)
            if not polys:
                return
            eid = attrs.get("id") or f"{tag}{len(elements) + 1}"
            while eid in seen:
                eid = f"{eid}-x"
            seen.add(eid)
            elements.append(
                Element(eid=eid, tag=tag, group_path=gpath, depth=len(gpath),
                        polys=polys, attrs=attrs, truth=dict(truth))
            )

    for child in list(root):
        walk(child, IDENTITY, (), {})

    d = Drawing(name=name, width=w, height=h, elements=elements)
    analyse(d)
    return d


def region_of(c: Point, w: float, h: float) -> str:
    col = min(2, int(c[0] / (w / 3.0))) if w else 1
    row = min(2, int(c[1] / (h / 3.0))) if h else 1
    return ["top-left", "top", "top-right"][col] if row == 0 else (
        ["left", "centre", "right"][col] if row == 1 else (
            ["bottom-left", "bottom", "bottom-right"][col]))


def analyse(d: Drawing) -> None:
    """Attach the exact geometric facts that define the partition vocabulary."""
    diag = math.hypot(d.width, d.height)
    for e in d.elements:
        e.length = sum(polyline_len(p) for p in e.polys)
        e.bbox = bbox_of(e.polys)
        allpts = [p for poly in e.polys for p in poly]
        e.centroid = centroid(allpts)
        e.closed = any(
            len(p) > 3 and math.dist(p[0], p[-1]) < 1e-6 for p in e.polys
        )
        e.area = sum(polygon_area(p) for p in e.polys if len(p) > 3 and
                     math.dist(p[0], p[-1]) < 1e-6) or 0.0
        e.orientation = orientation_deg(e.polys)
        e.turning = turning_total(resample(e.polys))
        e.subpaths = len(e.polys)
        e.region = region_of(e.centroid, d.width, d.height)
        e.family = ""

    # enclosure: a closed shape A encloses B when every sampled point of B sits
    # inside A (boundary contact forgiven) and A carries more area than B.
    tol = max(1.5, 0.004 * diag)
    closed = [e for e in d.elements if e.closed and e.area > 4]
    for b in d.elements:
        b.enclosers = []
        pts = [p for poly in b.polys for p in poly]
        for a in closed:
            if a is b or a.area <= b.area * 1.05:
                continue
            if all(point_in_or_on_poly(p, a.polys[0], tol) for p in pts):
                b.enclosers.append(a.eid)
        b.enclosers.sort(key=lambda i: -d.by_id(i).area)
    for e in d.elements:
        e.enclosure_depth = len(e.enclosers)

    # near-duplicate parallel strokes -> a hatch / texture family
    for e in d.elements:
        if e.family or e.length > diag * 0.6 or e.closed:
            continue
        peers = [
            f for f in d.elements
            if f is not e and not f.closed and f.family == ""
            and abs(f.length - e.length) < max(6.0, 0.18 * e.length)
            and (abs(f.orientation - e.orientation) % 180) < 14
            and min_distance(e.polys, f.polys) < max(36.0, 0.16 * diag)
        ]
        if len(peers) >= 2:
            fam = f"family-{e.eid}"
            e.family = fam
            for f in peers:
                f.family = fam

    for e in d.elements:
        e.truth.setdefault("behind", "")
        e.behind = e.truth.get("behind", "")
        e.object_ = e.truth.get("object", "")
        e.group = e.truth.get("group", "") or e.object_
        e.layer = e.truth.get("layer", "")
        e.role = e.truth.get("role", "")

    # abstract fixtures carry no authored labels: derive the vocabulary from
    # geometry so the definitions stay exact and checkable.
    if all(not e.layer for e in d.elements):
        for e in d.elements:
            n = len(e.enclosers)
            e.layer = {0: "far", 1: "mid"}.get(n, "near")
        for e in d.elements:
            if e.bbox[2] - e.bbox[0] > 0.93 * d.width and e.bbox[3] - e.bbox[1] > 0.9 * d.height:
                e.layer, e.role = "frame", "border_frame"
            elif e.family:
                e.role = "repeated_texture"
            elif len(e.enclosers) >= 2 and e.length < 0.15 * diag:
                e.role = "interior_detail"
            elif not e.closed and e.length > 0.55 * diag:
                e.role = "ground_plane_line"
            else:
                e.role = "object_outline"
    for e in d.elements:
        for other in d.elements:
            if other.eid == e.behind:
                other.in_front_of.append(e.eid)
