#!/usr/bin/env python3
"""What does the export do when there is nothing left to triage?

    python3 tools/probe_empty_album.py

`_export_body()` reads the album, counts it, then takes `First Item` and asks for its
name to put in the manifest. That is fine for every run this project has ever had,
because `Triage` has never been empty at export time. It can be now: the backlog
accumulates but the intake only reaches back INTAKE_DAYS, so a few days without taking
a photo — or a session that triages everything — leaves the album empty when the
automation fires.

The question is what `Get Item from List → First Item` and `Get Name` do with nothing.
Shortcuts has no error handling, so if either errors the whole run aborts and the
automation produces no folder. That is *safe* — the app refuses a folder with no
manifest — but it is indistinguishable from the automation being broken, which is
exactly the confusion that has cost this project the most time.

So it is measured rather than assumed. `Triage Manual` is a real album that is empty,
which makes it the fixture: read-only, touches no photo, and tells us which of the two
behaviours we get.

Run it from the Shortcuts UI's point of view — it imports and runs on this Mac. It
leaves a probe shortcut behind, which no CLI can delete; `macrun.py --clean` names it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from macrun import probe                                              # noqa: E402
from shortcut_kit import action, album_is, find_photos, uid, var, set_var  # noqa: E402

EMPTY_ALBUM = 'Triage Manual'


def main():
    found, counted = uid(), uid()
    first, firstname = uid(), uid()

    # Stage 1: can we even see the empty album and count it? If this does not come
    # back, the problem is the probe, not the thing being probed.
    setup_count = [
        find_photos(found, [album_is(EMPTY_ALBUM)], sort='Date Taken',
                    order='Oldest First', limit=None),
        set_var('Assets', {'Value': {'OutputName': 'Photos', 'OutputUUID': found,
                                     'Type': 'ActionOutput'},
                           'WFSerializationType': 'WFTextTokenAttachment'}),
        action('is.workflow.actions.count', UUID=counted,
               Input=var('Assets'), WFCountType='Items'),
    ]
    count_token = {'Value': {'OutputName': 'Count', 'OutputUUID': counted,
                             'Type': 'ActionOutput'},
                   'WFSerializationType': 'WFTextTokenAttachment'}

    body, err = probe('Photo Curator Probe EmptyCount',
                      'count=[{}]', count_token, setup=setup_count)
    print(f'stage 1  count of an empty album: {body!r}  err={err!r}')
    if body is None:
        print('  the probe itself did not complete — stop here, stage 2 proves nothing')
        return 1

    # Stage 2: the two actions the export actually uses on that empty list. If this
    # returns nothing, they abort the run; if it returns, we see what they produce.
    setup_first = setup_count + [
        action('is.workflow.actions.getitemfromlist', UUID=first,
               WFInput=var('Assets'), WFItemSpecifier='First Item'),
        action('is.workflow.actions.getitemname', UUID=firstname,
               WFInput={'Value': {'OutputName': 'Item from List', 'OutputUUID': first,
                                  'Type': 'ActionOutput'},
                        'WFSerializationType': 'WFTextTokenAttachment'}),
    ]
    name_token = {'Value': {'OutputName': 'Name', 'OutputUUID': firstname,
                            'Type': 'ActionOutput'},
                  'WFSerializationType': 'WFTextTokenAttachment'}

    body2, err2 = probe('Photo Curator Probe EmptyFirst',
                        'count=[{}] firstname=[{}]', count_token, name_token,
                        setup=setup_first)
    print(f'stage 2  First Item + Get Name on empty: {body2!r}  err={err2!r}')

    print()
    if body2 is None:
        print('VERDICT: First Item / Get Name on an empty album aborts the run.')
        print('  The 18:00 automation will produce no folder at all on a day with')
        print('  nothing to triage, and that is indistinguishable from it being broken.')
        return 2
    print('VERDICT: they survive an empty album and yield an empty name.')
    print('  The export then writes a manifest with count 0, which validateSelection')
    print('  rejects for having no media — a clean refusal, not a dead run.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
