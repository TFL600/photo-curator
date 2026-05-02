# Photo Curator

A mobile-first web app for quickly culling your iPhone camera roll. Swipe through photos, mark the ones to delete, then batch-delete them via an iOS Shortcut.

**[Open on iPhone →](https://tfl600.github.io/photo-curator/)**

## How it works

1. Tap **Select Photos** and pick photos from your library
2. Swipe **right to keep**, **left to delete** (or tap the left/right sides of the screen)
3. On the confirmation screen, tap **Delete via Shortcuts** — this opens the shortcut with the list of photos to delete

## iOS Shortcut

The app passes a list of filenames and dates to a Shortcut named **"Delete Photos From Text"** in this format:

```
IMG_0225|02/05/2026,IMG_0226|02/05/2026
```

### Installing the Shortcut

> **[Install "Delete Photos From Text" →](https://www.icloud.com/shortcuts/5bc67e3382ac4089809647bb871aacb4)**

