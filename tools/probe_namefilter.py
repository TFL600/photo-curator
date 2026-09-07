#!/usr/bin/env python3
"""Find the serialization that actually makes a Name filter bind.

    python3 tools/probe_namefilter.py

`Find Photos where Name is X` returned the whole library on the phone: 40 names
against a per-name cap of 3 produced exactly 120 matches, which is the cap times
the names — the signature of a filter value that never bound. A filter that fails
to bind does not error, it just stops filtering, and Delete Photos downstream
makes that the most dangerous failure in the project.

So: take one asset whose name is known at runtime, try each candidate shape
against it, and count what comes back. The shape that works reports 1 or 2 (a
Live Photo pair); every broken shape reports the cap.

Runs against this Mac's Photos library, which has the same albums synced. Read
only — no deletions, nothing added to or removed from an album.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from macrun import probe                                             # noqa: E402
from shortcut_kit import (                                            # noqa: E402
    action, album_is, find_photos, out, uid, var,
)

# High enough that a non-binding filter is unmistakable, low enough to stay cheap.
CAP = 25.0


def candidates(name_token):
    """Every plausible shape for the value of a text filter, and its label."""
    return [
        ('String: token',
         'Name', {'String': name_token}),
        ('bare token',
         'Name', name_token),
        ('Enumeration/WFStringSubstitutableState',
         'Name', {'Enumeration': {'Value': name_token,
                                  'WFSerializationType': 'WFStringSubstitutableState'}}),
        ('String: WFStringSubstitutableState',
         'Name', {'String': {'Value': name_token,
                             'WFSerializationType': 'WFStringSubstitutableState'}}),
        ('Text: token',
         'Name', {'Text': name_token}),
        ('String: token, Property "File Name"',
         'File Name', {'String': name_token}),
        ('String: token, Property "Filename"',
         'Filename', {'String': name_token}),
    ]


def build_setup(label, prop, values_of):
    """One candidate per run.

    Tried as one shortcut with all seven at first, and a single bad shape errored
    the whole run — "There was a problem running the action" — losing the answer
    for the six that might have been fine. One per run costs a few seconds each
    and cannot lose information.
    """
    acts = []
    pics = uid()
    acts.append(find_photos(pics, [album_is('Triage')], limit=1))
    one = uid()
    acts.append(action('is.workflow.actions.getitemfromlist', UUID=one,
                       WFInput=out(pics, 'Photos'), WFItemSpecifier='First Item'))
    nm = uid()
    acts.append(action('is.workflow.actions.getitemname', UUID=nm,
                       WFInput=out(one, 'Item from List')))
    acts.append(action('is.workflow.actions.setvariable', WFVariableName='TheName',
                       WFInput=out(nm, 'Name')))

    f = uid()
    acts.append(find_photos(
        f, [{'Operator': 4, 'Property': prop, 'Removable': True,
             'Values': values_of(var('TheName'))}],
        limit=CAP))
    c = uid()
    acts.append(action('is.workflow.actions.count', UUID=c,
                       Input=out(f, 'Photos'), WFCountType='Items'))
    return acts, 'name=[{}] matched=[{}]', (out(nm, 'Name'), out(c, 'Count'))


SHAPES = [
    ('String: token', 'Name', lambda t: {'String': t}),
    ('bare token', 'Name', lambda t: t),
    ('Enumeration/WFStringSubstitutableState', 'Name',
     lambda t: {'Enumeration': {'Value': t,
                                'WFSerializationType': 'WFStringSubstitutableState'}}),
    ('String: WFStringSubstitutableState', 'Name',
     lambda t: {'String': {'Value': t, 'WFSerializationType': 'WFStringSubstitutableState'}}),
    ('Text: token', 'Name', lambda t: {'Text': t}),
    ('String: token, Property "File Name"', 'File Name', lambda t: {'String': t}),
    ('String: token, Property "Filename"', 'Filename', lambda t: {'String': t}),
]


def main():
    print(f'a working shape reports 1 or 2; a broken one reports {int(CAP)}\n')
    for label, prop, values_of in SHAPES:
        acts, report, tokens = build_setup(label, prop, values_of)
        body, err = probe('PC Name Filter Probe', report, *tokens, setup=acts)
        line = (body or '').strip().replace('\n', ' ')
        print(f'{label:42s} -> {line or "(no output)"}{"  err=" + err if err else ""}',
              flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
