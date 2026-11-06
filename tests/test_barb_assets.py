"""Check the scientific geometry of the saved Matplotlib symbols offline."""
import json
import math
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestBarbAssets(unittest.TestCase):
    def test_saved_matplotlib_speed_components(self):
        source = (ROOT / 'assets/vendor/matplotlib-barbs.js').read_text()
        glyphs = json.loads(source.split('Object.freeze(', 1)[1].removesuffix(');\n'))
        self.assertEqual(glyphs['version'], '3.10.8')
        self.assertEqual(glyphs['step_knots'], 5)
        self.assertEqual(len(glyphs['paths']), 141)
        self.assertEqual(glyphs['max_knots'], 700)
        # Canonical wind FROM north: feathered end is above the SVG origin.
        # Half feather is shorter and inset; a 50-knot flag is a filled triangle.
        self.assertEqual(glyphs['paths'][1], 'M0,14 L0,-14 L0,-8.75 L5.6,-10.5 L0,-8.75 Z')
        self.assertEqual(glyphs['paths'][2], 'M0,14 L0,-14 L11.2,-17.5 L0,-14 Z')
        self.assertEqual(glyphs['paths'][10], 'M0,14 L0,-14 L11.2,-10.5 L0,-7 Z')
        self.assertIn('L11.2,-10.5 L0,-7', glyphs['paths'][13])  # 65 = 50 + 10 + 5
        self.assertIn('L11.2,-7 L0,-3.5', glyphs['paths'][13])
        self.assertIn('L5.6,-1.75', glyphs['paths'][13])
        # Every allowed speed fits the symbol box at any bearing, including flags.
        for path, scale in zip(glyphs['paths'], glyphs['scales']):
            points = re.findall(r'[ML](-?[\d.]+),(-?[\d.]+)', path)
            self.assertTrue(points)
            self.assertTrue(0 < scale <= 1)
            self.assertLessEqual(max(math.hypot(float(x), float(y)) * scale for x, y in points), 25.001)


if __name__ == '__main__':
    unittest.main()
