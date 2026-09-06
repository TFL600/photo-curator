#!/usr/bin/env python3
"""Diff a generated Shortcut against what Shortcuts actually stored on import.

    python3 tools/roundtrip_check.py

Run this straight after importing the built shortcuts on the Mac, before touching
the phone. Shortcuts normalises and, when a parameter key is wrong for an action,
quietly drops it — the action still imports, its input chip is just empty. That is
invisible in the editor unless you know exactly which chip to look at, and it is
invisible at runtime because the shortcut runs and does nothing.

Reading the stored plist back out of Shortcuts.sqlite and diffing it against the
source makes that failure loud and free: any key that went in and did not come out
is printed here.
"""

import os
import plistlib
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_shortcuts import SHORTCUTS                                 # noqa: E402

DB = os.path.expanduser('~/Library/Shortcuts/Shortcuts.sqlite')


def stored_actions(name):
    """The newest shortcut with this name, plus how many share it.

    Deleting a shortcut on the phone does not remove the row here until iCloud
    catches up, so a re-import leaves two rows with the same name. Taking the
    first one silently compares against the version that was just replaced.
    Duplicates matter beyond this check: the app opens shortcuts by name, so two
    live rows means the app may run either one.
    """
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    # Importing over an existing name does not replace it: Shortcuts keeps both and
    # suffixes one of them, and which one gets the clean name is not predictable.
    # So look for "Name" and "Name 1", "Name 2", ... together.
    rows = db.execute(
        "select ZNAME, ZACTIONS from ZSHORTCUT where ZNAME = ? or ZNAME glob ? "
        "order by ZMODIFICATIONDATE desc", (name, name + ' [0-9]*')).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        others = ', '.join(repr(r[0]) for r in rows)
        print(f'STALE COPIES: {len(rows)} shortcuts match {name!r} — {others}. '
              f'Delete all of them and import once; the app opens shortcuts by '
              f'name and older copies are easy to tap by mistake.')
    # Compare against the copy holding the exact name, because that is the one the
    # app will open. Not the most recently modified one: renaming a shortcut bumps
    # its modification date, so the copy Shortcuts just pushed aside to make room
    # for the new import looks newest of all.
    exact = [r for r in rows if r[0] == name]
    data = (exact or rows)[0][1]
    if isinstance(data, int):
        row = db.execute('select ZDATA from ZSHORTCUTACTIONS where Z_PK = ?', (data,)).fetchone()
        if row is None:
            return None
        data = row[0]
    if data is None:
        return None
    return plistlib.loads(bytes(data))


def diff(name, mine, theirs):
    problems = []
    if len(mine) != len(theirs):
        problems.append(f'{name}: built {len(mine)} actions, Shortcuts stored {len(theirs)}')
    for i, (a, b) in enumerate(zip(mine, theirs)):
        ia = a['WFWorkflowActionIdentifier']
        ib = b['WFWorkflowActionIdentifier']
        if ia != ib:
            problems.append(f'{name}[{i}]: built {ia}, stored {ib}')
            continue
        pa = a['WFWorkflowActionParameters']
        pb = b['WFWorkflowActionParameters']
        for k in pa:
            if k == 'UUID':
                continue
            if k not in pb:
                problems.append(
                    f'{name}[{i}] {ia}: parameter {k!r} was DROPPED on import — '
                    f'wrong key for this action, the chip is unbound')
        for k in pb:
            if k not in pa and k not in ('UUID', 'CustomOutputName'):
                problems.append(f'{name}[{i}] {ia}: Shortcuts added {k!r} (usually harmless)')
    return problems


def _report_build_ids():
    """Print the build stamp baked into each stored copy.

    Two copies of a shortcut look identical in the library. The stamp is the only
    way to tell, from here or from the finish notification, which one actually ran.
    """
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    import re
    for zname, acts in db.execute(
            "select ZNAME, ZACTIONS from ZSHORTCUT where ZNAME glob 'Photo Curator Export*' "
            "order by ZMODIFICATIONDATE"):
        data = acts
        if isinstance(data, int):
            row = db.execute('select ZDATA from ZSHORTCUTACTIONS where Z_PK = ?', (data,)).fetchone()
            data = row[0] if row else None
        if data is None:
            continue
        blob = str(plistlib.loads(bytes(data)))
        found = set(re.findall(r'build ([0-9a-f]{8})', blob))
        print(f'  {zname!r}: build {", ".join(sorted(found)) or "unstamped (older build)"}')


def main():
    if not os.path.exists(DB):
        print(f'no Shortcuts database at {DB}')
        return 1
    total, missing = [], []
    for name, fn in SHORTCUTS.items():
        mine = fn()[0]
        theirs = stored_actions(name)
        if theirs is None:
            missing.append(name)
            continue
        total += diff(name, mine, theirs)
    for name in missing:
        print(f'not imported yet: {name}')
    _report_build_ids()
    for p in total:
        print(p)
    if not total and not missing:
        print('round trip clean: every parameter survived import')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
