import importlib.util
import tempfile
import unittest
from pathlib import Path

MOD_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'build.py'
spec = importlib.util.spec_from_file_location('monitor_build', MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestParsing(unittest.TestCase):
    def test_iem_stage(self):
        csv = b'station,valid(UTC),Stage,Flow\nWIPF1,2026-11-04 15:00,1.50,0\nWIPF1,2026-11-04 15:06,1.52,0\n'
        values = mod.parse_iem(csv)
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0]['v'], 1.5)
        self.assertTrue(values[0]['t'].endswith('+00:00'))

    def test_iem_primary(self):
        csv = b'station,valid,primary_value,secondary_value\nWIPF1,2026-11-04 15:00,2.2,\n'
        self.assertEqual(mod.parse_iem(csv)[0]['v'], 2.2)

    def test_coops(self):
        payload = b'{"data":[{"t":"2026-11-04 15:00","s":"3.2","d":"90","g":"4.0"}]}'
        parsed = mod.parse_coops(payload, 'wind')
        self.assertEqual(parsed[0]['direction'], 90)
        self.assertEqual(parsed[0]['speed'], 3.2)
        self.assertEqual(mod.parse_coops(b'{"predictions":[{"t":"2026-11-04 15:00","v":"0.45"}]}', 'predictions')[0]['v'], .45)

    def test_render_offline(self):
        with tempfile.TemporaryDirectory() as d:
            original_site = mod.SITE
            try:
                mod.SITE = Path(d)
                mod.render({'built_utc':'2026-11-04T15:00:00+00:00','williams_point':[{'t':'2026-11-04T15:00:00+00:00','v':1.5}], 'trident':{},'warnings':[]})
                html = (Path(d) / 'index.html').read_text()
                self.assertIn('Williams Point water level',html)
                self.assertIn('"v":1.5',html)
                self.assertTrue((Path(d) / '.nojekyll').exists())
            finally:
                mod.SITE = original_site


if __name__ == '__main__':
    unittest.main()
