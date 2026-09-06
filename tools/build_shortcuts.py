#!/usr/bin/env python3
"""Generate the Photo Curator Shortcuts.

    python3 tools/build_shortcuts.py            # build, verify, sign into ~/Downloads
    python3 tools/build_shortcuts.py --no-sign  # build + verify only

Four shortcuts, and the contract between them:

  Photo Curator Export      rebuilds the Triage album from the last N days minus
                            anything already triaged, then writes one file per
                            asset into a fresh dated folder plus manifest.json.
  Delete Photos By Index    takes "3,7,12", deletes those positions, then marks
                            everything that survived as triaged.
  Add Photos To Album By Index   the app's ★ pile.
  Quick Delete By Name      the manual-pick fallback: matches by filename, so it
                            shows you everything it matched before deleting.

Export and Delete MUST resolve the same ordered list. Both run Find Photos over
album Triage sorted by Date Taken, Oldest First, with no limit. That single line
is the whole identity model — if the two ever diverge, the indices point at
different assets and nothing downstream can tell.
"""

import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shortcut_kit import (                                            # noqa: E402
    action, album_is, append_var, find_photos, if_contains, out, repeat_count,
    repeat_each, save_file, set_var, shortcut_input, taken_within_days, text,
    uid, var, write_shortcut,
)

# ── Configuration ───────────────────────────────────────────
TRIAGE_ALBUM = 'Triage'      # working set, rebuilt from scratch by every export
TRIAGED_ALBUM = 'Triaged'    # everything already swiped once; never offered again
EXPORT_ROOT = '/TriageExport'
WINDOW_DAYS = 3              # how far back an export looks
WINDOW_LIMIT = 400           # hard cap, so a bad run cannot chew through the library
PHOTO_WIDTH = 800
VIDEO_SIZE = '960x540'
# Album name → sidecar kind. The app stages each of these as a grid before swiping.
# Only real albums belong here. "Screenshots" is a smart album, which Find Photos
# cannot see — asking for it aborts the whole run with "Photo album not found" —
# so screenshots come from the dedicated action below instead.
CATEGORIES = [('WhatsApp', 'whatsapp')]
SCREENSHOT_SCAN = 300   # how many recent screenshots to name in the sidecar

BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build')


# ── Reusable fragments ──────────────────────────────────────
def find_triage(u):
    """The ordering that defines identity. Used verbatim by every shortcut."""
    return find_photos(u, [album_is(TRIAGE_ALBUM)], sort='Date Taken',
                       order='Oldest First', limit=None)


def add_each_to_album(items, album_name):
    return repeat_each(items, [
        action('is.workflow.actions.savetocameraroll',
               WFCameraRollSelectedGroup=album_name, WFInput=var('Repeat Item')),
    ])


def remove_each_from_album(items, album_name):
    return repeat_each(items, [
        action('is.workflow.actions.removefromalbum',
               WFRemoveAlbumSelectedGroup=album_name, WFInput=var('Repeat Item')),
    ])


def subtract_album(from_album, other_album):
    """Remove everything that is in both albums from `from_album`.

    An intersection plus a removal, rather than an "Album is not" filter: the
    numeric operator for "is not" has never been verified on this machine, and a
    wrong operator in a filter fails silently instead of erroring.
    """
    u = uid()
    return ([find_photos(u, [album_is(from_album), album_is(other_album)])]
            + remove_each_from_album(out(u, 'Photos'), from_album))


def clear_album(album_name):
    u = uid()
    return [find_photos(u, [album_is(album_name)])] + \
        remove_each_from_album(out(u, 'Photos'), album_name)


def format_date(source, fmt):
    u = uid()
    return u, action('is.workflow.actions.format.date', UUID=u, WFDate=source,
                     WFDateFormatStyle='Custom', WFDateFormat=fmt)


