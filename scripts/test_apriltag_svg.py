import unittest
from pathlib import Path

import apriltag_svg as m

# tag41_12_00123.png from AprilRobotics/apriltag-imgs: "#" black, " " white
TAG41_123 = [
    "     # # ",
    " ########",
    " #     ##",
    "##     # ",
    " #  ## # ",
    "##     # ",
    "##     # ",
    "######## ",
    "# #### # ",
]


class TestApriltagSvg(unittest.TestCase):
    def test_grid_matches_apriltag_imgs(self):
        grid = m.tag_grid(m.load_family("tagStandard41h12"), 123)
        self.assertEqual(["".join("#" if v == 0 else " " for v in row) for row in grid], TAG41_123)

    def test_circle_corners_are_transparent(self):
        grid = m.tag_grid(m.load_family("tagCircle21h7"), 0)
        self.assertIsNone(grid[0][0])
        self.assertIsNotNone(grid[0][4])

    def test_labels_pack_into_ids(self):
        fields = m.field_values({"fields": [["CENTER", "CIRCLE"], ["A", "B", {"from": 1, "to": 12}], ["TL", "TR", "BL", "BR"]]})
        names = m.labels(fields)
        self.assertEqual(len(names), 2 * 14 * 4)
        self.assertEqual(names[:2], ["CENTER A TL", "CENTER A TR"])
        self.assertEqual(names[-1], "CIRCLE 12 BR")
        for idx, label in enumerate(names):
            self.assertEqual(m.encode(fields, label), idx)
            self.assertEqual(m.decode(fields, idx), label)
        with self.assertRaises(ValueError):
            m.decode(fields, len(names))

    def test_values_may_contain_spaces(self):
        fields = m.field_values({"fields": [["BAR N", "L4", "CENTER C1"], ["TL", "BR"]]})
        self.assertEqual(m.decode(fields, 5), "CENTER C1 BR")
        self.assertEqual(m.encode(fields, "BAR N BR"), 1)
        self.assertEqual(m.file_name("CENTER C1 BR"), "CENTER_C1_BR.svg")

    def test_only_filters_without_renumbering(self):
        names = m.labels([["WALL L", "BAR N"], ["TL", "T2"]])
        self.assertEqual(m.selected({"only": ["* TL", "WALL L *"]}, names), [(0, "WALL L TL"), (1, "WALL L T2"), (2, "BAR N TL")])
        self.assertEqual(len(m.selected({}, names)), 4)

    def test_groups_must_not_overlap(self):
        import json, subprocess, sys, tempfile
        spec = {"family": "tagStandard41h12", "fields": [["A", "B"], ["TL", "TR"]],
                "groups": [{"only": ["A *"], "cell_px": 4}, {"only": ["* TL"], "cell_px": 8}]}
        with tempfile.TemporaryDirectory() as d:
            Path(d, "s.json").write_text(json.dumps(spec))
            run = subprocess.run([sys.executable, m.__file__, f"{d}/s.json", "-o", d], capture_output=True, text=True)
            self.assertIn("more than one group", run.stderr)
            spec["groups"][1]["only"] = ["B TL"]
            Path(d, "s.json").write_text(json.dumps(spec))
            subprocess.run([sys.executable, m.__file__, f"{d}/s.json", "-o", d], check=True, capture_output=True)
            self.assertIn('width="88"', Path(d, "B_TL.svg").read_text())
            self.assertIn('width="44"', Path(d, "A_TR.svg").read_text())

    def test_rejects_labels_that_collide(self):
        with self.assertRaises(SystemExit):
            m.labels([["A B", "A"], ["C", "B C"]])

    def test_rejects_unsafe_or_duplicate_values(self):
        for field in (["A/B"], ["A", "A"], ["A  B"], [" A"]):
            with self.assertRaises(SystemExit):
                m.field_values({"fields": [field]})


if __name__ == "__main__":
    unittest.main()
