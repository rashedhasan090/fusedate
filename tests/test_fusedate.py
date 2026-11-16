import io, json, os, tempfile, unittest
from contextlib import redirect_stdout
from datetime import date
from fusedate.cli import main
from fusedate.scan import scan, scan_text_dates, scan_runtimes, load_eol

HERE = os.path.dirname(__file__)
DEMO = os.path.join(HERE, "..", "examples", "demo-repo")


def run(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(list(args))
    return code, buf.getvalue()


class TextDates(unittest.TestCase):
    def kinds(self, rel, text):
        return [(f.kind, f.date) for f in scan_text_dates(rel, text)]

    def test_iso_todo_comment(self):
        self.assertEqual(self.kinds("a.py", "# TODO remove after 2026-12-01\n"), [("dated-comment", date(2026, 12, 1))])

    def test_wordy_date(self):
        self.assertEqual(self.kinds("a.js", "// workaround until Jan 15, 2027\n"), [("dated-comment", date(2027, 1, 15))])

    def test_history_note_ignored(self):
        self.assertEqual(self.kinds("a.py", "# Added 2024-03-01 for v2\n"), [])

    def test_date_in_code_not_comment_ignored(self):
        self.assertEqual(self.kinds("a.py", "x = '2026-12-01'  \n"), [])

    def test_config_expiry_key(self):
        self.assertEqual(self.kinds("f.yaml", "  expires: 2026-11-10\n"), [("config-expiry", date(2026, 11, 10))])

    def test_config_key_only_in_config_files(self):
        self.assertEqual(self.kinds("f.py", "expires = 2026-11-10\n"), [])

    def test_invalid_date_skipped(self):
        self.assertEqual(self.kinds("a.py", "# TODO remove by 2026-02-31\n"), [])

    def test_year_month_only(self):
        self.assertEqual(self.kinds("a.go", "// deprecated, delete by 2027-06\n"), [("dated-comment", date(2027, 6, 1))])


class Runtimes(unittest.TestCase):
    def test_workflow_matrix_and_runner(self):
        text = "jobs:\n  t:\n    runs-on: ubuntu-20.04\n    with:\n      python-version: ['3.8', '3.13']\n"
        got = {(f.what) for f in scan_runtimes(".github/workflows/ci.yml", text, load_eol())}
        self.assertIn("GitHub runner ubuntu-20.04 end of life", got)
        self.assertIn("Python 3.8 end of life", got)
        self.assertIn("Python 3.13 end of life", got)

    def test_runs_on_outside_workflows_ignored(self):
        self.assertEqual(list(scan_runtimes("notes.yml", "runs-on: ubuntu-20.04\n", load_eol())), [])

    def test_dockerfile_and_nvmrc(self):
        self.assertEqual([f.what for f in scan_runtimes("Dockerfile", "FROM node:18-alpine\n", load_eol())], ["Node.js 18 end of life"])
        self.assertEqual([f.what for f in scan_runtimes(".nvmrc", "v16.20.0\n", load_eol())], ["Node.js 16 end of life"])

    def test_eol_file_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"python": {"3.14": "2030-10-31"}}, fh)
        try:
            eol = load_eol(fh.name)
            self.assertEqual([f.date for f in scan_runtimes(".python-version", "3.14.0\n", eol)], [date(2030, 10, 31)])
        finally:
            os.unlink(fh.name)


class Certs(unittest.TestCase):
    def test_demo_cert_parsed(self):
        certs = [f for f in scan(DEMO) if f.kind == "certificate"]
        self.assertEqual(len(certs), 1)
        self.assertIn("internal.example.test", certs[0].what)
        self.assertEqual(certs[0].date, date(2026, 12, 6))


class Cli(unittest.TestCase):
    def test_text_groups(self):
        code, out = run(DEMO, "--today", "2026-11-16")
        self.assertEqual(code, 0)
        self.assertIn("Already gone off", out)
        self.assertIn("Going off within 30 days", out)
        self.assertNotIn("history note", out)

    def test_fail_on_lit_and_soon(self):
        self.assertEqual(run(DEMO, "--today", "2026-11-16", "--fail-on", "lit")[0], 1)
        self.assertEqual(run(DEMO, "--today", "2020-01-01", "--fail-on", "lit")[0], 0)
        self.assertEqual(run(DEMO, "--today", "2026-11-25", "--within", "7", "--fail-on", "soon", "--kind", "dated-comment")[0], 1)

    def test_json_status(self):
        _, out = run(DEMO, "--today", "2026-11-16", "--format", "json")
        data = json.loads(out)
        st = {f["what"]: f["status"] for f in data["fuses"]}
        self.assertEqual(st["expires = 2026-11-10"], "LIT")
        self.assertEqual(st["valid_until = 2027-03-31"], "LATER")

    def test_ics_only_future_with_alarm(self):
        _, out = run(DEMO, "--today", "2026-11-16", "--format", "ics", "--alarm-days", "7")
        self.assertTrue(out.startswith("BEGIN:VCALENDAR"))
        self.assertIn("DTSTART;VALUE=DATE:20261201", out)
        self.assertNotIn("20261110", out)
        self.assertIn("TRIGGER:-P7D", out)

    def test_hide_later_and_md(self):
        _, out = run(DEMO, "--today", "2026-11-16", "--hide-later", "--format", "md")
        self.assertIn("| LIT |", out)
        self.assertNotIn("LATER", out)


if __name__ == "__main__":
    unittest.main()
