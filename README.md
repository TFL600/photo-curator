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

Or build it manually:
1. Open the **Shortcuts** app
2. Create a new shortcut named exactly `Delete Photos From Text`
3. Add a **Find Photos** action filtered by filename/date matching the input
4. Add a **Delete Photos** action

### Sharing your Shortcut

To generate an iCloud install link for others:
1. Open the **Shortcuts** app
2. Long-press your shortcut → **Share** → **Copy iCloud Link**
3. Anyone can tap that link to install it on their device
