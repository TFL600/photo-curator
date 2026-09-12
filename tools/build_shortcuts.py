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
import copy
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shortcut_kit import (                                            # noqa: E402
    action, album_is, append_var, find_photos, out, repeat_count,
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
# Passed as a float, the way WFContentItemLimitNumber is in the working shortcuts.
# An int here appeared to be ignored: a run that should have listed hundreds of
# screenshots wrote a 422-byte sidecar, about eleven names, so screenshots outside
# that handful were never tagged and went into the swipe stack untouched.
SCREENSHOT_SCAN = 120.0
# Get Type's exact wording for a video is not known. Test every plausible spelling
# rather than spend a round trip per guess; diag-types.txt records the real answer.
# Deliberately small. These scans cost time proportional to the library, not to
# the batch, and a 500-video scan hung a two-item export for minutes. Only assets
# inside the export window can matter, so a shallow scan loses nothing: a video
# older than this is also older than WINDOW_DAYS and is not in the export.
VIDEO_SCAN = 60.0
# Most a single hand-picked name may resolve to. Live Photo pairs and edited
# copies make a couple plausible; anything more means the filter is not working.
QUICK_NAME_LIMIT = 3.0

BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build')

# Every export stamps the build it came from into the manifest and the finish
# notification. Importing a shortcut whose name already exists does not replace
# it — Shortcuts keeps both and suffixes one — so several builds can sit in the
# library at once looking identical. The stamp is how you tell which one ran.
# Exactly 8 characters, so substituting it cannot shift any text token offset.
BUILD_PLACEHOLDER = 'BUILDID0'


def stamp_build_id(actions):
    """Replace the placeholder with a hash of the logic, ignoring UUIDs."""
    skeleton = copy.deepcopy(actions)

    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items()
                    if k not in ('UUID', 'OutputUUID', 'GroupingIdentifier')}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v

    digest = hashlib.sha256(plistlib.dumps(strip(skeleton))).hexdigest()[:8]

    def put(v):
        if isinstance(v, dict):
            return {k: put(x) for k, x in v.items()}
        if isinstance(v, list):
            return [put(x) for x in v]
        if isinstance(v, str):
            return v.replace(BUILD_PLACEHOLDER, digest)
        return v

    return put(actions), digest


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


# ── 1. Photo Curator Export ─────────────────────────────────
def build_export():
    acts = []

    # No Format Date anywhere. Its WFDateFormatStyle / WFDateFormat pair survives
    # import intact and still produced an empty string on the phone, so every
    # timestamp downstream of it came out blank. Raw date tokens render as a
    # localised string, which is good enough to read; the app displays whatever
    # it is given and only computes a duration when it can parse both ends.
    started = uid()
    acts.append(action('is.workflow.actions.date', UUID=started,
                       WFDateActionMode='Current Date'))
    acts.append(set_var('StartedAt', out(started, 'Date')))

    # Rebuild the working album: window, minus anything already triaged.
    acts += clear_album(TRIAGE_ALBUM)
    recent = uid()
    acts.append(find_photos(recent, [taken_within_days(WINDOW_DAYS)],
                            order='Oldest First', limit=WINDOW_LIMIT))
    acts += add_each_to_album(out(recent, 'Photos'), TRIAGE_ALBUM)
    acts += subtract_album(TRIAGE_ALBUM, TRIAGED_ALBUM)
    acts += _export_body()
    return acts


def build_export_selected():
    """The same export, over photos handed in from the Photos share sheet.

    This replaces matching hand-picked photos by filename, which cannot be made
    safe. `Find Photos where Name is X` matches without the extension and collides
    on Live Photo pairs and edited copies — 229 names once resolved to 257 assets —
    and the value shape for a name filter could not be verified from here at all:
    on the phone it did not bind, so 40 names matched the per-name cap times 40,
    which is arbitrary photos.

    Selecting in Photos and sharing to this instead puts the chosen assets straight
    into the album, which means the whole proven pipeline applies unchanged:
    position in the album is identity, the app reads indices, and Delete Photos By
    Index needs no modification. It is also fewer taps than picking in the app.
    """
    acts = list(clear_album(TRIAGE_ALBUM))
    acts += add_each_to_album(shortcut_input(), TRIAGE_ALBUM)
    acts += _export_body()
    return acts, ['ActionExtension']


