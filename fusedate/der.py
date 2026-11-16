"""Tiny DER reader: just enough X.509 to pull subject CN and validity."""
import base64, re
from datetime import datetime, timezone

PEM_RE = re.compile(rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.S)


def _tlv(buf, i):
    tag = buf[i]; i += 1
    ln = buf[i]; i += 1
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[i:i + n], "big"); i += n
    return tag, buf[i:i + ln], i + ln


def _children(buf):
    out, i = [], 0
    while i < len(buf):
        tag, val, i = _tlv(buf, i)
        out.append((tag, val))
    return out


def _time(tag, val):
    s = val.decode("ascii").rstrip("Z")
    if tag == 0x17:  # UTCTime YYMMDDHHMMSS
        yy = int(s[:2]); year = 1900 + yy if yy >= 50 else 2000 + yy
        s = f"{year}{s[2:]}"
    fmt = "%Y%m%d%H%M%S" if len(s) >= 14 else "%Y%m%d%H%M"
    return datetime.strptime(s[:14] if len(s) >= 14 else s[:12], fmt).replace(tzinfo=timezone.utc)


def _cn(name_val):
    for _, rdn in _children(name_val):
        for _, atv in _children(rdn):
            parts = _children(atv)
            if len(parts) == 2 and parts[0][1] == b"\x55\x04\x03":
                return parts[1][1].decode("utf-8", "replace")
    return None


def parse_cert(der):
    _, cert, _ = _tlv(der, 0)
    _, tbs, _ = _tlv(cert, 0)
    kids = _children(tbs)
    if kids and kids[0][0] == 0xA0:
        kids = kids[1:]
    # serial, sigalg, issuer, validity, subject
    validity = _children(kids[3][1])
    nb = _time(*validity[0]); na = _time(*validity[1])
    return {"subject_cn": _cn(kids[4][1]), "issuer_cn": _cn(kids[2][1]),
            "not_before": nb, "not_after": na}


def certs_in(data):
    for m in PEM_RE.finditer(data):
        b64 = re.sub(rb"\s+", b"", m.group(1))
        try:
            yield parse_cert(base64.b64decode(b64)), data[:m.start()].count(b"\n") + 1
        except Exception:
            continue
