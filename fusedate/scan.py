"""Scanners. Each yields Fuse(date, kind, path, line, what, detail)."""
import json, os, re
from dataclasses import dataclass, asdict
from datetime import date, datetime
from .der import certs_in
from .eol import EOL

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox", ".mypy_cache"}
MAX_BYTES = 2_000_000


@dataclass
class Fuse:
    date: date
    kind: str
    path: str
    line: int
    what: str
    detail: str = ""

    def to_dict(self, today):
        d = asdict(self); d["date"] = self.date.isoformat()
        d["days_left"] = (self.date - today).days
        return d


MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
ISO = r"(?P<y>20\d\d)[-/.](?P<m>0?[1-9]|1[0-2])(?:[-/.](?P<d>0?[1-9]|[12]\d|3[01]))?"
WORDY = r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?P<wd>[0-3]?\d)(?:st|nd|rd|th)?,?\s+(?P<wy>20\d\d)"
DATE_RE = re.compile(rf"(?<![\d.]){ISO}(?![\d])|{WORDY}", re.I)

INTENT = re.compile(
    r"\b(remove|delete|drop|kill|rip\s*out|clean\s*up|revert|expire[sd]?|expiry|expiration|sunset|"
    r"deadline|deprecat\w*|until|no\s+later\s+than|by|after|before|revisit|valid[_\s-]?until|"
    r"not[_\s-]?after|end[_\s-]?of[_\s-]?life|eol|temporary|temp|hack|workaround|"
    r"todo|fixme|xxx)\b", re.I)
COMMENT = re.compile(r"(^\s*(#|//|/\*|\*|--|;|<!--|%|rem\b))|(\s(#|//)\s)|(/\*)|(<!--)", re.I)
CONFIG_KEY = re.compile(
    r"^\s*[\"']?(?P<key>[\w.-]*(expires?|expiry|expiration|valid[_-]?until|not[_-]?after|sunset|"
    r"end[_-]?date|deadline|eol)[\w.-]*)[\"']?\s*[:=]", re.I)
CONFIG_EXT = {".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties", ".tf", ".hcl"}


def _mkdate(m):
    try:
        if m.group("y"):
            return date(int(m.group("y")), int(m.group("m")), int(m.group("d") or 1))
        mon = MONTHS[m.group("mon").lower()[:3]]
        return date(int(m.group("wy")), mon, int(m.group("wd")))
    except (ValueError, TypeError, KeyError):
        return None


def walk(root):
    if os.path.isfile(root):
        yield root; return
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for f in sorted(fns):
            yield os.path.join(dp, f)


