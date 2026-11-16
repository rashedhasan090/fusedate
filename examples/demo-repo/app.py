import os

# TODO: remove this legacy auth shim after 2026-12-01 once mobile v3 is gone
def legacy_login(user):
    return user

# HACK until Jan 15, 2027: vendor rate limit is doubled during migration
RATE_LIMIT = 200

# Added 2024-03-01 (history note, not a fuse)
VERSION = "1.4.0"