def _export_body():
    """Everything after the Triage album has been filled: files and manifest."""
    acts = []

    # Clear out every previous export first.
    #
    # Get Contents of Folder really does need a security-scoped bookmark, but Get
    # File does not: handed a path with the picker switched off it returns the
    # folder, and Delete Files removes it outright. Verified on this Mac on
    # 2026-09-12, fixture and all, in tools/probe_cleanup.py.
    #
    # Doing this *before* writing anything, rather than filtering the new folder
    # out afterwards, avoids needing an "is not" comparison — the one filter
    # operator that has never been verified here. It costs nothing either: the
    # album rebuild above has already happened, so every older folder's indices
    # now point at a Triage album that no longer exists. Stale folders were never
    # just clutter; they were a wrong-deletion waiting to happen.
    #
    # The repeat is the guard. An empty result means zero iterations, which is how
    # you avoid asking Delete Files what it does with nothing.
    old = uid()
    acts.append(action('is.workflow.actions.documentpicker.open', UUID=old,
                       WFGetFilePath=EXPORT_ROOT, WFShowFilePicker=False,
                       WFFileErrorIfNotFound=False))
    acts += repeat_each(out(old, 'File'), [
        action('is.workflow.actions.file.delete', UUID=uid(),
               WFInput=var('Repeat Item'), WFDeleteImmediatelyDelete=True)])

    setu = uid()
    acts.append(find_triage(setu))
    acts.append(set_var('Assets', out(setu, 'Photos')))
    countu = uid()
    acts.append(action('is.workflow.actions.count', UUID=countu,
                       Input=var('Assets'), WFCountType='Items'))
    acts.append(set_var('Total', out(countu, 'Count')))
    firstu, firstn = uid(), uid()
    acts.append(action('is.workflow.actions.getitemfromlist', UUID=firstu,
                       WFInput=var('Assets'), WFItemSpecifier='First Item'))
    acts.append(action('is.workflow.actions.getitemname', UUID=firstn,
                       WFInput=out(firstu, 'Item from List')))
    acts.append(set_var('First', out(firstn, 'Name')))
    acts += _folder_name()

    # Category sidecars. Names only — they steer the staging grid in the app and
    # nothing else, so a filename collision costs a mis-staged thumbnail. Names
    # that match nothing in the export are ignored, so a sidecar may over-list.
    for album_name, kind in CATEGORIES:
        found = uid()
        acts.append(find_photos(found, [album_is(TRIAGE_ALBUM), album_is(album_name)]))
        acts += _sidecar(kind, out(found, 'Photos'))

    # How a video is told apart from a photo. Get Type reports the same string for
    # both — confirmed off diag-types.txt from a real run containing one of each —
    # so type inspection cannot do it. Instead: ask Photos for the recent videos,
    # keep their names in one block of text, and test membership by name inside the
    # loop. Names are UUIDs, so there is nothing for a name to collide with, and
    # every piece of this is a serialization already proven on the phone: Get Latest
    # Videos mirrors Get Latest Screenshots, and Contains with a variable on the
    # right-hand side is what Delete Photos By Index already does.
    vids = uid()
    acts.append(action('is.workflow.actions.getlastvideo', UUID=vids,
                       WFGetLatestPhotoCount=VIDEO_SCAN))
    vnames, vacts = _names_of(out(vids, 'Latest Videos'))
    acts += vacts
    acts.append(set_var('VideoList', vnames))   # diagnostic only, see diag-videos.txt
    vcount = uid()
    acts.append(action('is.workflow.actions.count', UUID=vcount,
                       Input=out(vids, 'Latest Videos'), WFCountType='Items'))
    acts.append(set_var('VidsSeen', out(vcount, 'Count')))
    acts += save_file('diag-videos.txt',
                      text(EXPORT_ROOT + '/{}/diag-videos.txt', var('Stamp')),
                      var('VideoList'))

    shots = uid()
    acts.append(action('is.workflow.actions.getlastscreenshot', UUID=shots,
                       WFGetLatestPhotoCount=SCREENSHOT_SCAN))
    acts += _sidecar('screenshot', out(shots, 'Latest Screenshots'))
    shotcount = uid()
    acts.append(action('is.workflow.actions.count', UUID=shotcount,
                       Input=out(shots, 'Latest Screenshots'), WFCountType='Items'))
    acts.append(set_var('ShotsSeen', out(shotcount, 'Count')))

    # The export itself. Assets and Total were captured above, before the sidecars,
    # and nothing since has touched the album.
    # Every asset gets a JPEG, videos included — that is the poster frame, and it
    # keeps indices, thumbnails and the strip working with no branching at all.
    #
    # There is no If here on purpose. Three attempts at one failed the same way:
    # a name test could not work (names are UUIDs with no extension), Get Type
    # reports "Photo media" for videos as well as photos, and testing membership of
    # the video-name list never fired either — the legacy WFCondition keys are
    # stored on import and then ignored at runtime, exactly like Format Date's.
    # Videos are handled by a second pass below instead, which needs no condition.
    item = uid()
    name = uid()
    body = [
        action('is.workflow.actions.getitemfromlist', UUID=item, WFInput=var('Assets'),
               WFItemSpecifier='Item At Index', WFItemIndex=var('Repeat Index')),
        action('is.workflow.actions.getitemname', UUID=name, WFInput=out(item, 'Item from List')),
    ]
    body += _photo_branch(item, name)
    acts += repeat_count(var('Total'), body)

    # Second pass: the videos in this batch, written as companion files.
    #
    # Filter Photos takes an input list, so the recent videos can be narrowed to
    # the ones in Triage without needing a media-type filter (there isn't one) and
    # without a condition. The loop is then only as long as the batch's videos.
    # Each is saved as v_<name>.mp4 alongside its JPEG; the app pairs them up by
    # name, plays the video and keeps the JPEG as the instant thumbnail. If this
    # pass ever yields nothing, the export degrades to poster frames rather than
    # breaking.
    vintriage = uid()
    acts.append(action(
        'is.workflow.actions.filter.photos', UUID=vintriage,
        WFContentItemInputParameter=out(vids, 'Latest Videos'),
        WFContentItemSortProperty='Date Taken', WFContentItemSortOrder='Oldest First',
        WFContentItemLimitEnabled=False,
        WFContentItemFilter={
            'Value': {'WFActionParameterFilterPrefix': 1,
                      'WFActionParameterFilterTemplates': [album_is(TRIAGE_ALBUM)],
                      'WFContentPredicateBoundedDate': False},
            'WFSerializationType': 'WFContentPredicateTableTemplate'}))
    vname, venc = uid(), uid()
    acts += repeat_each(out(vintriage, 'Photos'), [
        action('is.workflow.actions.getitemname', UUID=vname, WFInput=var('Repeat Item')),
        action('is.workflow.actions.encodemedia', UUID=venc, WFMedia=var('Repeat Item'),
               WFMediaSize=VIDEO_SIZE, WFMediaAudioOnly=False),
    ] + save_file(
        text('v_{}.mp4', out(vname, 'Name')),
        text(EXPORT_ROOT + '/{}/v_{}.mp4', var('Stamp'), out(vname, 'Name')),
        out(venc, 'Encoded Media')))
    vtcount = uid()
    acts.append(action('is.workflow.actions.count', UUID=vtcount,
                       Input=out(vintriage, 'Photos'), WFCountType='Items'))
    acts.append(set_var('VidsHere', out(vtcount, 'Count')))

    # What Get Type actually says, one line per asset in index order. Purely
    # diagnostic — the app ignores diag-*.txt — but it is the difference between
    # knowing the answer and guessing at it again.
    typ, typjoin = uid(), uid()
    acts += [
        action('is.workflow.actions.getitemtype', UUID=typ, WFInput=var('Assets')),
        action('is.workflow.actions.text.combine', UUID=typjoin,
               text=out(typ, 'Type'), WFTextSeparator='New Lines'),
    ]
    acts += save_file('diag-types.txt',
                      text(EXPORT_ROOT + '/{}/diag-types.txt', var('Stamp')),
                      out(typjoin, 'Combined Text'))

    # manifest.json
    last_i, last_n = uid(), uid()
    acts += [
        action('is.workflow.actions.getitemfromlist', UUID=last_i, WFInput=var('Assets'),
               WFItemSpecifier='Last Item'),
        action('is.workflow.actions.getitemname', UUID=last_n,
               WFInput=out(last_i, 'Item from List')),
    ]
    ended = uid()
    acts.append(action('is.workflow.actions.date', UUID=ended, WFDateActionMode='Current Date'))

    manifest = uid()
    acts.append(action(
        'is.workflow.actions.gettext', UUID=manifest,
        WFTextActionText=text(
            '{"album":"' + TRIAGE_ALBUM + '","count":{},"first":"{}","last":"{}",'
            '"startedAt":"{}","exportedAt":"{}","folder":"{}","windowDays":'
            + str(WINDOW_DAYS) + ',"build":"' + BUILD_PLACEHOLDER + '"}',
            var('Total'), var('First'), out(last_n, 'Name'),
            var('StartedAt'), out(ended, 'Date'), var('Stamp'))))
    acts += save_file('manifest.json',
                      text(EXPORT_ROOT + '/{}/manifest.json', var('Stamp')),
                      out(manifest, 'Text'))

    # No finish notification. There was one, reporting counts and the build stamp,
    # and it was removed on the phone on purpose: a daily automation that announces
    # itself every morning is noise, and the counts it carried were debugging aids
    # from the week the export was being got working. What replaced it is the
    # manifest, which is written last — a folder without one is a run that died,
    # and the app already refuses to load that folder.
    return acts


