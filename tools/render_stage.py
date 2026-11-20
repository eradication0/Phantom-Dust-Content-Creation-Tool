"""Draw a stage's collision with its spawns (red) and orbs (blue): isometric + top-down PNG.
Needs Pillow (pip install pillow).

  python tools/render_stage.py <stNN.dat> <out.png>
"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pdstage import dat
from PIL import Image, ImageDraw

p, out = sys.argv[1], sys.argv[2]
b = open(p, 'rb').read()
tris = dat.triangles(b)
spawns = [s for l in dat.spawn_layouts(b) for s in l]

pal = {}
def colour(t, n):
    if t not in pal:
        h = (t * 0.61803) % 1.0
        pal[t] = tuple(int(255 * (0.45 + 0.45 * math.cos(2 * math.pi * (h + k / 3)))) for k in range(3))
    light = 0.35 + 0.65 * max(0.0, n[0] * 0.3 + n[1] * 0.8 + n[2] * 0.5)
    return tuple(int(c * light) for c in pal[t])

def view(proj, W, H, title):
    pts = [proj(v) for t in tris for v in t[:3]]
    mx, Mx = min(q[0] for q in pts), max(q[0] for q in pts)
    my, My = min(q[1] for q in pts), max(q[1] for q in pts)
    s = min((W - 40) / (Mx - mx), (H - 60) / (My - my))
    f = lambda q: (20 + (q[0] - mx) * s, 40 + (q[1] - my) * s)
    img = Image.new('RGB', (W, H), (20, 22, 28))
    d = ImageDraw.Draw(img)
    for t in sorted(tris, key=lambda t: sum(proj(v)[2] for v in t[:3])):
        d.polygon([f(proj(v)) for v in t[:3]], fill=colour(t[4], t[3]), outline=(0, 0, 0))
    for sp in spawns:
        for ob in sp.orbs:
            ox, oy = f(proj(ob))
            d.ellipse([ox - 3, oy - 3, ox + 3, oy + 3], fill=(80, 200, 255))
        sx, sy = f(proj(sp.pos))
        d.ellipse([sx - 5, sy - 5, sx + 5, sy + 5], fill=(255, 60, 60))
    d.text((10, 10), title, fill=(230, 230, 230))
    return img

c45 = math.cos(math.radians(45))
iso = lambda v: (v[0] * c45 - v[2] * c45, -v[1] * 0.9 + (v[0] * c45 + v[2] * c45) * 0.5, v[0] * c45 + v[2] * c45 + v[1] * 0.01)
top = lambda v: (v[0], v[2], v[1])
img = Image.new('RGB', (1600, 700))
img.paste(view(iso, 900, 700, '%s: %d collision tris (iso)  red=spawn blue=orb' % (os.path.basename(p), len(tris))), (0, 0))
img.paste(view(top, 700, 700, 'top-down (x right, z down)'), (900, 0))
img.save(out)
print('wrote', out)
