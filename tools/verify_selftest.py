#!/usr/bin/env python3
"""Prove the verifier still detects each failure mode it claims to detect.

    python3 tools/verify_selftest.py

CLAUDE.md has said for a while that the verifier is mutation-tested — that breaking
each known failure mode makes it fail. That was true when it was written and was done
by hand, which means nothing re-checked it afterwards. A checker nobody checks drifts
into agreeing with whatever the code happens to do: `check_albums.py` had quietly
stopped filtering deleted albums and was reporting three `Triage` albums that Photos
did not have, which cost a real investigation on 2026-09-19.

So the mutations are code now. Each one takes the real generated shortcuts, breaks one
specific thing, and asserts the verifier objects. A mutation that slips through is a
hole in the verifier, and this exits non-zero when it finds one.
"""

import copy
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_shortcuts as B
import verify_shortcuts as V
from shortcut_kit import uid, out, var


def built():
    """The real thing, freshly generated."""
    return {name: fn()[0] for name, fn in B.SHORTCUTS.items()}


def find_action(acts, ident, nth=0):
    hits = [i for i, a in enumerate(acts) if a['WFWorkflowActionIdentifier'] == ident]
    return hits[nth]


# ── The mutations ───────────────────────────────────────────
# Each returns a mutated copy of the whole shortcut set.

def m_wrong_input_key(all_acts):
    """The failure that costs the most time: a key that is wrong for its action.

    It imports without complaint and leaves the input chip unbound, so the action
    silently operates on nothing. Six rounds went into this on 2026-08-31.
    """
    acts = all_acts['Photo Curator Delete']
    i = find_action(acts, 'is.workflow.actions.deletephotos')
    acts[i]['WFWorkflowActionParameters']['WFInput'] = \
        acts[i]['WFWorkflowActionParameters'].pop('photos')
    return all_acts


def m_dangling_magic_variable(all_acts):
    """A magic variable pointing at an action that does not exist."""
    acts = all_acts['Photo Curator Delete']
    i = find_action(acts, 'is.workflow.actions.setvariable')
    acts[i]['WFWorkflowActionParameters']['WFInput'] = out(uid(), 'Split Text')
    return all_acts


def m_unbalanced_control_flow(all_acts):
    """A repeat that opens and never closes."""
    acts = all_acts['Photo Curator Delete']
    i = find_action(acts, 'is.workflow.actions.repeat.each')
    del acts[find_action(acts, 'is.workflow.actions.repeat.each', 1)]
    return all_acts


def m_divergent_lookup(all_acts):
    """Two shortcuts resolving the same album in different orders.

    Nothing at runtime can notice this: the export enumerates one order, the delete
    another, and index 7 is a different photo on each side.
    """
    acts = all_acts['Photo Curator Delete']
    i = find_action(acts, 'is.workflow.actions.filter.photos')
    acts[i]['WFWorkflowActionParameters']['WFContentItemSortOrder'] = 'Latest First'
    return all_acts


def m_no_provenance(all_acts):
    """An action nobody has ever seen work, shipped on a guess."""
    acts = all_acts['Photo Curator Delete']
    acts.insert(0, {'WFWorkflowActionIdentifier': 'is.workflow.actions.madeup',
                    'WFWorkflowActionParameters': {'UUID': uid()}})
    return all_acts


def m_library_wide_repeat(all_acts):
    """A repeat whose list is a library-wide scan rather than the batch."""
    acts = all_acts['Photo Curator Export']
    scan = uid()
    acts.insert(0, {'WFWorkflowActionIdentifier': 'is.workflow.actions.getlastvideo',
                    'WFWorkflowActionParameters': {'UUID': scan,
                                                   'WFGetLatestPhotoCount': 500}})
    acts[1:1] = B.repeat_each(out(scan, 'Latest Videos'), [
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.getitemname',
         'WFWorkflowActionParameters': {'UUID': uid(), 'WFInput': var('Repeat Item')}}])
    return all_acts


def m_triaged_from_a_scan(all_acts):
    """The bug that lost a swipe session on 2026-09-19.

    Mark Triaged from "whatever Find Photos still sees in the album" instead of from
    the keep list the app sent. Identical behaviour when the delete works; marks the
    entire batch as triaged, permanently, when it silently does not.
    """
    acts = all_acts['Photo Curator Delete']
    i = find_action(acts, 'is.workflow.actions.filter.photos')
    find_uuid = acts[i]['WFWorkflowActionParameters']['UUID']
    acts += B.add_each_to_album(out(find_uuid, 'Photos'), B.TRIAGED_ALBUM)
    return all_acts


def m_keeps_resolved_after_delete(all_acts):
    """Resolve the keep list after deleting, when every later position has shifted.

    The keep repeat sits directly above Delete Photos and is one drag away from
    sitting below it, at which point every keeper past the first deleted position is
    the wrong photo — and is marked as triaged under someone else's name.
    """
    acts = all_acts['Photo Curator Delete']
    d = find_action(acts, 'is.workflow.actions.deletephotos')
    # The keep loop is the repeat block immediately before the delete.
    ends = [i for i, a in enumerate(acts[:d])
            if a['WFWorkflowActionIdentifier'] == 'is.workflow.actions.repeat.each'
            and a['WFWorkflowActionParameters'].get('WFControlFlowMode') == 2]
    end = ends[-1]
    group = acts[end]['WFWorkflowActionParameters']['GroupingIdentifier']
    start = next(i for i, a in enumerate(acts)
                 if a['WFWorkflowActionParameters'].get('GroupingIdentifier') == group
                 and a['WFWorkflowActionParameters'].get('WFControlFlowMode') == 0)
    block = acts[start:end + 1]
    del acts[start:end + 1]
    at = find_action(acts, 'is.workflow.actions.deletephotos')
    acts[at + 1:at + 1] = block
    return all_acts


MUTATIONS = [
    ('wrong input key for the action', m_wrong_input_key),
    ('magic variable pointing nowhere', m_dangling_magic_variable),
    ('repeat opened and never closed', m_unbalanced_control_flow),
    ('two shortcuts ordering one album differently', m_divergent_lookup),
    ('action with no recorded provenance', m_no_provenance),
    ('repeat over a library-wide scan', m_library_wide_repeat),
    ('Triaged marked from a scan, not from the keep list', m_triaged_from_a_scan),
    ('a position resolved after the delete shifted it', m_keeps_resolved_after_delete),
]


def main():
    # The unmutated set must be clean, or nothing below means anything.
    base = V.verify_all(built())
    if base:
        print('the real shortcuts do not verify, so the mutations prove nothing:')
        for p in base:
            print('  ' + p)
        return 1

    holes = []
    for label, mutate in MUTATIONS:
        problems = V.verify_all(mutate(copy.deepcopy(built())))
        status = 'caught ' if problems else 'MISSED '
        if not problems:
            holes.append(label)
        print(f'{status} {label}')
        if problems and os.environ.get('PC_VERBOSE'):
            for p in problems:
                print(f'          {p}')

    print()
    if holes:
        print(f'{len(holes)} mutation(s) the verifier does not detect:')
        for h in holes:
            print('  ' + h)
        return 1
    print(f'ok  all {len(MUTATIONS)} mutations detected')
    return 0


if __name__ == '__main__':
    sys.exit(main())
