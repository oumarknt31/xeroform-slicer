"""Build the XeroForm logo as SVG from its geometry.

The mark is a faithful vector redraw of the XeroForm logo (a cluster of seven
hexagons, three linked chains, side wings and a zig-zag base). It is rebuilt
from measured shapes rather than traced, so it stays crisp at any size.

    python tools/build_logo.py      # writes src/slicerkit/gui/assets/*.svg

Writes:
  xeroform-icon.svg  white mark on the black rounded tile (app icon)
  xeroform-mark.svg  the white mark alone, transparent background
"""
import math
import os

from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

ASSETS = os.path.join(os.path.dirname(__file__), os.pardir, "src", "slicerkit", "gui", "assets")


def hex_pointy(cx, cy, R):
    return Polygon([(cx + R * math.cos(math.radians(a)), cy + R * math.sin(math.radians(a))) for a in range(-90, 270, 60)])


def hex_flat(cx, cy, R):
    return Polygon([(cx + R * math.cos(math.radians(a)), cy + R * math.sin(math.radians(a))) for a in range(0, 360, 60)])


CX = 65.0
R = 10.4                      # body hexagons, 18 px across the flats
GAP = 1.0                     # half-width of the black separating lines


def mirror(g):
    return affinity.scale(g, xfact=-1, yfact=1, origin=(CX, 0))


# --- body: a flower of pointy-top hexagons plus the filled middle
hexes = [hex_pointy(CX, 26.4, R), hex_pointy(43, 40.4, R), hex_pointy(87, 40.4, R),
         hex_pointy(43, 66.0, R), hex_pointy(87, 66.0, R), hex_pointy(CX, 76.6, R)]
middle = Polygon([(56, 31), (74, 31), (78, 35), (78, 74), (52, 74), (52, 35)])
sides = box(40.5, 45, 52, 62)
body = unary_union(hexes + [middle, sides, mirror(sides)])

# --- side wings, cut off from the body by a black gap
# a slanted bar, cut square against a black vertical line at x ~ 39
wing = Polygon([(27.8, 57.0), (37.9, 50.9), (37.9, 56.2), (30.6, 58.5)])  # a wedge, pointing outwards
wings = [wing, mirror(wing)]
for side in (box(37.9, 48.6, 40.3, 61.0), mirror(box(37.9, 48.6, 40.3, 61.0))):
    body = body.difference(side)  # the black line between wing and body
body = body.difference(box(0, 0, 37.9, 200)).difference(mirror(box(0, 0, 37.9, 200)).buffer(0))     .union(unary_union([hex_pointy(43, 40.4, R), hex_pointy(43, 66.0, R)]).difference(box(37.9, 46.5, 200, 62)))     .union(mirror(unary_union([hex_pointy(43, 40.4, R), hex_pointy(43, 66.0, R)]).difference(box(37.9, 46.5, 200, 62))))
for w in wings:
    body = body.difference(w.buffer(GAP, join_style=2))

# --- zig-zag base band, separated from the body by a black zig-zag
zig = [(28.6, 73.6), (43, 81.6), (48.6, 78.4), (53.6, 81.2), (53.6, 84.6), (CX, 91.6)]
zig = zig + [(2 * CX - x, y) for x, y in reversed(zig[:-1])]
ext = [(zig[0][0] - 4, zig[0][1] - 2.2)] + zig + [(2 * CX - zig[0][0] + 4, zig[0][1] - 2.2)]
band = LineString(ext).buffer(2.3, cap_style=2, join_style=2, mitre_limit=3).intersection(
    box(28.6, 0, 2 * CX - 28.6, 200))  # ends cut straight down, like the original
# the body ends just above the band, following the zig-zag (the black line is the gap)
edge = [(x, y - 2.3 - 2.2 * GAP) for x, y in ext]
body = body.intersection(Polygon([(0, 0), (200, 0), (200, edge[-1][1])] + edge[::-1] + [(0, edge[0][1])]))

# --- three chains of small flat-top hex rings (shared corners), a triangle around the middle
# each chain: two hexagonal loops stretched along the chain, meeting at its middle (an "8")
A, B, H = 6.6, 3.2, 4.6          # half-length along the chain, shoulder offset, half-width
loop = Polygon([(A, 0), (B, H), (-B, H), (-A, 0), (-B, -H), (B, -H)])
def chain(cx, cy, angle):
    loops = []
    for sign in (-1, 1):
        g = affinity.translate(loop, sign * A, 0)
        g = affinity.rotate(g, angle, origin=(0, 0))
        loops.append(affinity.translate(g, cx, cy).exterior.buffer(0.95, join_style=2))
    return unary_union(loops)
chains = [chain(CX, 40.4, 0), chain(54.0, 59.4, 60), chain(2 * CX - 54.0, 59.4, -60)]
body = body.difference(unary_union(chains))
white = unary_union([body, band] + wings)

def path(geom):
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    out = []
    for p in polys:
        for ringc in [p.exterior, *p.interiors]:
            pts = list(ringc.coords)[:-1]
            out.append("M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z")
    return " ".join(out)



def main() -> None:
    d = path(white)
    icon = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 2 112 110">'
            '<rect x="10" y="2" width="112" height="110" rx="24" fill="#000"/>'
            f'<path fill="#fff" fill-rule="evenodd" d="{d}"/></svg>\n')
    x0, y0, x1, y1 = white.bounds
    pad = 1.5
    mark = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0 - pad:.2f} {y0 - pad:.2f} '
            f'{x1 - x0 + 2 * pad:.2f} {y1 - y0 + 2 * pad:.2f}">'
            f'<path fill="#fff" fill-rule="evenodd" d="{d}"/></svg>\n')
    os.makedirs(ASSETS, exist_ok=True)
    for name, svg in (("xeroform-icon.svg", icon), ("xeroform-mark.svg", mark)):
        with open(os.path.join(ASSETS, name), "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", name)


if __name__ == "__main__":
    main()
