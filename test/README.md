# Tests

No build step, no runner, no dependencies. The suite runs inside the real page and
calls the app's real functions, exposed by the `?test=1` hook at the bottom of
`index.html`.

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
quick pick, the index strings that go to Shortcuts, and the confirm screen's two modes.
What is *not* covered is touch handling and video playback, which need a real device.

## Shortcuts

The Shortcuts have their own checks, which do not need the phone:

```bash
python3 tools/verify_shortcuts.py    # static checks on the generated plists
python3 tools/build_shortcuts.py     # build, verify, sign into ~/Downloads
python3 tools/roundtrip_check.py     # after importing: diff stored vs generated
```

`verify_shortcuts.py` catches the failure mode that costs the most time — a parameter
key that is wrong for its action, which imports without complaint and leaves the input
chip unbound. `roundtrip_check.py` catches the same thing from the other side, by
reading back what Shortcuts actually stored.
