#!/usr/bin/env python3
"""What did Photo Curator Delete actually resolve? Run on the PHONE.

    python3 tools/probe_delete_resolve.py <input string>   # or --file batch.txt

On 2026-10-31 a batch of 213 deletes / 80 keeps out of 293 raised "Allow Photo
Curator Delete to delete 3,240 photos?", and the first two tiles in that dialog were
Triage #12 and #14 — both keeps. The app's string was correct; the live shortcut was
identical to the build; replaying the same index logic over a text list on this Mac
gave exactly 213 and 80. So the fault is in how the phone resolves *photos*, and only
the phone can show it.

This is build_delete() verbatim up to, and not including, Delete Photos — nothing is
deleted and no album is touched — with the shortcut input replaced by a literal
string. It writes counts and the names of everything it resolved to
`Shortcuts/PCProbe/diag-delete.txt` in iCloud Drive, which syncs here; names are
asset UUIDs, so each line maps back to a Triage index with the Photos database.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_shortcuts import build_delete, _names_of                   # noqa: E402
from macrun import BUILD_DIR, PROBE_DIR                                # noqa: E402
from shortcut_kit import action, out, save_file, text, uid, var, write_shortcut  # noqa: E402

NAME = 'Photo Curator Probe Resolve Delete'


def build(input_string):
    acts, _ = build_delete()
    cut = next(i for i, a in enumerate(acts)
               if a['WFWorkflowActionIdentifier'] == 'is.workflow.actions.deletephotos')
    acts = acts[:cut]

    # The first action splits the shortcut input; feed it a literal instead.
    lit = uid()
    acts[0]['WFWorkflowActionParameters']['text'] = out(lit, 'Text')
    acts.insert(0, action('is.workflow.actions.gettext', UUID=lit,
                          WFTextActionText=input_string))

    counts = {}
    for k in ('Parts', 'DeleteIndices', 'KeepIndices', 'Assets', 'Targets', 'Keepers'):
        counts[k] = uid()
        acts.append(action('is.workflow.actions.count', UUID=counts[k],
                           Input=var(k), WFCountType='Items'))
    names = {}
    for k in ('Assets', 'Targets', 'Keepers'):
        names[k], more = _names_of(var(k))
        acts += more

    keys = list(counts)
    template = ' '.join(f'{k}=[{{}}]' for k in keys) + \
        '\n== Assets\n{}\n== Targets\n{}\n== Keepers\n{}\n'
    report = uid()
    acts.append(action('is.workflow.actions.gettext', UUID=report, WFTextActionText=text(
        template, *(out(counts[k], 'Count') for k in keys),
        names['Assets'], names['Targets'], names['Keepers'])))
    acts += save_file('diag-delete.txt', f'/{PROBE_DIR}/diag-delete.txt',
                      out(report, 'Text'))
    return acts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', nargs='?')
    ap.add_argument('--file')
    ap.add_argument('--out', default=os.path.expanduser('~/Downloads'))
    args = ap.parse_args()
    s = open(args.file).read().strip() if args.file else args.input
    if not s or '|' not in s:
        raise SystemExit('need "<delete>|<keep>"')

    os.makedirs(BUILD_DIR, exist_ok=True)
    raw = os.path.join(BUILD_DIR, NAME.replace(' ', '_') + '.plist.shortcut')
    signed = os.path.join(args.out, NAME + '.shortcut')
    write_shortcut(raw, build(s), types=[])
    r = subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', raw, '-o', signed],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sign failed: {r.stderr.strip()}')
    print(f'signed -> {signed}')


if __name__ == '__main__':
    sys.exit(main())
