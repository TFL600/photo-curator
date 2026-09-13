#!/usr/bin/env python3
"""Check the Photos library for the one precondition the index model cannot see.

    python3 tools/check_albums.py

Every shortcut here resolves an album by *name*: Find Photos "Album is Triage",
Save to Photo Album "Triage", Remove from Album "Triage". PhotoKit does not
require album names to be unique, so two albums can share one, and then nothing
downstream is defined — which album a given action resolves to is not something
this repo controls or can check at build time.

That is worse than an error. If the three actions ever disagree, the album the
export enumerates is not the album the delete shortcut enumerates, indices mean
different assets on each side, and the delete lands on the wrong photos with
nothing to say so. A PHPhotosErrorDomain 3300 in that state is the good outcome.

So it is checked from outside, against the library itself, read-only.
"""

import os
import shutil
import sqlite3
import sys
import tempfile

LIBRARY = os.path.expanduser('~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite')
REQUIRED = ['Triage', 'Triaged']
# Only the sidecar categories. A missing one is not fatal — the export just tags
# nothing — but a duplicated one mis-stages thumbnails, so it is worth naming.
OPTIONAL = ['WhatsApp']


def albums(db):
    """Every user album, with its member count and when it was made."""
    rows = db.execute("""
        select a.Z_PK, a.ZTITLE,
               datetime(a.ZCREATIONDATE + 978307200, 'unixepoch', 'localtime'),
               (select count(*) from Z_33ASSETS j where j.Z_33ALBUMS = a.Z_PK)
          from ZGENERICALBUM a
         where a.ZTITLE is not null""").fetchall()
    out = {}
    for pk, title, created, members in rows:
        out.setdefault(title, []).append((pk, created, members))
    return out


def main():
    if not os.path.exists(LIBRARY):
        print(f'no Photos library at {LIBRARY}')
        return 1
    # Copy first: the live database is locked by Photos, and a read-only handle on
    # it still trips over the write-ahead log.
    tmp = tempfile.mkdtemp()
    try:
        for suffix in ('', '-wal', '-shm'):
            if os.path.exists(LIBRARY + suffix):
                shutil.copy(LIBRARY + suffix, os.path.join(tmp, 'p.sqlite' + suffix))
        db = sqlite3.connect(os.path.join(tmp, 'p.sqlite'))
        found = albums(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    problems = []
    for name in REQUIRED + OPTIONAL:
        copies = found.get(name, [])
        if len(copies) > 1:
            problems.append(
                f'{name}: {len(copies)} albums share this name. Every shortcut '
                f'resolves it by name, so which one they each get is undefined — '
                f'delete all but one in Photos. It does not matter which: the '
                f'export rebuilds Triage from scratch every run.')
            for pk, created, members in sorted(copies, key=lambda c: c[1]):
                problems.append(f'    created {created}, {members} item(s)')
        elif not copies and name in REQUIRED:
            problems.append(
                f'{name}: missing. Find Photos aborts the whole run with "Photo '
                f'album not found" and Shortcuts cannot recover from it.')
        elif copies:
            print(f'ok  {name}: 1 album, {copies[0][2]} item(s)')

    for p in problems:
        print(p if p.startswith('    ') else 'FAIL ' + p)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
