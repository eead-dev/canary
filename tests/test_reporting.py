from contextlib import redirect_stdout, redirect_stderr
from html import escape
import io
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from canary.discover import main
from canary.fitting import discover_and_fit
from canary.observation import Frame
from canary.reporting import write_report


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.frames = [Frame(i, 0x123, bytes([i]) + bytes(7)) for i in range(3)]
        self.reference = [(0, 5), (1, 7), (2, 9)]
        self.results = discover_and_fit(self.frames, self.reference, top_n=2)

    def report(self, name="measurement"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "report.html"
            write_report(path, self.frames, self.reference, self.results, name)
            self.assertTrue(path.is_file())
            return path.read_text(encoding="utf-8")

    def test_file_sections_and_best_candidate(self):
        text = self.report()
        for section in ("CANary Signal Discovery Report", "Capture summary", "Best candidate",
                        "Fitted equation", "Reference vs reconstruction", "Top candidates",
                        "Pearson correlation", "RMSE", "MAE", "R-squared", "Aligned samples"):
            self.assertIn(section, text)
        self.assertIn("0x123", text)
        self.assertIn("physical = raw * 2 + (5)", text)
        self.assertIn("<dt>Start bit</dt><dd>0</dd>", text)
        self.assertIn("<dt>Length</dt><dd>8 bits</dd>", text)
        self.assertIn("<dt>Signed</dt><dd>no (unsigned)</dd>", text)

    def test_html_escaping(self):
        name = '<script>alert("x")</script>&\'test'
        text = self.report(name)
        self.assertIn(escape(name), text)
        self.assertNotIn(name, text)
        self.assertNotIn("<script", text)
        self.assertNotIn("&'test", text)

    def test_svg_data_and_self_contained(self):
        text = self.report()
        svg = ET.fromstring(re.search(r"<svg.*?</svg>", text, re.S).group())
        lines = svg.findall("{http://www.w3.org/2000/svg}polyline")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].attrib["points"], lines[1].attrib["points"])
        self.assertEqual(lines[0].attrib["points"].split(), ["75.00,330.00", "510.00,192.50", "945.00,55.00"])
        self.assertIn("<style>", text)
        for pattern in (r"<script\b", r"<link\b", r"\bsrc=", r"\bhref=", r"@import", r"url\("):
            self.assertIsNone(re.search(pattern, text))

    def test_empty_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            with self.assertRaisesRegex(ValueError, "no fitted candidate"):
                write_report(path, [], [], [], "measurement")
            self.assertFalse(path.exists())

    def test_cli_report_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref, report = [Path(directory) / p for p in ("can.csv", "ref.csv", "report.html")]
            can.write_text("timestamp,can_id,data\n" + "".join(
                f"{i},291,{i:02X} 00 00 00 00 00 00 00\n" for i in range(3)), encoding="utf-8")
            ref.write_text("timestamp,value\n0,5\n1,7\n2,9\n", encoding="utf-8")
            args = ["canary.discover", str(can), str(ref), "--value-column", "value", "--top", "2"]
            text = io.StringIO()
            with patch("sys.argv", args + ["--fit", "--report", str(report)]), redirect_stdout(text):
                main()
            self.assertTrue(report.exists())
            for value in ("CAN frames: 3", "Unique CAN IDs: 1", "Candidates searched: 44",
                          "Aligned samples (best): 3", "BEST CANDIDATE", "Start bit:",
                          "physical = raw * 2 + (5)", "RANKED TOP CANDIDATES", "#1", "#2", "Report written:"):
                self.assertIn(value, text.getvalue())
            for extra in (["--report", str(report)], ["--fit", "--report", str(can)],
                          ["--fit", "--report", str(report), "--output-reconstruction", str(report)]):
                with patch("sys.argv", args + extra), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        main()
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
