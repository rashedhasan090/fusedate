import argparse, json, sys
from datetime import date, datetime, timezone
from . import __version__
from .scan import scan, load_eol

KINDS = ["dated-comment", "config-expiry", "certificate", "runtime-eol"]


def status(f, today, within):
    left = (f.date - today).days
    if left < 0:
        return "LIT"      # already gone off
    if left <= within:
        return "SOON"
    return "LATER"


def render_text(fuses, today, within):
    if not fuses:
        return "fusedate: no dated fuses found.\n"
    out = [f"fusedate {__version__}: {len(fuses)} fuse(s), today={today}, soon=<= {within} days\n"]
    for group, title in (("LIT", "Already gone off"), ("SOON", f"Going off within {within} days"), ("LATER", "Later")):
        rows = [f for f in fuses if status(f, today, within) == group]
        if not rows:
            continue
        out.append(f"\n== {title} ({len(rows)}) ==")
        for f in rows:
            left = (f.date - today).days
            when = f"{-left}d ago" if left < 0 else ("today" if left == 0 else f"in {left}d")
            out.append(f"  {f.date}  {when:>9}  [{f.kind}] {f.path}:{f.line}  {f.what}")
            if f.detail:
                out.append(f"{'':26}{f.detail}")
    return "\n".join(out) + "\n"


def render_md(fuses, today, within):
    lines = [f"# fusedate report ({today})", "", "| Status | Date | Days | Kind | Where | What |", "|---|---|---|---|---|---|"]
    for f in fuses:
        lines.append(f"| {status(f, today, within)} | {f.date} | {(f.date - today).days} | {f.kind} | `{f.path}:{f.line}` | {f.what.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def _ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def render_ics(fuses, today, alarm_days):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//fusedate//EN", "CALSCALE:GREGORIAN"]
    for i, f in enumerate(fuses):
        if f.date < today:
            continue
        uid = f"{abs(hash((f.path, f.line, f.what, f.date))):x}-{i}@fusedate"
        L += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
              f"DTSTART;VALUE=DATE:{f.date.strftime('%Y%m%d')}",
              f"SUMMARY:{_ics_escape('fuse: ' + f.what)}",
              f"DESCRIPTION:{_ics_escape(f'{f.kind} at {f.path}:{f.line}. {f.detail}')}",
              "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-P{alarm_days}D",
              f"DESCRIPTION:{_ics_escape('fuse in ' + str(alarm_days) + ' days: ' + f.what)}", "END:VALARM",
              "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(L) + "\r\n"


def main(argv=None):
    p = argparse.ArgumentParser(prog="fusedate", description="Find dated time bombs in a repo: TODO-by-date comments, "
                                "config expiry keys, checked-in certificates, and EOL runtimes, on one timeline.")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD (reproducible CI)")
    p.add_argument("--within", type=int, default=30, help="days counted as SOON (default 30)")
    p.add_argument("--kind", action="append", choices=KINDS, help="only these kinds (repeatable)")
    p.add_argument("--format", choices=["text", "json", "md", "ics"], default="text")
    p.add_argument("--alarm-days", type=int, default=14, help="ics reminder lead time (default 14)")
    p.add_argument("--eol-file", help="JSON to extend/override the EOL table")
    p.add_argument("--hide-later", action="store_true", help="only show LIT and SOON")
    p.add_argument("--fail-on", choices=["lit", "soon", "never"], default="never",
                   help="exit 1 if any fuse already went off (lit) or goes off within --within (soon)")
    p.add_argument("--version", action="version", version=f"fusedate {__version__}")
    a = p.parse_args(argv)
    today = date.fromisoformat(a.today) if a.today else date.today()
    fuses = scan(a.path, load_eol(a.eol_file), set(a.kind) if a.kind else None)
    if a.hide_later:
        fuses = [f for f in fuses if status(f, today, a.within) != "LATER"]
    if a.format == "json":
        sys.stdout.write(json.dumps({"today": today.isoformat(), "within": a.within,
                                     "fuses": [dict(f.to_dict(today), status=status(f, today, a.within)) for f in fuses]}, indent=2) + "\n")
    elif a.format == "md":
        sys.stdout.write(render_md(fuses, today, a.within))
    elif a.format == "ics":
        sys.stdout.write(render_ics(fuses, today, a.alarm_days))
    else:
        sys.stdout.write(render_text(fuses, today, a.within))
    sts = {status(f, today, a.within) for f in fuses}
    if a.fail_on == "lit" and "LIT" in sts:
        return 1
    if a.fail_on == "soon" and sts & {"LIT", "SOON"}:
        return 1
    return 0