def read(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def scan_text_dates(rel, text):
    ext = os.path.splitext(rel)[1].lower()
    is_cfg = ext in CONFIG_EXT or os.path.basename(rel).startswith(".env")
    for n, line in enumerate(text.splitlines(), 1):
        if len(line) > 400:
            continue
        dm = list(DATE_RE.finditer(line))
        if not dm:
            continue
        km = CONFIG_KEY.match(line) if is_cfg else None
        if km:
            d = _mkdate(dm[0])
            if d:
                yield Fuse(d, "config-expiry", rel, n, f"{km.group('key')} = {d.isoformat()}", line.strip()[:160])
            continue
        if not COMMENT.search(line):
            continue
        im = INTENT.search(line)
        if not im:
            continue
        d = _mkdate(dm[0])
        if not d:
            continue
        # changelog-style history ("added 2021-03-01") is not a fuse: require intent word
        yield Fuse(d, "dated-comment", rel, n, f"'{im.group(0).lower()}' marker", line.strip()[:160])


def scan_certs(rel, data):
    for c, ln in certs_in(data):
        cn = c["subject_cn"] or "?"
        yield Fuse(c["not_after"].date(), "certificate", rel, ln,
                   f"cert CN={cn} notAfter", f"issuer={c['issuer_cn'] or '?'} notBefore={c['not_before'].date()}")


def _norm_py(v):
    m = re.match(r"^(\d)\.(\d+)", v.strip().strip("'\"").lstrip("v").lstrip("="))
    return f"{m.group(1)}.{m.group(2)}" if m else None


def _norm_node(v):
    m = re.match(r"^v?(\d+)", v.strip().strip("'\"").lstrip(">=~^"))
    return m.group(1) if m else None


RUNTIME_PATTERNS = [
    # (regex, family, normalizer)
    (re.compile(r"python-version\s*:\s*\[?\s*([^\]\n#]+)"), "python", _norm_py),
    (re.compile(r"node-version\s*:\s*\[?\s*([^\]\n#]+)"), "node", _norm_node),
    (re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(?:docker\.io/)?(?:library/)?python:([\w.-]+)", re.I | re.M), "python", _norm_py),
    (re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(?:docker\.io/)?(?:library/)?node:([\w.-]+)", re.I | re.M), "node", _norm_node),
    (re.compile(r"^\s*(?:image|container)\s*:\s*['\"]?(?:docker\.io/)?(?:library/)?python:([\w.-]+)", re.M), "python", _norm_py),
    (re.compile(r"^\s*(?:image|container)\s*:\s*['\"]?(?:docker\.io/)?(?:library/)?node:([\w.-]+)", re.M), "node", _norm_node),
]
RUNS_ON = re.compile(r"runs-on\s*:\s*\[?\s*([^\n#]+)")


def scan_runtimes(rel, text, eol):
    base = os.path.basename(rel)
    hits = []
    if base == ".python-version":
        hits.append((1, "python", _norm_py(text.splitlines()[0] if text.strip() else "")))
    if base in (".nvmrc", ".node-version"):
        hits.append((1, "node", _norm_node(text.splitlines()[0] if text.strip() else "")))
    for rx, fam, norm in RUNTIME_PATTERNS:
        for m in rx.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            for part in re.split(r"[,\s]+", m.group(1)):
                if part:
                    hits.append((ln, fam, norm(part)))
    is_wf = "/.github/workflows/" in "/" + rel.replace(os.sep, "/") and rel.endswith((".yml", ".yaml"))
    if is_wf:
        for m in RUNS_ON.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            for part in re.split(r"[,\s\[\]'\"]+", m.group(1)):
                if part:
                    hits.append((ln, "gha-runner", part))
    seen = set()
    for ln, fam, ver in hits:
        if not ver or (ln, fam, ver) in seen:
            continue
        seen.add((ln, fam, ver))
        d = eol.get(fam, {}).get(ver)
        if d:
            label = {"python": "Python", "node": "Node.js", "gha-runner": "GitHub runner"}[fam]
            yield Fuse(date.fromisoformat(d), "runtime-eol", rel, ln, f"{label} {ver} end of life",
                       "retired by GitHub" if fam == "gha-runner" else "upstream EOL, no more security fixes")


def load_eol(extra_path=None):
    eol = {k: dict(v) for k, v in EOL.items()}
    if extra_path:
        with open(extra_path) as fh:
            for fam, table in json.load(fh).items():
                eol.setdefault(fam, {}).update(table)
    return eol


def scan(root, eol=None, kinds=None):
    eol = eol or load_eol()
    kinds = kinds or {"dated-comment", "config-expiry", "certificate", "runtime-eol"}
    out = []
    for path in walk(root):
        data = read(path)
        if data is None or b"\x00" in data[:4096] and b"CERTIFICATE" not in data:
            continue
        rel = os.path.relpath(path, root) if os.path.isdir(root) else os.path.basename(path)
        if "certificate" in kinds and b"BEGIN CERTIFICATE" in data:
            out.extend(scan_certs(rel, data))
        text = data.decode("utf-8", "replace")
        if kinds & {"dated-comment", "config-expiry"}:
            out.extend(f for f in scan_text_dates(rel, text) if f.kind in kinds)
        if "runtime-eol" in kinds:
            out.extend(scan_runtimes(rel, text, eol))
    out.sort(key=lambda f: (f.date, f.path, f.line))
    return out
