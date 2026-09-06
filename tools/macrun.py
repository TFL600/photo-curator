#!/usr/bin/env python3
"""Build a Shortcut, import it on this Mac, run it, and return its output.

    python3 tools/macrun.py --selftest

This is the loop that removes the phone from the inner cycle. Shortcuts has no
import CLI, but `open`ing a signed .shortcut raises an import sheet that can be
driven with System Events, and `shortcuts run -o` returns a shortcut's output as
text. So a question about serialization — does this parameter key bind, what does
this action actually return — can be asked and answered here in seconds.

What it cannot answer: anything that depends on the phone's photo library, or on
iOS-only behaviour. Photo actions on macOS run against the Mac's Photos library,
which is not the same library and may be empty. Use it for date, text, number,
file and control-flow questions; keep photo questions for the phone.

Requires Terminal (or whichever app runs this) to have Accessibility permission,
because driving the import sheet means synthesising a keystroke.
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shortcut_kit import action, save_file, text, uid, write_shortcut    # noqa: E402

BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build')
# Where Save File lands when WFAskWhereToSave is off. On this Mac that is a real
# local directory, so a probe can hand its answer back simply by writing a file.
ICLOUD = os.path.expanduser(
    '~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents')
PROBE_DIR = 'PCProbe'


def sign(actions, name):
    os.makedirs(BUILD_DIR, exist_ok=True)
    # shortcuts sign refuses an input that is not named .shortcut.
    raw = os.path.join(BUILD_DIR, name.replace(' ', '_') + '.plist.shortcut')
    signed = os.path.join(BUILD_DIR, name + '.shortcut')
    write_shortcut(raw, actions, types=[])
    r = subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', raw, '-o', signed],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'sign failed: {r.stderr.strip()}')
    return signed


def installed(name):
    r = subprocess.run(['shortcuts', 'list'], capture_output=True, text=True)
    return name in r.stdout.splitlines()


def do_import(path, name, timeout=30):
    """Open the file and click through whatever Shortcuts puts up.

    The sheet's buttons expose no accessibility names — every one of them reads as
    `missing value` — so they cannot be clicked by title. They are all default
    buttons though, so Return activates them: Return on the import sheet is
    "Add Shortcut", and Return on the name-collision dialog is "Replace", which is
    exactly the answer wanted. Two presses covers both, and a press with no dialog
    up is harmless.
    """
    subprocess.run(['open', '-a', 'Shortcuts', path], check=True)
    deadline = time.time() + timeout
    presses = 0
    while time.time() < deadline:
        time.sleep(1.2)
        subprocess.run(['osascript',
                        '-e', 'tell application "Shortcuts" to activate',
                        '-e', 'delay 0.3',
                        '-e', 'tell application "System Events" to keystroke return'],
                       capture_output=True, text=True)
        presses += 1
        time.sleep(1.0)
        if installed(name):
            # The name can take a moment to become resolvable by `shortcuts run`
            # even once it is listed.
            time.sleep(1.5)
            return True, f'{presses} press(es)'
    return installed(name), f'{presses} press(es), timed out'


def run(name, outfile, timeout=120):
    """Run the shortcut and read the file it wrote.

    Not `shortcuts run -o`: that returns success and writes nothing, and adding
    --output-type makes it hang indefinitely. Having the shortcut save a file is
    the channel that actually works, and it exercises Save File at the same time.
    """
    landing = os.path.join(ICLOUD, PROBE_DIR, outfile)
    if os.path.exists(landing):
        os.remove(landing)
    try:
        r = subprocess.run(['shortcuts', 'run', name], capture_output=True,
                           text=True, timeout=timeout)
        err = (r.stderr or '').strip()
    except subprocess.TimeoutExpired:
        err = f'shortcuts run did not return within {timeout}s'
    deadline = time.time() + 10
    while time.time() < deadline and not os.path.exists(landing):
        time.sleep(0.3)
    body = open(landing).read() if os.path.exists(landing) else ''
    return body, err


def probe(name, report_template, *tokens, setup=(), reimport=True):
    """Build, import and run a shortcut that writes `report_template` to a file.

    The name gets a unique suffix. Importing over an existing name raises a
    replace/keep-both dialog and leaves the library in a state where `shortcuts
    run` can briefly not resolve the name at all; a fresh name every time avoids
    the whole question. Probes are disposable, so the litter is acceptable —
    `--clean` removes them.
    """
    name = f'{name} {int(time.time()) % 100000}'
    outfile = name.replace(' ', '_') + '.txt'
    acts = list(setup)
    said = uid()
    acts.append(action('is.workflow.actions.gettext', UUID=said,
                       WFTextActionText=text(report_template, *tokens)))
    acts += save_file(outfile, f'/{PROBE_DIR}/{outfile}', out_text(said))
    path = sign(acts, name)
    if reimport or not installed(name):
        ok, note = do_import(path, name)
        if not ok:
            return None, f'import did not complete ({note})'
    return run(name, outfile)


def out_text(u):
    return {'Value': {'OutputName': 'Text', 'OutputUUID': u, 'Type': 'ActionOutput'},
            'WFSerializationType': 'WFTextTokenAttachment'}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true',
                    help='prove the build/import/run loop works end to end')
    args = ap.parse_args()

    if args.selftest:
        name = 'PC Loop Selftest 2'
        body, err = probe(name, 'loop works')
        print(f'output={body!r} err={err!r}')
        sys.exit(0 if (body or '').strip() == 'loop works' else 1)
    ap.print_help()
