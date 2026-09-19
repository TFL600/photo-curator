#!/usr/bin/env python3
"""Static checks on generated Shortcut action lists.

Shortcuts has no error reporting at import time. A wrong parameter key does not
fail: the action imports, its input chip is silently left unset, and the shortcut
runs and does nothing. Six rounds of testing on a phone went into discovering that
once. These checks catch the same class of mistake here instead.

    python3 tools/verify_shortcuts.py     # build everything and check it

What it checks:
  * every action identifier exists in WorkflowKit (tools/action_ids.txt)
  * every action that takes an input actually sets its input key, and sets it to a
    real token rather than a bare string
  * every magic-variable reference points at a UUID defined by an earlier action
  * If / Repeat groups open, branch and close in order and nest properly
  * Repeat Index / Repeat Item are only referenced inside a repeat
  * text token offsets line up with the U+FFFC placeholders in the string
  * no Repeat iterates a library-wide scan, which costs time proportional to the
    photo library rather than to the batch
  * no If anywhere: conditions are stored on import and ignored at runtime, so a
    branch reads like logic and behaves like nothing
  * export and delete resolve the same ordered list of assets
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shortcut_kit import KEY_PROVENANCE, TOKEN                        # noqa: E402

IDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'action_ids.txt')
KNOWN_IDS = set(open(IDS_PATH).read().split())

CONTROL_FLOW = {
    'is.workflow.actions.conditional',
    'is.workflow.actions.repeat.count',
    'is.workflow.actions.repeat.each',
    'is.workflow.actions.choosefrommenu',
}
# Actions that return "the latest N" from the whole photo library. Their cost is
# set by N, not by the batch, so a Repeat over one of them is proportional to the
# library: a 500-video scan looped one asset at a time hung a two-item export for
# minutes. Shortcuts actions map over lists, so read properties off the list in
# one action instead of iterating it.
LIBRARY_SCANS = {
    'is.workflow.actions.getlastvideo',
    'is.workflow.actions.getlastscreenshot',
    'is.workflow.actions.getlastphoto',
    'is.workflow.actions.getlatestlivephotos',
    'is.workflow.actions.getlatestphotoimport',
}

# Actions that legitimately take no input of their own.
NO_INPUT_OK = {
    'is.workflow.actions.date', 'is.workflow.actions.gettext',
    'is.workflow.actions.notification', 'is.workflow.actions.showresult',
    'is.workflow.actions.filter.photos', 'is.workflow.actions.number',
    # Sources its own items from the photo library rather than from the flow.
    'is.workflow.actions.getlastscreenshot', 'is.workflow.actions.getlastvideo',
    # Takes a path, not a file: it is where files come from.
    'is.workflow.actions.documentpicker.open',
}


def _walk(value):
    """Yield every dict nested anywhere inside a parameter value."""
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def check(actions, name):
    problems = []
    seen_uuids = set()
    scan_uuids = {a['WFWorkflowActionParameters']['UUID']: a['WFWorkflowActionIdentifier']
                  for a in actions
                  if a['WFWorkflowActionIdentifier'] in LIBRARY_SCANS
                  and a['WFWorkflowActionParameters'].get('UUID')}
    stack = []            # open control-flow groups
    repeat_depth = 0

    def fail(i, msg):
        ident = actions[i].get('WFWorkflowActionIdentifier', '?')
        problems.append(f'{name}[{i}] {ident}: {msg}')

    for i, act in enumerate(actions):
        ident = act.get('WFWorkflowActionIdentifier')
        params = act.get('WFWorkflowActionParameters', {})

        if ident not in KNOWN_IDS:
            fail(i, 'identifier not present in WorkflowKit')

        # Conditions do not work in generated shortcuts. WFCondition and
        # WFConditionalActionString survive import — the round trip reads them
        # back — and are then ignored when the shortcut runs, so every branch
        # takes the else path. Proven three ways while trying to split videos from
        # photos. A dead branch is worse than no branch, because it reads like
        # protection: the delete shortcut's per-asset fallback sat behind one.
        if ident == 'is.workflow.actions.conditional':
            fail(i, 'uses If, which never fires here — restructure so no condition '
                    'is needed, the way the video pass does')

        # ── magic variables must point backwards at a real action ──
        for d in _walk(params):
            if d.get('Type') == 'ActionOutput':
                ref = d.get('OutputUUID')
                if ref not in seen_uuids:
                    fail(i, f'references output {ref} that no earlier action defines')
            if d.get('Type') == 'Variable' and d.get('VariableName') in ('Repeat Index', 'Repeat Item'):
                if repeat_depth == 0:
                    fail(i, f'uses {d["VariableName"]} outside a repeat')

        # ── token offsets ──
        for d in _walk(params):
            if d.get('WFSerializationType') == 'WFTextTokenString':
                s = d['Value'].get('string', '')
                for key in d['Value'].get('attachmentsByRange', {}):
                    pos = int(key.strip('{}').split(',')[0])
                    if pos >= len(s) or s[pos] != TOKEN:
                        fail(i, f'token offset {pos} does not land on a placeholder in {s!r}')

        # ── repeats must not iterate a library-wide scan ──
        if ident == 'is.workflow.actions.repeat.each' and params.get('WFControlFlowMode') == 0:
            src = params.get('WFInput', {})
            ref = src.get('Value', {}).get('OutputUUID') if isinstance(src, dict) else None
            if ref in scan_uuids:
                fail(i, f'repeats over {scan_uuids[ref]}, whose size is the library '
                        f'rather than the batch — map over the list in one action instead')

        # ── control flow ──
        if ident in CONTROL_FLOW:
            mode = params.get('WFControlFlowMode')
            group = params.get('GroupingIdentifier')
            if group is None:
                fail(i, 'control flow action without a GroupingIdentifier')
            elif mode == 0:
                stack.append(group)
            elif mode == 1:
                if not stack or stack[-1] != group:
                    fail(i, 'Otherwise does not match the innermost open block')
            elif mode == 2:
                if not stack or stack[-1] != group:
                    fail(i, 'End does not close the innermost open block')
                elif stack:
                    stack.pop()
            else:
                fail(i, f'unknown WFControlFlowMode {mode!r}')

            if ident.startswith('is.workflow.actions.repeat'):
                if mode == 0:
                    repeat_depth += 1
                elif mode == 2:
                    repeat_depth = max(0, repeat_depth - 1)

            # Only the opening action of a block carries an input.
            if mode != 0:
                if params.get('UUID'):
                    seen_uuids.add(params['UUID'])
                continue

        # ── input binding ──
        expected = KEY_PROVENANCE.get(ident, (None, None))[0]
        if ident not in KEY_PROVENANCE:
            fail(i, 'no provenance recorded for this action — do not ship a guessed key')
        elif expected is not None:
            if expected not in params:
                fail(i, f'input key {expected!r} missing — the chip would import unbound')
            else:
                v = params[expected]
                if isinstance(v, str):
                    fail(i, f'input key {expected!r} is a bare string; it needs a token')
        elif ident not in NO_INPUT_OK and ident not in CONTROL_FLOW:
            fail(i, 'action takes no input but is not on the no-input list')

        if params.get('UUID'):
            seen_uuids.add(params['UUID'])

    if stack:
        problems.append(f'{name}: {len(stack)} control-flow block(s) never closed')
    return problems


# Albums whose membership order defines an index space. An index emitted against one
# of these is meaningless against any other, so each is checked on its own.
INDEX_ALBUMS = ('Triage', 'Triage Manual')
TRIAGED_ALBUM = 'Triaged'


def _find_photos_signature(actions):
    """Every Find Photos over an index album, reduced to what defines ordering."""
    sigs = []
    for a in actions:
        if a['WFWorkflowActionIdentifier'] != 'is.workflow.actions.filter.photos':
            continue
        p = a['WFWorkflowActionParameters']
        f = p.get('WFContentItemFilter', {}).get('Value', {})
        templates = f.get('WFActionParameterFilterTemplates', [])
        albums = [t['Values']['Enumeration']['Value'] for t in templates
                  if t.get('Property') == 'Album']
        if len(albums) != 1 or albums[0] not in INDEX_ALBUMS:
            continue
        sigs.append((tuple(albums), p.get('WFContentItemSortProperty'),
                     p.get('WFContentItemSortOrder'), p.get('WFContentItemLimitEnabled'),
                     p.get('WFContentItemLimitNumber')))
    return sigs


def _triaged_marking(actions, name):
    """Refuse to mark Triaged from an album-wide scan in a shortcut that deletes.

    This is the shape of the bug that lost a swipe session on 2026-09-19. The delete
    shortcut deleted its targets and then added *everything Find Photos still saw in
    Triage* to Triaged. The two steps agree only when the delete worked, and Delete
    Photos on an accumulated set is atomic: one unmaterialisable asset fails the whole
    batch silently. Nothing deleted, so nothing left the album, so the entire batch
    was marked as triaged and never offered again — with every photo still there.

    "Everything still in the album" is never a safe answer to "what did the user
    keep", because it is also the answer when nothing happened at all. The keep list
    has to come from the app, which is the only thing that knows. So: inside a
    shortcut containing Delete Photos, a Save to Photo Album into Triaged may iterate
    a variable the shortcut built, but never the output of a Find Photos.
    """
    problems = []
    if not any(a['WFWorkflowActionIdentifier'] == 'is.workflow.actions.deletephotos'
               for a in actions):
        return problems
    finds = {a['WFWorkflowActionParameters'].get('UUID')
             for a in actions
             if a['WFWorkflowActionIdentifier'] == 'is.workflow.actions.filter.photos'}
    scan = None
    for a in actions:
        ident = a['WFWorkflowActionIdentifier']
        p = a['WFWorkflowActionParameters']
        if ident == 'is.workflow.actions.repeat.each':
            if p.get('WFControlFlowMode') == 0:
                ref = p.get('WFInput', {})
                ref = ref.get('Value', {}).get('OutputUUID') if isinstance(ref, dict) else None
                scan = ref if ref in finds else None
            else:
                scan = None
        elif (ident == 'is.workflow.actions.savetocameraroll'
              and p.get('WFCameraRollSelectedGroup') == TRIAGED_ALBUM and scan):
            problems.append(
                f'{name}: marks {TRIAGED_ALBUM} from a Find Photos result inside a '
                f'shortcut that deletes. If the delete silently fails, that marks the '
                f'whole batch as triaged and it is never offered again. Iterate the '
                f'keep list the app sent instead.')
    return problems


def _resolve_before_delete(actions, name):
    """Positions must be turned into assets before anything is deleted.

    Deleting shifts every position after the first target by one, so an index
    resolved afterwards names a different photo — and names it without any error, the
    same class of silent wrongness as a divergent lookup. The keep list in particular
    is resolved after the targets and is easy to drift below the delete during an
    edit, which is why it is checked rather than just commented.
    """
    idents = [a['WFWorkflowActionIdentifier'] for a in actions]
    if 'is.workflow.actions.deletephotos' not in idents:
        return []
    cut = idents.index('is.workflow.actions.deletephotos')
    for i, a in enumerate(actions[cut + 1:], start=cut + 1):
        if (a['WFWorkflowActionIdentifier'] == 'is.workflow.actions.getitemfromlist'
                and a['WFWorkflowActionParameters'].get('WFItemSpecifier') == 'Item At Index'):
            return [f'{name}: action {i} resolves a position after Delete Photos has '
                    f'run. Deleting shifts every later position, so this names a '
                    f'different asset than the app counted — resolve every index '
                    f'before deleting anything.']
    return []


def verify_all(built):
    problems = []
    for name, actions in built.items():
        problems += check(actions, name)
        problems += _triaged_marking(actions, name)
        problems += _resolve_before_delete(actions, name)

    # The identity contract: whatever resolves positions must resolve them the same
    # way everywhere. A divergence here is undetectable at runtime and deletes the
    # wrong photos, so it is checked separately and loudly.
    # Per album: two albums are two index spaces, and it is only a divergence *within*
    # one album that makes an index resolve to a different asset in two shortcuts.
    by_album = {}
    for name, actions in built.items():
        for s in _find_photos_signature(actions):
            by_album.setdefault(s[0][0], {}).setdefault(s, []).append(name)
    for album, sigs in sorted(by_album.items()):
        if len(sigs) > 1:
            problems.append(f'{album} lookups disagree on ordering, so indices would '
                            'resolve differently: ' +
                            '; '.join(f'{s} used by {sorted(set(n))}'
                                      for s, n in sigs.items()))
            continue
        (s,) = sigs
        if s[1:] != ('Date Taken', 'Oldest First', False, None):
            problems.append(
                f'{album} lookup is not Date Taken / Oldest First / no limit: {s}')

    return problems


if __name__ == '__main__':
    from build_shortcuts import SHORTCUTS
    built = {}
    for n, fn in SHORTCUTS.items():
        acts, _ = fn()
        built[n] = acts
    probs = verify_all(built)
    for p in probs:
        print(p)
    print(f'\n{len(probs)} problem(s) across {len(built)} shortcut(s), '
          f'{sum(len(a) for a in built.values())} actions')
    sys.exit(1 if probs else 0)
