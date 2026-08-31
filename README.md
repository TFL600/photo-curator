# Photo Curator

A mobile-first web app for quickly culling your iPhone camera roll. Export a triage
folder from Photos, swipe through it, then batch-delete via an iOS Shortcut.

**[Open on iPhone →](https://tfl600.github.io/photo-curator/)**

## Why positions, not filenames

Earlier versions passed `Name|dd/MM/yyyy` pairs to a Shortcut that resolved them with
`Find Photos where Name is X AND Date Taken is on D`. **Filenames are not unique.** Live
Photo pairs, edited copies and re-imports collide, and `Name is` matches without the
extension, which widens the collision further — on a real library a 229-entry list
resolved to 257 assets. Worse, `Delete Photos` on an accumulated set is a single atomic
`PHAssetChangeRequest`, so one unmaterialisable asset (`PHPhotosErrorDomain error -1`)
failed all 257 silently: the confirmation dialog appeared, reported the count, and
deleted nothing.

`PHAsset.localIdentifier` is the correct identifier, but Shortcuts offers no filter for
it. So assets are not named at all: they are referred to **by position** in a
deterministically ordered album.

## How it works

1. Run the **export** Shortcut. It collects the candidates into an album, sorts by Date
   Taken ascending, and writes one resized JPEG per asset into a folder, with the 1-based
   position zero-padded into the filename, plus a `manifest.json`:

   ```
   0001_IMG_2177.jpg
   0002_IMG_2179.jpg
   0003_IMG_5192.jpg
   manifest.json
   ```

   ```json
   {
     "album": "Triage",
     "count": 229,
     "first": "IMG_2177",
     "last": "IMG_2318",
     "exportedAt": "2026-08-31T16:55:00Z"
   }
   ```

2. Tap **Select Export Folder** and pick *every* file in that folder, `manifest.json`
   included.
3. Swipe **right to keep**, **left to delete**, **up to add to an album**.
4. On the confirmation screen, tap **Delete via Shortcuts**.

## The manifest guard

Before anything loads, the app checks that the folder is the export it claims to be. If
any check fails, nothing is loaded and no deletion string can be produced — a mismatched
folder means the positions point at the wrong assets, which is unrecoverable.

- `manifest.json` present, valid JSON, with `count`, `first` and `last`
- every media file matches `NNNN_*` (a file that doesn't is an error, never skipped)
- indices unique and a continuous run from 1 to `count`
- `count` equals the number of media files present
- the first and last files match `first` and `last`

Each failed check is named on screen.

## What the app emits

Positions only — ascending, deduplicated, comma-separated, no spaces:

```
3,7,12,41
```

The confirm screen shows the count and index range before you copy, and displays the
manifest's `exportedAt` prominently.

## iOS Shortcuts

Two shortcuts, both taking the index list above:

- **Delete Photos By Index**
- **Add Photos To Album By Index** (target album `Swipe-album`)

Each runs `Find Photos` on the same album with the same sort (Date Taken ascending), then
loops the pasted indices, uses **Get Item from List** at each index to pull exactly one
asset, and deletes/saves it **inside the loop**. One change request per asset, so a
poisoned asset costs one item rather than the whole batch.

## Known limitation

Assets with an identical Date Taken to the second — bursts and Live Photo pairs produce
these — have no tie-break order guaranteed stable across two separate `Find Photos`
calls. The manifest guard catches gross drift (a photo added or removed since export) but
not a swap *within* a tie group. Members of such a group are usually near-identical, so
the practical cost is low, but it is not zero.

Separately: indices are only valid against the album as it stood at export time. If the
album changes between export and delete, the guard cannot detect it. Re-export if in
doubt.
