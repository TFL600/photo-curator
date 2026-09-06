#!/usr/bin/env python3
"""A read-only diagnostic Shortcut that answers several serialization questions at once.

    python3 tools/build_probe.py

Shortcuts cannot be run headlessly from here and photo actions behave differently on
the Mac, so some questions can only be answered by one run on the phone. Each such
run costs an import, a tap and a screenshot, so this asks *everything currently
unknown* in a single run rather than one question per round trip.

It touches nothing: no albums are changed, no files written, no photos deleted. It
finds the first photo in Triage, reads properties off it, and shows the results.

What it settles:
  1/2  which action actually produces the current date — `date` with
       WFDateActionMode, or the separate `currentdate` action
  3/4  whether format.date's WFDateFormatStyle/WFDateFormat pair does anything,
       fed from each of those two candidates
  5    what Get Name returns for a photo — specifically whether it carries the
       original extension, which both the video branch and the category sidecars
       rely on
  6    what Get Name returns for a video, i.e. whether ".MOV" is really in it
  7    whether Combine Text joins a list variable with newlines
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shortcut_kit import (                                            # noqa: E402
    action, album_is, append_var, find_photos, out, repeat_each, text, uid, var,
    write_shortcut,
)

TRIAGE_ALBUM = 'Triage'
BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build')


def build():
    acts = []

    # 1. is.workflow.actions.date, the action the export currently uses.
    d1 = uid()
    acts.append(action('is.workflow.actions.date', UUID=d1, WFDateActionMode='Current Date'))

    # 2. is.workflow.actions.currentdate, a separate identifier that also exists.
    d2 = uid()
    acts.append(action('is.workflow.actions.currentdate', UUID=d2))

    # 3/4. Format Date over each candidate.
    f1, f2 = uid(), uid()
    acts.append(action('is.workflow.actions.format.date', UUID=f1, WFDate=out(d1, 'Date'),
                       WFDateFormatStyle='Custom', WFDateFormat='yyyy-MM-dd-HHmm'))
    acts.append(action('is.workflow.actions.format.date', UUID=f2,
                       WFDate=out(d2, 'Current Date'),
                       WFDateFormatStyle='Custom', WFDateFormat='yyyy-MM-dd-HHmm'))

    # 5. The name of the first photo in Triage. The export builds every filename out
    #    of this, and the sidecars match on it.
    photos = uid()
    acts.append(find_photos(photos, [album_is(TRIAGE_ALBUM)], limit=1))
    first = uid()
    acts.append(action('is.workflow.actions.getitemfromlist', UUID=first,
                       WFInput=out(photos, 'Photos'), WFItemSpecifier='First Item'))
    n1 = uid()
    acts.append(action('is.workflow.actions.getitemname', UUID=n1,
                       WFInput=out(first, 'Item from List')))

    # 6. The same for the most recent video, to see whether ".MOV" is in the name.
    vids = uid()
    acts.append(action('is.workflow.actions.getlastvideo', UUID=vids,
                       WFGetLatestPhotoCount=1))
    n2 = uid()
    acts.append(action('is.workflow.actions.getitemname', UUID=n2, WFInput=out(vids, 'Latest Videos')))

    # 7. Combine Text over a list variable, which is how the sidecars are built.
    acts += repeat_each(out(photos, 'Photos'), [append_var('Bag', var('Repeat Item'))])
    joined = uid()
    acts.append(action('is.workflow.actions.text.combine', UUID=joined,
                       text=var('Bag'), WFTextSeparator='New Lines'))

    acts.append(action('is.workflow.actions.showresult', Text=text(
        '1 date: [{}]\n'
        '2 currentdate: [{}]\n'
        '3 format(date): [{}]\n'
        '4 format(currentdate): [{}]\n'
        '5 photo name: [{}]\n'
        '6 video name: [{}]\n'
        '7 combined: [{}]',
        out(d1, 'Date'), out(d2, 'Current Date'), out(f1, 'Formatted Date'),
        out(f2, 'Formatted Date'), out(n1, 'Name'), out(n2, 'Name'),
        out(joined, 'Combined Text'))))
    return acts


if __name__ == '__main__':
    os.makedirs(BUILD_DIR, exist_ok=True)
    acts = build()
    raw = os.path.join(BUILD_DIR, 'Photo_Curator_Probe.plist.shortcut')
    write_shortcut(raw, acts, types=[])

    from verify_shortcuts import check
    # Structural checks only. The probe deliberately exercises actions with no
    # recorded provenance — that is the point of it — and it reads a single photo
    # rather than the full ordered list, so the identity contract does not apply.
    problems = [p for p in check(acts, 'Photo Curator Probe')
                if 'provenance' not in p and 'no-input list' not in p]
    for p in problems:
        print(p)
    if problems:
        sys.exit(1)

    signed = os.path.join(BUILD_DIR, 'Photo Curator Probe.shortcut')
    r = subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', raw, '-o', signed],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print('sign failed:', r.stderr.strip())
        sys.exit(1)
    dest = os.path.expanduser('~/Downloads/Photo Curator Probe.shortcut')
    __import__('shutil').copy(signed, dest)
    print(f'{len(acts)} actions, structural checks passed -> {dest}')