# ── 1. Photo Curator Export ─────────────────────────────────
def build_export():
    acts = []

    started = uid()
    acts.append(action('is.workflow.actions.date', UUID=started,
                       WFDateActionMode='Current Date'))
    stamp_u, stamp_act = format_date(out(started, 'Date'), 'yyyy-MM-dd-HHmm')
    acts.append(stamp_act)
    acts.append(set_var('Stamp', out(stamp_u, 'Formatted Date')))
    started_u, started_act = format_date(out(started, 'Date'), 'yyyy-MM-dd HH:mm:ss')
    acts.append(started_act)
    acts.append(set_var('StartedAt', out(started_u, 'Formatted Date')))

    # Rebuild the working album: window, minus anything already triaged.
    acts += clear_album(TRIAGE_ALBUM)
    recent = uid()
    acts.append(find_photos(recent, [taken_within_days(WINDOW_DAYS)],
                            order='Oldest First', limit=WINDOW_LIMIT))
    acts += add_each_to_album(out(recent, 'Photos'), TRIAGE_ALBUM)
    acts += subtract_album(TRIAGE_ALBUM, TRIAGED_ALBUM)

    # Category sidecars. Names only — they steer the staging grid in the app and
    # nothing else, so a filename collision costs a mis-staged thumbnail. Names
    # that match nothing in the export are ignored, so a sidecar may over-list.
    for album_name, kind in CATEGORIES:
        found = uid()
        acts.append(find_photos(found, [album_is(TRIAGE_ALBUM), album_is(album_name)]))
        acts += _sidecar(kind, out(found, 'Photos'))

    shots = uid()
    acts.append(action('is.workflow.actions.getlastscreenshot', UUID=shots,
                       WFGetLatestPhotoCount=SCREENSHOT_SCAN))
    acts += _sidecar('screenshot', out(shots, 'Latest Screenshots'))

    # The export itself.
    assets = uid()
    acts.append(find_triage(assets))
    acts.append(set_var('Assets', out(assets, 'Photos')))
    counted = uid()
    acts.append(action('is.workflow.actions.count', UUID=counted,
                       Input=var('Assets'), WFCountType='Items'))
    acts.append(set_var('Total', out(counted, 'Count')))

    item = uid()
    name = uid()
    body = [
        action('is.workflow.actions.getitemfromlist', UUID=item, WFInput=var('Assets'),
               WFItemSpecifier='Item At Index', WFItemIndex=var('Repeat Index')),
        action('is.workflow.actions.getitemname', UUID=name, WFInput=out(item, 'Item from List')),
    ]
    body += if_contains(
        out(name, 'Name'), 'MOV',
        _video_branch(item, name),
        # Screen recordings land as MP4 rather than MOV, so the same branch again
        # rather than one condition that has to match both.
        if_contains(out(name, 'Name'), 'MP4',
                    _video_branch(item, name),
                    _photo_branch(item, name)))
    acts += repeat_count(var('Total'), body)

    # manifest.json
    first_i, first_n, last_i, last_n = uid(), uid(), uid(), uid()
    acts += [
        action('is.workflow.actions.getitemfromlist', UUID=first_i, WFInput=var('Assets'),
               WFItemSpecifier='First Item'),
        action('is.workflow.actions.getitemname', UUID=first_n,
               WFInput=out(first_i, 'Item from List')),
        action('is.workflow.actions.getitemfromlist', UUID=last_i, WFInput=var('Assets'),
               WFItemSpecifier='Last Item'),
        action('is.workflow.actions.getitemname', UUID=last_n,
               WFInput=out(last_i, 'Item from List')),
    ]
    ended = uid()
    acts.append(action('is.workflow.actions.date', UUID=ended, WFDateActionMode='Current Date'))
    ended_u, ended_act = format_date(out(ended, 'Date'), 'yyyy-MM-dd HH:mm:ss')
    acts.append(ended_act)

    manifest = uid()
    acts.append(action(
        'is.workflow.actions.gettext', UUID=manifest,
        WFTextActionText=text(
            '{"album":"' + TRIAGE_ALBUM + '","count":{},"first":"{}","last":"{}",'
            '"startedAt":"{}","exportedAt":"{}","folder":"{}","windowDays":'
            + str(WINDOW_DAYS) + '}',
            var('Total'), out(first_n, 'Name'), out(last_n, 'Name'),
            var('StartedAt'), out(ended_u, 'Formatted Date'), var('Stamp'))))
    acts += save_file('manifest.json',
                      text(EXPORT_ROOT + '/{}/manifest.json', var('Stamp')),
                      out(manifest, 'Text'))

    acts.append(action(
        'is.workflow.actions.notification',
        WFNotificationActionBody=text(
            'Triage export ready: {} items in {}. Started {}, finished {}.',
            var('Total'), var('Stamp'), var('StartedAt'), out(ended_u, 'Formatted Date')),
        WFNotificationActionTitle='Photo Curator',
        WFInputIsShownAsAttachment=False))

    return acts


def _sidecar(kind, items):
    vname = f'Names_{kind}'
    got = uid()
    acts = repeat_each(items, [
        action('is.workflow.actions.getitemname', UUID=got, WFInput=var('Repeat Item')),
        append_var(vname, out(got, 'Name')),
    ])
    joined = uid()
    acts.append(action('is.workflow.actions.text.combine', UUID=joined,
                       text=var(vname), WFTextSeparator='New Lines'))
    return acts + save_file(
        f'group-{kind}.txt',
        text(EXPORT_ROOT + '/{}/group-' + kind + '.txt', var('Stamp')),
        out(joined, 'Combined Text'))


