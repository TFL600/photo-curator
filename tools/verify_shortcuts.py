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
# Actions that legitimately take no input of their own.
NO_INPUT_OK = {
    'is.workflow.actions.date', 'is.workflow.actions.gettext',
    'is.workflow.actions.notification', 'is.workflow.actions.showresult',
    'is.workflow.actions.filter.photos', 'is.workflow.actions.number',
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


def _find_photos_signature(actions):
    """Every Find Photos over the Triage album, reduced to what defines ordering."""
    sigs = []
    for a in actions:
        if a['WFWorkflowActionIdentifier'] != 'is.workflow.actions.filter.photos':
            continue
        p = a['WFWorkflowActionParameters']
        f = p.get('WFContentItemFilter', {}).get('Value', {})
        templates = f.get('WFActionParameterFilterTemplates', [])
        albums = [t['Values']['Enumeration']['Value'] for t in templates
                  if t.get('Property') == 'Album']
        if albums != ['Triage']:
            continue
        sigs.append((tuple(albums), p.get('WFContentItemSortProperty'),
                     p.get('WFContentItemSortOrder'), p.get('WFContentItemLimitEnabled'),
                     p.get('WFContentItemLimitNumber')))
    return sigs


def verify_all(built):
    problems = []
    for name, actions in built.items():
        problems += check(actions, name)

    # The identity contract: whatever resolves positions must resolve them the same
    # way everywhere. A divergence here is undetectable at runtime and deletes the
    # wrong photos, so it is checked separately and loudly.
    sigs = {}
    for name, actions in built.items():
        for s in _find_photos_signature(actions):
            sigs.setdefault(s, []).append(name)
    if len(sigs) > 1:
        problems.append('Triage lookups disagree on ordering, so indices would '
                        'resolve differently: ' +
                        '; '.join(f'{s} used by {sorted(set(n))}' for s, n in sigs.items()))
    elif len(sigs) == 1:
        (s,) = sigs
        if s[1:] != ('Date Taken', 'Oldest First', False, None):
            problems.append(f'Triage lookup is not Date Taken / Oldest First / no limit: {s}')

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
