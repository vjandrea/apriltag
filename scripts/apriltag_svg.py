#!/usr/bin/env python3
"""Generate AprilTag SVGs named by label, with labels packed into tag IDs.

A spec file lists the label fields; each tag ID is the mixed-radix number of
its field values (first field most significant), so detection code can turn an
ID back into its label with decode() and no lookup table:

    {
      "family": "tagStandard41h12",
      "cell_px": 8,
      "fields": [
        ["CENTER", "CIRCLE"],
        ["A", "B", {"from": 1, "to": 12}],
        ["TL", "TR", "BL", "BR"]
      ]
    }

"CENTER A TL" is ID 0, "CENTER A TR" is 1, "CIRCLE 12 BR" is the last one.
An optional "only" list of glob patterns limits which tags are written, e.g.
["* TL", "* TR", "WALL L *"]; IDs don't change, so other labels keep theirs
reserved for later.
A value may contain single spaces ("BAR N", "CENTER C1"); files are named with
underscores, e.g. CENTER_C1_TL.svg.
Appending values to a field renumbers the fields before it, so add new values
only before printing, or add a new field at the front.

cell_px is the size of one tag cell in pixels, a whole number so every edge
lands on a pixel. Each SVG is a white sheet: the tag, a quiet zone of
"margin_cells" cells (default 1) and a footer row with the label and ID, so a
tagStandard41h12 sheet is 11 x 12 cells (88 x 96 px at cell_px 8).

Usage:
    apriltag_svg.py spec.json -o out/      write one <LABEL>.svg per tag
    apriltag_svg.py spec.json --decode 7   print the label of tag ID 7
"""

import argparse
import fnmatch
import itertools
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parent.parent
VALUE = re.compile(r"[A-Za-z0-9_.-]+( [A-Za-z0-9_.-]+)*")  # values become file names; single inner spaces allowed


def load_family(name, src=REPO):
    text = (src / f"{name}.c").read_text()

    def num(field):
        return int(re.search(rf"tf->{field} = (\w+);", text).group(1).replace("true", "1").replace("false", "0"))

    body = re.search(r"codedata\[\d+\] = \{(.*?)\};", text, re.S).group(1)
    nbits = num("nbits")
    return {
        "codes": [int(c, 16) for c in re.findall(r"0x([0-9a-fA-F]+)", body)],
        "nbits": nbits,
        "bit_x": [int(v) for v in re.findall(r"tf->bit_x\[\d+\] = (-?\d+);", text)],
        "bit_y": [int(v) for v in re.findall(r"tf->bit_y\[\d+\] = (-?\d+);", text)],
        "width_at_border": num("width_at_border"),
        "total_width": num("total_width"),
        "reversed_border": bool(num("reversed_border")),
    }


def tag_grid(fam, idx):
    """Rows of 1 (white), 0 (black) or None (not part of the tag: circle corners, 48h12's centre).

    Same layout as apriltag-imgs: a black and a white border ring (white inside on
    reversed-border families), then the data bits.
    """
    n, wab = fam["total_width"], fam["width_at_border"]
    grid = [[None] * n for _ in range(n)]
    black, white = (wab + 2, wab) if fam["reversed_border"] else (wab, wab + 2)
    for size, colour in ((black, 0), (white, 1)):
        s = (n - size) // 2
        for i in range(size):
            for x, y in ((s + i, s), (s + i, s + size - 1), (s, s + i), (s + size - 1, s + i)):
                grid[y][x] = colour
    bs = (n - wab) // 2
    code = fam["codes"][idx]
    for i in range(fam["nbits"]):
        grid[fam["bit_y"][i] + bs][fam["bit_x"][i] + bs] = (code >> (fam["nbits"] - 1 - i)) & 1
    return grid


def to_svg(grid, cell_px, title, caption, margin=1):
    """The tag on a white sheet: `margin` cells of quiet zone, then a footer row with the caption."""
    n = len(grid)
    black = []
    for y, row in enumerate(grid):
        for v, run in itertools.groupby(enumerate(row), key=lambda c: c[1]):
            cells = list(run)
            if v == 0:
                black.append(f"M{cells[0][0]} {y}h{len(cells)}v1h-{len(cells)}z")
    w, h = n + 2 * margin, n + 2 * margin + 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w * cell_px}" height="{h * cell_px}" '
        f'viewBox="{-margin} {-margin} {w} {h}">\n'
        f"<title>{escape(title)}</title>\n"
        f'<rect x="{-margin}" y="{-margin}" width="{w}" height="{h}" fill="#fff"/>\n'
        f'<path fill="#000" shape-rendering="crispEdges" d="{"".join(black)}"/>\n'
        f'<text x="{n / 2:g}" y="{n + margin + 0.75:g}" font-family="Helvetica, Arial, sans-serif" '
        f'font-size="0.7" font-weight="bold" text-anchor="middle">{escape(caption)}</text>\n'
        "</svg>\n"
    )


def field_values(spec):
    fields = []
    for field in spec["fields"]:
        values = []
        for v in field:
            values += [str(i) for i in range(v["from"], v["to"] + 1)] if isinstance(v, dict) else [str(v)]
        bad = [v for v in values if not VALUE.fullmatch(v)]
        if bad or len(set(values)) != len(values):
            raise SystemExit(f"field values must be unique and match {VALUE.pattern}: {field}")
        fields.append(values)
    return fields


def labels(fields):
    """All labels in ID order."""
    names = [" ".join(p) for p in itertools.product(*fields)]
    files = {file_name(n) for n in names}
    if len(files) != len(names):  # "A B"+"C" and "A"+"B C" would share a label
        raise SystemExit("two labels produce the same name; rename a field value")
    return names


def file_name(label):
    return label.replace(" ", "_") + ".svg"


def selected(spec, names):
    """(ID, label) pairs to write: all of them, or those matching spec["only"]."""
    only = spec.get("only")
    return [(i, n) for i, n in enumerate(names) if only is None or any(fnmatch.fnmatchcase(n, p) for p in only)]


def encode(fields, label):
    return labels(fields).index(label)


def decode(fields, idx):
    parts = []
    for values in reversed(fields):
        idx, r = divmod(idx, len(values))
        parts.append(values[r])
    if idx:
        raise ValueError("ID out of range for this spec")
    return " ".join(reversed(parts))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("."))
    ap.add_argument("--decode", type=int, metavar="ID")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text())
    fields = field_values(spec)
    if args.decode is not None:
        print(decode(fields, args.decode))
        return

    fam = load_family(spec["family"])
    names = labels(fields)
    if len(names) > len(fam["codes"]):
        raise SystemExit(f"{len(names)} labels, but {spec['family']} has only {len(fam['codes'])} IDs")
    cell, margin, n = spec["cell_px"], spec.get("margin_cells", 1), fam["total_width"]
    if not isinstance(cell, int) or cell < 1:
        raise SystemExit("cell_px must be a whole number of pixels")
    args.out.mkdir(parents=True, exist_ok=True)
    tags = selected(spec, names)
    for idx, label in tags:
        svg = to_svg(tag_grid(fam, idx), cell, f"{label} ({spec['family']} {idx})", f"{label} · {idx}", margin)
        (args.out / file_name(label)).write_text(svg, encoding="utf-8")
    print(f"{len(tags)} of {len(names)} tags in {args.out}, tag {n * cell} px, sheet {(n + 2 * margin) * cell} x {(n + 2 * margin + 1) * cell} px")


if __name__ == "__main__":
    main()