def _video_branch(item, name):
    encoded = uid()
    return [
        action('is.workflow.actions.encodemedia', UUID=encoded,
               WFMedia=out(item, 'Item from List'), WFMediaSize=VIDEO_SIZE,
               WFMediaAudioOnly=False),
    ] + save_file(
        text('{}_{}.mp4', var('Repeat Index'), out(name, 'Name')),
        text(EXPORT_ROOT + '/{}/{}_{}.mp4', var('Stamp'), var('Repeat Index'), out(name, 'Name')),
        out(encoded, 'Encoded Media'))


def _photo_branch(item, name):
    resized, converted = uid(), uid()
    return [
        action('is.workflow.actions.image.resize', UUID=resized,
               WFImage=out(item, 'Item from List'),
               WFImageResizeWidth=PHOTO_WIDTH, WFImageResizeHeight='Auto'),
        action('is.workflow.actions.image.convert', UUID=converted,
               WFInput=out(resized, 'Resized Image'), WFImageFormat='JPEG',
               WFImageCompressionQuality=0.7, WFImagePreserveMetadata=False),
    ] + save_file(
        text('{}_{}.jpg', var('Repeat Index'), out(name, 'Name')),
        text(EXPORT_ROOT + '/{}/{}_{}.jpg', var('Stamp'), var('Repeat Index'), out(name, 'Name')),
        out(converted, 'Converted Image'))


# ── 2. Delete Photos By Index ───────────────────────────────
def build_delete():
    """One confirmation for the whole batch, with a per-asset fallback.

    Deleting inside the loop costs one system confirmation per photo, which is
    unusable at 70 photos. Deleting an accumulated set is a single atomic
    PHAssetChangeRequest, so one unmaterialisable asset silently fails all of
    them. So: try the batch, then count the album again. If nothing went, fall
    back to deleting one at a time — the annoying path, but only when it is the
    only path that works.
    """
    acts = []
    split = uid()
    acts.append(action('is.workflow.actions.text.split', UUID=split,
                       text=shortcut_input(), WFTextSeparator='Custom',
                       WFTextCustomSeparator=','))
    acts.append(set_var('Indices', out(split, 'Split Text')))

    assets = uid()
    acts.append(find_triage(assets))
    acts.append(set_var('Assets', out(assets, 'Photos')))
    before = uid()
    acts.append(action('is.workflow.actions.count', UUID=before,
                       Input=var('Assets'), WFCountType='Items'))
    acts.append(set_var('Before', out(before, 'Count')))

    picked = uid()
    acts += repeat_each(var('Indices'), [
        action('is.workflow.actions.getitemfromlist', UUID=picked, WFInput=var('Assets'),
               WFItemSpecifier='Item At Index', WFItemIndex=var('Repeat Item')),
        append_var('Targets', out(picked, 'Item from List')),
    ])
    acts.append(action('is.workflow.actions.deletephotos', UUID=uid(), photos=var('Targets')))

    after_find, after_count = uid(), uid()
    acts.append(find_triage(after_find))
    acts.append(action('is.workflow.actions.count', UUID=after_count,
                       Input=out(after_find, 'Photos'), WFCountType='Items'))

    one = uid()
    fallback = repeat_each(var('Targets'), [
        action('is.workflow.actions.deletephotos', UUID=one, photos=var('Repeat Item')),
    ]) + [action('is.workflow.actions.showresult',
                 Text='The batch delete did nothing, so they were deleted one at a '
                      'time instead. One of them is probably not downloaded from '
                      'iCloud.')]
    acts += if_contains(out(after_count, 'Count'), var('Before'), fallback)

    # Mark the survivors, so tomorrow's export does not offer them again. Subtract
    # first, so running this twice on the same export cannot re-add a member.
    acts += subtract_album(TRIAGE_ALBUM, TRIAGED_ALBUM)
    survivors = uid()
    acts.append(find_triage(survivors))
    acts += add_each_to_album(out(survivors, 'Photos'), TRIAGED_ALBUM)

    done = uid()
    acts.append(action('is.workflow.actions.count', UUID=done,
                       Input=var('Targets'), WFCountType='Items'))
    acts.append(action('is.workflow.actions.showresult',
                       Text=text('Deleted {} of {} · indices {}',
                                 out(done, 'Count'), var('Before'), var('Indices'))))
    return acts, ['ActionExtension']


