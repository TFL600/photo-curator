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
    rows = db.execute(
        'select ZACTIONS from ZSHORTCUT where ZNAME = ? '
        'order by ZMODIFICATIONDATE desc', (name,)).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        print(f'note: {len(rows)} shortcuts named {name!r}; checking the newest. '
              f'Confirm only one is on the phone — the app opens them by name.')
    data = rows[0][0]
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
    for p in total:
        print(p)
    if not total and not missing:
        print('round trip clean: every parameter survived import')
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
