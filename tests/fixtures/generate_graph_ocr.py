"""Deterministic original PNG graph exercises for OCR regression tests.

No external textbook images or answer screenshots are committed to the repository.
"""
from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


def font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_arrow(draw, end, start, radius=18):
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    tip = (end[0] - 39 * math.cos(angle), end[1] - 39 * math.sin(angle))
    left = (tip[0] - radius * math.cos(angle - 0.56), tip[1] - radius * math.sin(angle - 0.56))
    right = (tip[0] - radius * math.cos(angle + 0.56), tip[1] - radius * math.sin(angle + 0.56))
    draw.polygon([tip, left, right], fill="#111111")


def draw_node(draw, p, label, label_font):
    x, y = p
    r = 32
    draw.ellipse((x-r, y-r, x+r, y+r), fill="#ffffff", outline="#111111", width=5)
    box = draw.textbbox((0, 0), label, font=label_font)
    draw.text((x-(box[2]-box[0])/2, y-(box[3]-box[1])/2-box[1]),
              label, fill="#111111", font=label_font)


def build_one(which, target):
    im = Image.new("RGB", (1150, 680), "#ffffff")
    d = ImageDraw.Draw(im)
    title = {
        "directed": "Exercise 1: List all directed edges in graph G1.",
        "parallel": "Exercise 2: Count the parallel edges in undirected graph G2.",
        "simple": "Exercise 3: List every edge in undirected graph G3.",
    }[which]
    d.text((70, 45), title, font=font(33), fill="#111111")
    d.line((65, 111, 1085, 111), fill="#aaaaaa", width=2)

    p = {"A": (310, 295), "B": (815, 295), "C": (562, 550)}
    thick = 6
    if which == "directed":
        paths = [("A","B"),("B","C"),("C","A")]
        for a,b in paths:
            d.line((p[a],p[b]), fill="#111111", width=thick)
            draw_arrow(d, p[b], p[a])
    elif which == "parallel":
        # Two clearly separated parallel curved edges with endpoints at A and B.
        for control_y in (165, 430):
            pts = []
            for t in range(101):
                u = t / 100.0
                x = (1-u)**2*p["A"][0] + 2*(1-u)*u*562 + u*u*p["B"][0]
                y = (1-u)**2*p["A"][1] + 2*(1-u)*u*control_y + u*u*p["B"][1]
                pts.append((x,y))
            d.line(pts, fill="#111111", width=thick, joint="curve")
        d.line((p["B"],p["C"]), fill="#111111", width=thick)
    else:
        for a,b in (("A","B"),("B","C"),("A","C")):
            d.line((p[a],p[b]), fill="#111111", width=thick)
    for k,xy in p.items():
        draw_node(d,xy,k,font(30))
    target.parent.mkdir(parents=True, exist_ok=True)
    im.save(target, optimize=True)


def generate(output_dir):
    base = Path(output_dir)
    paths = {}
    for which in ("directed","parallel","simple"):
        dest = base / f"{which}.png"
        build_one(which,dest)
        paths[which] = dest
    return paths


if __name__ == "__main__":
    generate("artifacts/graph-fixtures")
