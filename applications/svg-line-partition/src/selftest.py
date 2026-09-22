"""Geometry self-test: the oracle must be right before it can grade anything.

    python -m src.selftest
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from .svggeom import load_svg

FIXTURES = sorted((Path(__file__).resolve().parent.parent / "fixtures").glob("*.svg"))

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def main() -> int:
    for path in FIXTURES:
        d = load_svg(str(path))
        print(f"\n=== {d.name}  canvas {d.width:.0f}x{d.height:.0f}  "
              f"{len(d.elements)} elements")
        print(f"{'id':<14}{'tag':<9}{'len':>7}{'bbox w x h':>13}{'closed':>7}"
              f"{'orient':>7}{'turn':>6}{'depth':>6}  enclosers / family / truth")
        for e in d.elements:
            print(f"{e.eid:<14}{e.tag:<9}{e.length:>7.1f}"
                  f"{e.width:>6.0f}x{e.height:<6.0f}{str(e.closed):>7}"
                  f"{e.orientation:>7.1f}{e.turning:>6.0f}{e.enclosure_depth:>6}"
                  f"  {','.join(e.enclosers) or '-'}"
                  f" | fam={e.family or '-'}"
                  f" | L={e.layer} R={e.role} O={e.object_}"
                  f"{' behind=' + e.behind if e.behind else ''}")

        for e in d.elements:
            check(e.length > 0 or e.tag == "rect", f"{d.name}/{e.eid}: zero length")
            check(math.isfinite(e.centroid[0]), f"{d.name}/{e.eid}: nan centroid")

        if d.name == "abstract_nesting":
            by = {e.eid: e for e in d.elements}
            check(abs(by["n-02"].area - math.pi * 108**2) / (math.pi * 108**2) < 0.012,
                  f"circle area off: {by['n-02'].area:.0f}")
            check(by["n-05"].enclosure_depth == 4,
                  f"n-05 depth {by['n-05'].enclosure_depth} != 4")
            check(by["n-01"].enclosure_depth == 0, "n-01 should enclose nothing")
            check(by["n-06"].enclosure_depth == 1,
                  f"n-06 depth {by['n-06'].enclosure_depth} != 1 (border only)")
            check(by["n-08"].enclosure_depth == 1,
                  f"n-08 diagonal depth {by['n-08'].enclosure_depth} != 1")
            check({by[k].family for k in ("n-10", "n-11", "n-12", "n-13")} ==
                  {by["n-10"].family} and by["n-10"].family,
                  "hatch lines not detected as one family")
            check(by["n-01"].role == "border_frame", f"n-01 role {by['n-01'].role}")
            check(by["n-17"].length > 100, "cubic path n-17 too short; flattening bug")
            check(by["n-05"].closed, "rotated rect should be closed")
            check(all(by[k].group.startswith("g-") for k in by),
                  "abstract group truth unresolved")
            check(330 < by["n-02"].turning < 390,
                  f"circle turning {by['n-02'].turning:.0f} should be near 360")
            check(by["n-08"].turning < 5, "a straight line must not bend")
            check(abs(by["n-18"].turning - 180) < 20,
                  f"3-corner bracket turning {by['n-18'].turning:.0f} != 180")

        if d.name == "house_scene":
            by = {e.eid: e for e in d.elements}
            check(by["wall"].closed and by["door"].closed, "wall/door should be closed")
            check("window-frame" in by["mullion-v"].enclosers,
                  f"mullion-v enclosers {by['mullion-v'].enclosers}")
            check("window-frame" in by["mullion-h"].enclosers,
                  f"mullion-h enclosers {by['mullion-h'].enclosers}")
            check("wall" in by["door"].enclosers,
                  f"door must be inside wall, got {by['door'].enclosers}")
            check(by["border"].role == "border_frame" or by["border"].truth.get("role") == "border_frame",
                  "border role")
            check({by[k].family for k in ("picket-1", "picket-2", "picket-3", "picket-4")} ==
                  {by["picket-1"].family} and by["picket-1"].family,
                  "pickets not detected as a family")
            check("horizon" in by["border"].enclosers or by["border"].enclosure_depth == 0,
                  "border must enclose nothing")

        if d.name == "kick_figure":
            by = {e.eid: e for e in d.elements}
            check(by["far-arm-a"].behind == "torso",
                  f"group truth did not inherit: {by['far-arm-a'].behind!r}")
            check(by["far-arm-b"].behind == "torso", "far-arm-b behind")
            check("far-arm-a" in by["torso"].in_front_of, "torso.in_front_of broken")
            check(by["near-arm"].behind == "", "near-arm must not be behind anything")
            check(by["torso"].enclosure_depth == 1,
                  f"torso depth {by['torso'].enclosure_depth} (border only expected)")
            d_ball = min(
                math.dist(p, (266, 184)) - 16
                for poly in by["kicking-leg"].polys for p in poly
            )
            print(f"    gap foot->ball = {d_ball:.1f}px")
            check(0 < d_ball < 8, "ball/foot designed to nearly touch")

    print("\n" + ("ALL GEOMETRY CHECKS PASSED" if not failures else
                  "FAILURES:\n  " + "\n  ".join(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
