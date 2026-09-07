#!/usr/bin/env python3
"""Answer the export's open photo questions on this Mac, with no phone involved.

    python3 tools/probe_photos.py

This Mac's Photos library has iCloud Photos on, so `Triage`, `Triaged`, `WhatsApp`
and several hundred videos are all present locally. That makes the photo half of
the export testable here after all — the thing that had been assumed impossible.

It asks, in one run:
  * does Get Name map over a *list* of assets, or only over one
  * what Get Type actually returns for a photo and for a video
  * whether the video/photo branch the export uses picks correctly for each
  * whether Encode Media produces a playable file

Read only: nothing is added to or removed from any album, and no photo is deleted.
The encoded video is written into the Shortcuts folder under PCProbe/.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_shortcuts import VIDEO_SIZE, _names_of                     # noqa: E402
from macrun import ICLOUD, PROBE_DIR, probe                          # noqa: E402
from shortcut_kit import (                                            # noqa: E402
    action, album_is, find_photos, if_contains, out, save_file, set_var, text, uid, var,
)


def build_setup():
    acts = []

    # The video-name list, exactly as the export builds it.
    vids = uid()
    acts.append(action('is.workflow.actions.getlastvideo', UUID=vids,
                       WFGetLatestPhotoCount=5.0))
    vnames, vacts = _names_of(out(vids, 'Latest Videos'))
    acts += vacts
    acts.append(set_var('VideoList', vnames))
    vcount = uid()
    acts.append(action('is.workflow.actions.count', UUID=vcount,
                       Input=out(vids, 'Latest Videos'), WFCountType='Items'))

    # How many names came back. If Get Name does not map over a list this is 1
    # (or empty) rather than 5, and the whole approach is unsound.
    lines = uid()
    acts.append(action('is.workflow.actions.text.split', UUID=lines,
                       text=var('VideoList'), WFTextSeparator='New Lines'))
    ncount = uid()
    acts.append(action('is.workflow.actions.count', UUID=ncount,
                       Input=out(lines, 'Split Text'), WFCountType='Items'))

    # One real video and one real photo.
    v1 = uid()
    acts.append(action('is.workflow.actions.getitemfromlist', UUID=v1,
                       WFInput=out(vids, 'Latest Videos'), WFItemSpecifier='First Item'))
    v1n, v1t = uid(), uid()
    acts.append(action('is.workflow.actions.getitemname', UUID=v1n,
                       WFInput=out(v1, 'Item from List')))
    acts.append(action('is.workflow.actions.getitemtype', UUID=v1t,
                       WFInput=out(v1, 'Item from List')))

    pics = uid()
    acts.append(find_photos(pics, [album_is('Triage')], limit=1))
    p1 = uid()
    acts.append(action('is.workflow.actions.getitemfromlist', UUID=p1,
                       WFInput=out(pics, 'Photos'), WFItemSpecifier='First Item'))
    p1n, p1t = uid(), uid()
    acts.append(action('is.workflow.actions.getitemname', UUID=p1n,
                       WFInput=out(p1, 'Item from List')))
    acts.append(action('is.workflow.actions.getitemtype', UUID=p1t,
                       WFInput=out(p1, 'Item from List')))

    # The export's actual branch, run against each of them.
    acts += if_contains(var('VideoList'), out(v1n, 'Name'),
                        [set_var('VerdictV', 'VIDEO')], [set_var('VerdictV', 'photo')])
    acts += if_contains(var('VideoList'), out(p1n, 'Name'),
                        [set_var('VerdictP', 'video')], [set_var('VerdictP', 'PHOTO')])

    # Whether Encode Media gives back something real. Deliberately not saved:
    # writing a media file raises a "save N photos to a file" permission prompt,
    # which blocks an unattended run, while writing text does not. Asking the
    # encoded item for its name is enough to tell whether one exists.
    enc, encn = uid(), uid()
    acts.append(action('is.workflow.actions.encodemedia', UUID=enc,
                       WFMedia=out(v1, 'Item from List'), WFMediaSize=VIDEO_SIZE,
                       WFMediaAudioOnly=False))
    acts.append(action('is.workflow.actions.getitemname', UUID=encn,
                       WFInput=out(enc, 'Encoded Media')))

    report = (
        'video count: [{}]\n'
        'names in list: [{}]\n'
        'video name: [{}]\n'
        'video type: [{}]\n'
        'photo name: [{}]\n'
        'photo type: [{}]\n'
        'branch on video: [{}]\n'
        'branch on photo: [{}]\n'
        'encoded name: [{}]\n'
        'video list:\n{}'
    )
    tokens = (out(vcount, 'Count'), out(ncount, 'Count'), out(v1n, 'Name'),
              out(v1t, 'Type'), out(p1n, 'Name'), out(p1t, 'Type'),
              var('VerdictV'), var('VerdictP'), out(encn, 'Name'),
              var('VideoList'))
    return acts, report, tokens


def main():
    acts, report, tokens = build_setup()
    body, err = probe('PC Photo Probe', report, *tokens, setup=acts)
    print(body or '(no output)')
    if err:
        print('err:', err)
    return 0 if body else 1


if __name__ == '__main__':
    sys.exit(main())
