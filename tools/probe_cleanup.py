#!/usr/bin/env python3
"""Prove, on this Mac, the two things the dated-folder export depends on.

    python3 tools/probe_cleanup.py

1. A folder can be reached by *path* with no picker and no security-scoped
   bookmark — Get File with WFShowFilePicker off — and Delete Files removes it.
   That is what lets an export clean up after itself. (Get Contents of Folder
   genuinely does need the bookmark: handed a Get File folder it hangs forever.)
2. A folder can be named after the date without Format Date, which returns an
   empty string, and without Replace Text, which returned empty under every input
   key tried. Split Text on " at " does the job.

Run from the Shortcuts UI, not `shortcuts run`: under the CLI the delete hangs
with no dialog and no error. That is a limitation of the headless runner.

A caveat this probe ran into and could not pin down, which matters more on the
phone than here: a freshly imported shortcut that deletes files sometimes does
nothing at all and never finishes, which looks exactly like waiting on an
unanswered "allow this shortcut to delete files" grant. Run the real export by
hand once, with the phone in front of you, and answer whatever it asks before
trusting the automation with it.

Fixture lives in PCProbe/ and PCProbeExport/ inside the Shortcuts iCloud folder
and is created and destroyed here. Nothing outside those two paths is touched.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macrun                                                         # noqa: E402
from shortcut_kit import (                                            # noqa: E402
    action, out, repeat_each, save_file, set_var, text, uid, var)

ROOT = '/PCProbeExport'
NAME = 'Photo Curator Probe Folders'
REPORT = 'probe-cleanup.txt'


def build():
    acts = []
    old = uid()
    acts.append(action('is.workflow.actions.documentpicker.open', UUID=old,
                       WFGetFilePath=ROOT, WFShowFilePicker=False,
                       WFFileErrorIfNotFound=False))
    acts += repeat_each(out(old, 'File'), [
        action('is.workflow.actions.file.delete', UUID=uid(),
               WFInput=var('Repeat Item'), WFDeleteImmediatelyDelete=True)])

    d, txt = uid(), uid()
    acts.append(action('is.workflow.actions.date', UUID=d, WFDateActionMode='Current Date'))
    acts.append(action('is.workflow.actions.gettext', UUID=txt,
                       WFTextActionText=text('{}', out(d, 'Date'))))
    part = out(txt, 'Text')
    for sep in (' at ', ':'):
        sp, it = uid(), uid()
        acts.append(action('is.workflow.actions.text.split', UUID=sp, text=part,
                           WFTextSeparator='Custom', WFTextCustomSeparator=sep))
        acts.append(action('is.workflow.actions.getitemfromlist', UUID=it,
                           WFInput=out(sp, 'Split Text'), WFItemSpecifier='First Item'))
        part = out(it, 'Item from List')
    stamp = uid()
    acts.append(action('is.workflow.actions.gettext', UUID=stamp,
                       WFTextActionText=text('{} (7)', part)))
    acts.append(set_var('Stamp', out(stamp, 'Text')))

    body = uid()
    acts.append(action('is.workflow.actions.gettext', UUID=body,
                       WFTextActionText=text('folder={}', var('Stamp'))))
    acts += save_file('manifest.json', text(ROOT + '/{}/manifest.json', var('Stamp')),
                      out(body, 'Text'))
    acts += save_file(REPORT, f'/{macrun.PROBE_DIR}/{REPORT}', out(body, 'Text'))
    return acts


def main():
    root = os.path.join(macrun.ICLOUD, ROOT.lstrip('/'))
    report = os.path.join(macrun.ICLOUD, macrun.PROBE_DIR, REPORT)
    stale = os.path.join(root, 'stale-folder-from-a-previous-export')
    os.makedirs(stale, exist_ok=True)
    open(os.path.join(stale, 'junk.txt'), 'w').write('should not survive\n')
    if os.path.exists(report):
        os.remove(report)

    macrun.do_import(macrun.sign(build(), NAME), NAME)
    subprocess.run(['open', 'shortcuts://run-shortcut?name=' + NAME.replace(' ', '%20')])
    for _ in range(60):
        if os.path.exists(report):
            break
        time.sleep(1)
    if not os.path.exists(report):
        print('no output — did the Shortcuts window come forward?')
        return 1

    left = sorted(os.listdir(root)) if os.path.isdir(root) else []
    print(open(report).read().strip())
    print('folders left behind:', left)
    ok = os.path.basename(stale) not in left and len(left) == 1
    print('cleanup + dated folder:', 'OK' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