def _folder_name():
    """Sets Stamp to something like "12 Sep 2026 (19)".

    The folder used to be named `<count>-<first asset name>`, which is a UUID —
    unreadable, and it collided twice in one week because consecutive exports
    share a first asset. The date is what you actually need to pick the right
    folder in the Files picker.

    Getting a date into a string without Format Date, which produces an empty
    string here and did so again on 2026-09-12 on this Mac, so it is not a phone
    problem and there is no point trying it a third time. Replace Text is no help
    either: its output came back empty under every input key tried. Split Text
    does work — it is what Delete Photos By Index already runs on — so the date
    token is coerced to text and then cut down.

    Two cuts. " at " takes the time off, which is the whole point. The second
    split on ":" only matters if the device ever renders a date this code has not
    seen: a colon in WFFileDestinationPath is a path separator's worth of trouble,
    and losing the minutes is a much better failure than losing the export.

    Same-day re-runs collide by design. The cleanup above has already removed the
    earlier folder, so there is nothing to collide with, and a name that repeats
    is better than a second folder to choose between.
    """
    d, txt = uid(), uid()
    acts = [
        action('is.workflow.actions.date', UUID=d, WFDateActionMode='Current Date'),
        action('is.workflow.actions.gettext', UUID=txt,
               WFTextActionText=text('{}', out(d, 'Date'))),
    ]
    part = out(txt, 'Text')
    for sep in (' at ', ':'):
        sp, it = uid(), uid()
        acts += [
            action('is.workflow.actions.text.split', UUID=sp, text=part,
                   WFTextSeparator='Custom', WFTextCustomSeparator=sep),
            action('is.workflow.actions.getitemfromlist', UUID=it,
                   WFInput=out(sp, 'Split Text'), WFItemSpecifier='First Item'),
        ]
        part = out(it, 'Item from List')
    stamp = uid()
    acts.append(action('is.workflow.actions.gettext', UUID=stamp,
                       WFTextActionText=text('{} ({})', part, var('Total'))))
    acts.append(set_var('Stamp', out(stamp, 'Text')))
    return acts


