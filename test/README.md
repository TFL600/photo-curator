# Tests

No build step, no runner, no dependencies. The suite runs inside the real page and
calls the app's real functions, exposed by the `?test=1` hook at the bottom of
`index.html`.

```bash
node test/run.js
```

That serves the repo, drives headless Chrome over CDP and exits non-zero on a failure,
with no dependencies — Chrome is already on the machine and Node 22 has a WebSocket
client built in. `node test/run.js staging` runs only the tests whose name matches, and
`node test/run.js --head` opens a real window to watch. An uncaught exception on the
page fails the run even if every check passed, which is how the swipe-window crash would
have been caught.

To drive it by hand instead:

```bash
python3 -m http.server 8765
```

Then open `http://localhost:8765/index.html?test=1` and, in the console:

```js
const m = await import('/test/suite.js?v=' + Date.now());
console.table((await m.run()).failures);
```

`run()` returns `{ total, passed, failed, failures }`. The cache-busting `?v=` matters
— the service worker is network-first, but the module cache is not.

## What is covered

The guard (every rejection path), index parsing, category sidecars, the staging grid,
quick pick, the index strings that go to Shortcuts, the confirm screen's two modes,
the confirm-screen rescue, decisions persisting across a reload, and the swipe-window
regressions. What is *not* covered is touch handling, video playback, and anything
Safari lays out differently from Chrome (the staging grid's tiles overlapped on the
phone and nowhere else), which need a real device.

## Shortcuts

The Shortcuts have their own checks, which do not need the phone:

```bash
python3 tools/verify_shortcuts.py    # static checks on the generated plists
python3 tools/verify_selftest.py     # proves the verifier still catches each failure mode
python3 tools/build_shortcuts.py     # build, verify, sign into ~/Downloads
python3 tools/roundtrip_check.py     # after importing: diff stored vs generated
python3 tools/check_albums.py        # two albums sharing a name, which breaks identity
```

`verify_shortcuts.py` catches the failure mode that costs the most time — a parameter
key that is wrong for its action, which imports without complaint and leaves the input
chip unbound. `roundtrip_check.py` catches the same thing from the other side, by
reading back what Shortcuts actually stored.
