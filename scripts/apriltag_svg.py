#!/usr/bin/env python3
"""Generate AprilTag SVGs named by label, with labels packed into tag IDs.

A spec file lists the label fields; each tag ID is the mixed-radix number of
its field values (first field most significant), so detection code can turn an
ID back into its label with decode() and no lookup table:

    {
      "family": "tagStandard41h12",
      "tag_size_mm": 50,
      "fields": [
        ["CENTER", "CIRCLE"],
        ["A", "B", {"from": 1, "to": 12}],
        ["TL", "TR", "BL", "BR"]
      ]
    }

"CENTER A TL" is ID 0, "CENTER A TR" is 1, "CIRCLE 12 BR" is the last one.
Appending values to a field renumbers the fields before it, so add new values
only before printing, or add a new field at the front.

tag_size_mm is the detector's tag size (the edge where the black and white
borders meet, see README.md); the SVG is drawn larger to include the outer
border. Cells outside the tag (the corners of the circle families) are left
transparent.

Usage:
    apriltag_svg.py spec.json -o out/      write one <LABEL>.svg per tag
    apriltag_svg.py spec.json --decode 7   print the label of tag ID 7
"""

import argparse
import itertools
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VALUE = re.compile(r"[A-Za-z0-9_.-]+")  # values become file names


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


def to_svg(grid, edge_mm, title):
    n = len(grid)
    paths = {0: [], 1: []}
    for y, row in enumerate(grid):
        for v, run in itertools.groupby(enumerate(row), key=lambda c: c[1]):
            if v is not None:
                cells = list(run)
                paths[v].append(f"M{cells[0][0]} {y}h{len(cells)}v1h-{len(cells)}z")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{edge_mm:g}mm" height="{edge_mm:g}mm" '
        f'viewBox="0 0 {n} {n}" shape-rendering="crispEdges">\n'
        f"<title>{title}</title>\n"
        f'<path fill="#fff" d="{"".join(paths[1])}"/>\n'
        f'<path fill="#000" d="{"".join(paths[0])}"/>\n'
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
    return [" ".join(p) for p in itertools.product(*fields)]


def encode(fields, label):
    idx = 0
    for values, part in zip(fields, label.split(), strict=True):
        idx = idx * len(values) + values.index(part)
    return idx


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
    edge = spec["tag_size_mm"] * fam["total_width"] / fam["width_at_border"]
    args.out.mkdir(parents=True, exist_ok=True)
    for idx, label in enumerate(names):
        (args.out / f"{label.replace(' ', '_')}.svg").write_text(to_svg(tag_grid(fam, idx), edge, f"{label} ({spec['family']} {idx})"))
    print(f"{len(names)} tags in {args.out}, IDs 0-{len(names) - 1}, printed edge {edge:g} mm")


if __name__ == "__main__":
    main()