def _names_of(items):
    """One newline-joined block of the names of every item in a list.

    Two actions, not a Repeat. Shortcuts actions map over lists, so Get Name on a
    list of assets yields a list of names — the previous version looped and
    appended one at a time, which cost an action per asset in the library and hung
    a two-item export for minutes.
    """
    got, joined = uid(), uid()
    return out(joined, 'Combined Text'), [
        action('is.workflow.actions.getitemname', UUID=got, WFInput=items),
        action('is.workflow.actions.text.combine', UUID=joined,
               text=out(got, 'Name'), WFTextSeparator='New Lines'),
    ]


def _sidecar(kind, items):
    joined, acts = _names_of(items)
    return acts + save_file(
        f'group-{kind}.txt',
        text(EXPORT_ROOT + '/{}/group-' + kind + '.txt', var('Stamp')),
        joined)


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
    """One confirmation for the whole batch, and the counts to prove it worked.

    Deleting inside the loop costs one system confirmation per photo, which is
    unusable at 70 photos. Deleting an accumulated set is a single atomic
    PHAssetChangeRequest, so one unmaterialisable asset silently fails all of
    them: the dialog appears, the count is reported, nothing is deleted.

    This used to try the batch and fall back to per-asset deletes if the album
    count had not moved. That fallback was behind an If, and an If never fires
    here — the legacy condition keys are stored on import and ignored at runtime —
    so the safety net was dead code that read like protection. It is gone.

    Instead the result names the album count before and after. A batch that
    silently deleted nothing shows as two equal numbers, which is visible rather
    than reassuring, and re-running is safe.
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

    acts.append(set_var('After', out(after_count, 'Count')))

    # Mark the survivors, so tomorrow's export does not offer them again. Subtract
    # first, so running this twice on the same export cannot re-add a member.
    acts += subtract_album(TRIAGE_ALBUM, TRIAGED_ALBUM)
    survivors = uid()
    acts.append(find_triage(survivors))
    acts += add_each_to_album(out(survivors, 'Photos'), TRIAGED_ALBUM)

    # The before/after readout that used to be here was removed on the phone. Delete
    # Photos raises its own system confirmation naming the count, so the second
    # dialog said little the first had not. Before and After are still computed and
    # still sit in variables, visible in the run log if a run ever needs explaining.
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
    namecount = uid()
    acts.append(action('is.workflow.actions.count', UUID=namecount,
                       Input=var('Names'), WFCountType='Items'))
    acts.append(set_var('Asked', out(namecount, 'Count')))

    # The per-find limit is a blast radius, not an optimisation. The value shape
    # for a Name filter is the one serialization here that has never been
    # verified, and a filter that fails to bind does not error — Find Photos just
    # returns everything. With Delete Photos downstream, an unbound filter would
    # mean the whole library. QUICK_NAME_LIMIT caps what a single name can
    # possibly resolve to, so the worst case is bounded by how many names were
    # asked for rather than by the size of the library.
    found = uid()
    acts += repeat_each(var('Names'), [
        find_photos(found, [{'Operator': 4, 'Property': 'Name', 'Removable': True,
                             'Values': {'String': var('Repeat Item')}}],
                    limit=QUICK_NAME_LIMIT),
        append_var('Matched', out(found, 'Photos')),
    ])
    counted = uid()
    acts.append(action('is.workflow.actions.count', UUID=counted,
                       Input=var('Matched'), WFCountType='Items'))

    # Say the numbers before showing anything, and before deleting anything. If
    # the filter is not binding, the match count comes back at the cap times the
    # number of names rather than roughly the number of names — which is the
    # signal to stop, and it arrives while stopping is still free.
    acts.append(action('is.workflow.actions.showresult',
                       Text=text('{} name(s) asked for, {} asset(s) matched. Names are '
                                 'not unique, so check the next screen before allowing '
                                 'the deletion — and cancel if that count looks wrong.',
                                 var('Asked'), out(counted, 'Count'))))
    acts.append(action('is.workflow.actions.previewdocument', WFInput=var('Matched')))
    acts.append(action('is.workflow.actions.deletephotos', UUID=uid(), photos=var('Matched')))
    acts.append(action('is.workflow.actions.showresult',
                       Text=text('Deleted {} matched asset(s) for {} name(s).',
                                 out(counted, 'Count'), var('Asked'))))
    return acts, ['ActionExtension']


# ── 5. Mark Batch Triaged ───────────────────────────────
def build_mark_triaged():
    """Record a whole batch as triaged without deleting anything.

    Marking normally happens inside Delete Photos By Index, which means a batch
    where nothing was marked for deletion recorded nothing — and the app hid the
    only button that would have run it. Those photos then came back on the next
    export, which is the exact complaint the Triaged album exists to fix.

    Takes no input and deletes nothing, so it is safe to run twice: the subtract
    step means a second run cannot re-add an existing member and hit error 3300.
    """
    acts = list(subtract_album(TRIAGE_ALBUM, TRIAGED_ALBUM))
    survivors = uid()
    acts.append(find_triage(survivors))
    acts += add_each_to_album(out(survivors, 'Photos'), TRIAGED_ALBUM)
    counted = uid()
    acts.append(action('is.workflow.actions.count', UUID=counted,
                       Input=out(survivors, 'Photos'), WFCountType='Items'))
    acts.append(action('is.workflow.actions.showresult',
                       Text=text('Marked {} as triaged. They will not be offered again.',
                                 out(counted, 'Count'))))
    return acts, ['ActionExtension']


# ── Driver ──────────────────────────────────────────────────
SHORTCUTS = {
    'Photo Curator Export': lambda: (build_export(), None),
    'Delete Photos By Index': build_delete,
    'Add Photos To Album By Index': build_add_to_album,
    'Mark Batch Triaged': build_mark_triaged,
}
# Two routes were tried for hand-picked photos and neither is built any more.
# Quick Delete By Name matched filenames, which cannot be made safe. Curate
# Selected replaced it via the share sheet and worked on paper, but the export
# already covers the need: it takes seconds, so there is nothing a separate
# hand-picked path buys. One way in is worth more than a second way in.



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-sign', action='store_true')
    ap.add_argument('--out', default=os.path.expanduser('~/Downloads'))
    args = ap.parse_args()

    os.makedirs(BUILD_DIR, exist_ok=True)
    built = {}
    for name, fn in SHORTCUTS.items():
        acts, types = fn()
        acts, digest = stamp_build_id(acts)
        path = os.path.join(BUILD_DIR, name.replace(' ', '_') + '.plist.shortcut')
        write_shortcut(path, acts, types=types)
        built[name] = (path, acts)
        print(f'built  {name}: {len(acts)} actions, build {digest} -> {path}')

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