# ── 3. Add Photos To Album By Index ─────────────────────────
def build_add_to_album(target_album='Swipe-album'):
    acts = []
    split = uid()
    acts.append(action('is.workflow.actions.text.split', UUID=split,
                       text=shortcut_input(), WFTextSeparator='Custom',
                       WFTextCustomSeparator=','))
    acts.append(set_var('Indices', out(split, 'Split Text')))
    assets = uid()
    acts.append(find_triage(assets))
    acts.append(set_var('Assets', out(assets, 'Photos')))

    picked = uid()
    acts += repeat_each(var('Indices'), [
        action('is.workflow.actions.getitemfromlist', UUID=picked, WFInput=var('Assets'),
               WFItemSpecifier='Item At Index', WFItemIndex=var('Repeat Item')),
        action('is.workflow.actions.savetocameraroll',
               WFCameraRollSelectedGroup=target_album, WFInput=out(picked, 'Item from List')),
        append_var('Done', out(picked, 'Item from List')),
    ])
    counted = uid()
    acts.append(action('is.workflow.actions.count', UUID=counted,
                       Input=var('Done'), WFCountType='Items'))
    acts.append(action('is.workflow.actions.showresult',
                       Text=text('Added {} to ' + target_album, out(counted, 'Count'))))
    return acts, ['ActionExtension']


# ── 4. Quick Delete By Name ─────────────────────────────────
def build_quick_delete():
    """The manual-pick path. Filenames are not unique, so this shows its work.

    Find Photos "Name is X" matches without the extension and collides on Live
    Photo pairs, edited copies and re-imports. That is exactly why the main path
    uses positions. This one exists because picking six photos by hand should not
    require an export, and it earns the right to be unsafe by putting every asset
    it matched in front of you in Quick Look before anything is deleted.
    """
    acts = []
    split = uid()
    acts.append(action('is.workflow.actions.text.split', UUID=split,
                       text=shortcut_input(), WFTextSeparator='New Lines'))
    acts.append(set_var('Names', out(split, 'Split Text')))

    found = uid()
    acts += repeat_each(var('Names'), [
        find_photos(found, [{'Operator': 4, 'Property': 'Name', 'Removable': True,
                             'Values': {'String': var('Repeat Item')}}]),
        append_var('Matched', out(found, 'Photos')),
    ])
    acts.append(action('is.workflow.actions.previewdocument', WFInput=var('Matched')))
    counted = uid()
    acts.append(action('is.workflow.actions.count', UUID=counted,
                       Input=var('Matched'), WFCountType='Items'))
    acts.append(action('is.workflow.actions.deletephotos', UUID=uid(), photos=var('Matched')))
    acts.append(action('is.workflow.actions.showresult',
                       Text=text('Deleted {} matched asset(s).', out(counted, 'Count'))))
    return acts, ['ActionExtension']


# ── Driver ──────────────────────────────────────────────────
SHORTCUTS = {
    'Photo Curator Export': lambda: (build_export(), None),
    'Delete Photos By Index': build_delete,
    'Add Photos To Album By Index': build_add_to_album,
    'Quick Delete By Name': build_quick_delete,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-sign', action='store_true')
    ap.add_argument('--out', default=os.path.expanduser('~/Downloads'))
    args = ap.parse_args()

    os.makedirs(BUILD_DIR, exist_ok=True)
    built = {}
    for name, fn in SHORTCUTS.items():
        acts, types = fn()
        path = os.path.join(BUILD_DIR, name.replace(' ', '_') + '.plist.shortcut')
        write_shortcut(path, acts, types=types)
        built[name] = (path, acts)
        print(f'built  {name}: {len(acts)} actions -> {path}')

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from verify_shortcuts import verify_all
    problems = verify_all({n: a for n, (_, a) in built.items()})
    if problems:
        print('\nVERIFY FAILED')
        for p in problems:
            print('  ' + p)
        return 1
    print('\nverify: all checks passed')

    if args.no_sign:
        return 0
    for name, (path, _) in built.items():
        signed = os.path.join(BUILD_DIR, name + '.shortcut')
        r = subprocess.run(['shortcuts', 'sign', '--mode', 'anyone', '-i', path,
                            '-o', signed], capture_output=True, text=True)
        if r.returncode != 0:
            print(f'sign FAILED for {name}: {r.stderr.strip()}')
            return 1
        shutil.copy(signed, os.path.join(args.out, name + '.shortcut'))
        print(f'signed {name} -> {os.path.join(args.out, name + ".shortcut")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
