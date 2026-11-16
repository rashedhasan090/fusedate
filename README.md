# fusedate

**Find the time bombs in a repo before the date goes off.**

Every codebase has dates buried in it that nobody owns: a `TODO: remove after 2026-12-01`, a feature flag with `expires: 2026-11-10`, a test certificate someone committed that dies next month, a CI matrix still running a Python that stopped getting security fixes. Each one is found by a different tool, if at all, and none of them tell you *when* things break.

`fusedate` is one offline, stdlib-only Python CLI that collects all of those dated fuses, puts them on a single timeline, and sorts them into **LIT** (already gone off), **SOON** (within N days), and **LATER**. It can fail CI when something is about to blow, or export an `.ics` calendar so the fuses show up next to your meetings with a reminder ahead of time.

## What's novel

- **One timeline across four unrelated sources of expiry**, not four separate linters:
  1. **dated-comment**: comments with an intent word (remove, until, by, after, sunset, deprecated, TODO, FIXME, HACK, temporary, ...) plus a date in ISO (`2026-12-01`, `2027-06`) or wordy form (`Jan 15, 2027`). History notes like `# Added 2024-03-01` are ignored because they lack an intent word.
  2. **config-expiry**: keys like `expires`, `expiry`, `valid_until`, `not_after`, `sunset`, `end_date`, `deadline` in YAML/JSON/TOML/INI/.env/Terraform files.
  3. **certificate**: every PEM certificate checked into the repo, decoded by a tiny built-in DER reader (no `cryptography`, no `openssl` needed) for CN and `notAfter`.
  4. **runtime-eol**: Python/Node versions in GitHub Actions matrices, `setup-*` steps, Dockerfile `FROM`, `image:` lines, `.python-version`, `.nvmrc`, plus retired GitHub-hosted runners (`ubuntu-20.04`, `macos-12`, ...), matched against a built-in EOL table you can extend with `--eol-file`.
- **Calendar export** (`--format ics`): each future fuse becomes an all-day event with a `VALARM` reminder `--alarm-days` before it fires. Subscribe your team calendar to the CI artifact.
- **Reproducible CI**: `--today YYYY-MM-DD` pins the clock, so a report or test never changes by itself.

## Install

```bash
pip install git+https://github.com/rashedhasan090/fusedate
# or run from a checkout, no install needed
python3 -m fusedate .
```

Requires Python 3.9+. No dependencies.

## Usage

```bash
fusedate .                                   # text timeline
fusedate . --within 14 --hide-later          # only what's lit or due in two weeks
fusedate . --format json > fuses.json
fusedate . --format md >> $GITHUB_STEP_SUMMARY
fusedate . --format ics --alarm-days 7 > fuses.ics
fusedate . --kind certificate --kind runtime-eol
fusedate . --fail-on soon --within 30         # exit 1 if anything is lit or due in 30 days
fusedate . --eol-file my-eol.json             # {"python": {"3.14": "2030-10-31"}}
```

### GitHub Actions

```yaml
- run: pip install git+https://github.com/rashedhasan090/fusedate
- run: fusedate . --format md --hide-later >> "$GITHUB_STEP_SUMMARY"
- run: fusedate . --fail-on lit
```

## Demo

`examples/demo-repo` has a workflow, Dockerfile, feature-flag YAML, a source file with dated comments, and a self-signed certificate.

```text
$ fusedate examples/demo-repo --today 2026-11-16
fusedate 0.1.0: 11 fuse(s), today=2026-11-16, soon=<= 30 days


== Already gone off (6) ==
  2025-04-15   580d ago  [runtime-eol] .github/workflows/ci.yml:5  GitHub runner ubuntu-20.04 end of life
                          retired by GitHub
  2025-10-31   381d ago  [runtime-eol] .github/workflows/ci.yml:8  Python 3.9 end of life
                          upstream EOL, no more security fixes
  2026-04-30   200d ago  [runtime-eol] .github/workflows/ci.yml:12  Node.js 20 end of life
                          upstream EOL, no more security fixes
  2026-10-31    16d ago  [runtime-eol] .github/workflows/ci.yml:8  Python 3.10 end of life
                          upstream EOL, no more security fixes
  2026-10-31    16d ago  [runtime-eol] Dockerfile:1  Python 3.10 end of life
                          upstream EOL, no more security fixes
  2026-11-10     6d ago  [config-expiry] flags.yaml:4  expires = 2026-11-10
                          expires: 2026-11-10

== Going off within 30 days (2) ==
  2026-12-01     in 15d  [dated-comment] app.py:3  'todo' marker
                          # TODO: remove this legacy auth shim after 2026-12-01 once mobile v3 is gone
  2026-12-06     in 20d  [certificate] certs/internal-ca.pem:1  cert CN=internal.example.test notAfter
                          issuer=internal.example.test notBefore=2026-11-16

== Later (3) ==
  2027-01-15     in 60d  [dated-comment] app.py:7  'hack' marker
                          # HACK until Jan 15, 2027: vendor rate limit is doubled during migration
  2027-03-31    in 135d  [config-expiry] flags.yaml:7  valid_until = 2027-03-31
                          valid_until: 2027-03-31
  2028-10-31    in 715d  [runtime-eol] .github/workflows/ci.yml:8  Python 3.12 end of life
                          upstream EOL, no more security fixes
```

Note that `# Added 2024-03-01 (history note, not a fuse)` in `app.py` is correctly left out.

## Limits

- The EOL table is a snapshot of upstream dates (Python, Node.js, GitHub runners) at release time; extend or override it with `--eol-file`.
- Dated comments need both a comment marker and an intent word on the same line, which keeps noise low but can miss free-form prose.
- Only PEM certificates are decoded; DER binaries and keystores are skipped.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## License

MIT
