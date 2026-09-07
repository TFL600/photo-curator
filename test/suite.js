// Browser-driven test suite for index.html.
//
// The app has no build step and no test runner, so the suite runs inside the real
// page against the real functions, exposed by the ?test hook at the bottom of
// index.html. See test/README.md for how to run it.

const results = [];
let currentName = null;

function check(label, cond, detail) {
  results.push({ test: currentName, label, pass: !!cond, detail: cond ? undefined : detail });
}

function eq(label, actual, expected) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  check(label, a === e, `expected ${e}, got ${a}`);
}

async function test(name, fn) {
  currentName = name;
  try {
    await fn();
  } catch (err) {
    results.push({ test: name, label: 'threw', pass: false, detail: String(err && err.stack || err) });
  }
  currentName = null;
}

// ── Synthetic files ──────────────────────────────────────
// Real encoded JPEGs, so object URLs, <img> decoding and canvas thumbnailing all
// behave as they do with a genuine export.
const jpegCache = new Map();
function jpegBlob(hue) {
  if (jpegCache.has(hue)) return jpegCache.get(hue);
  const c = document.createElement('canvas');
  c.width = 32; c.height = 32;
  const ctx = c.getContext('2d');
  ctx.fillStyle = `hsl(${hue}, 70%, 55%)`;
  ctx.fillRect(0, 0, 32, 32);
  const p = new Promise(res => c.toBlob(res, 'image/jpeg', 0.7));
  jpegCache.set(hue, p);
  return p;
}

async function photoFile(name, hue = 200) {
  return new File([await jpegBlob(hue)], name, { type: 'image/jpeg' });
}

function videoFile(name) {
  // Not a decodable stream. Nothing under test decodes it: type detection is by
  // MIME type, and thumbnailing resolves to '' on a decode error by design.
  return new File([new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112])], name, { type: 'video/mp4' });
}

function textFile(name, body) {
  return new File([body], name, { type: 'text/plain' });
}

function manifestFile(obj) {
  return new File([JSON.stringify(obj)], 'manifest.json', { type: 'application/json' });
}

// A well-formed export: n items named <i>_IMG_<1000+i>.HEIC.jpg.
async function goodExport(n, extra = {}) {
  const files = [];
  for (let i = 1; i <= n; i++) files.push(await photoFile(`${i}_IMG_${1000 + i}.HEIC.jpg`, i * 37));
  files.push(manifestFile({
    album: 'Triage',
    count: n,
    first: `IMG_1001.HEIC`,
    last: `IMG_${1000 + n}.HEIC`,
    exportedAt: '2026-09-06T09:00:00Z',
    ...extra,
  }));
  return files;
}

function errorText(res) {
  return (res.errors || []).join(' | ');
}

// ── Tests ────────────────────────────────────────────────
export async function run() {
  const pc = window.__pc;
  if (!pc) throw new Error('window.__pc missing — load the page with ?test=1');
  results.length = 0;

  await test('parseIndexedName', () => {
    eq('bare number', pc.parseIndexedName('7.jpg'), { idx: 7, name: '' });
    eq('number + name', pc.parseIndexedName('7_IMG_2177.jpg'), { idx: 7, name: 'IMG_2177' });
    eq('name keeps original extension', pc.parseIndexedName('7_IMG_2177.HEIC.jpg'), { idx: 7, name: 'IMG_2177.HEIC' });
    eq('zero padded', pc.parseIndexedName('0007_IMG_2177.jpg'), { idx: 7, name: 'IMG_2177' });
    eq('no index', pc.parseIndexedName('IMG_2177.jpg'), null);
  });

  await test('normaliseAssetName', () => {
    eq('strips one extension', pc.normaliseAssetName('IMG_1001.HEIC'), 'img_1001');
    eq('bare name unchanged', pc.normaliseAssetName('IMG_1001'), 'img_1001');
    eq('trims', pc.normaliseAssetName('  IMG_1001.heic \n'), 'img_1001');
  });

  await test('guard accepts a good export', async () => {
    const res = await pc.validateSelection(await goodExport(4));
    check('no errors', !res.errors, errorText(res));
    eq('4 entries', res.entries.length, 4);
    eq('ascending', res.entries.map(e => e.idx), [1, 2, 3, 4]);
    eq('name preserved', res.entries[0].name, 'IMG_1001.HEIC');
    eq('manifest parsed', res.manifest.album, 'Triage');
  });

  await test('guard rejects a missing manifest', async () => {
    const files = (await goodExport(3)).filter(f => f.name !== 'manifest.json');
    const res = await pc.validateSelection(files);
    check('rejected', !!res.errors, 'expected rejection');
    check('names manifest.json', /manifest\.json/.test(errorText(res)), errorText(res));
  });

  await test('guard rejects a count mismatch', async () => {
    const files = await goodExport(3, { count: 5 });
    const res = await pc.validateSelection(files);
    check('rejected', !!res.errors, 'expected rejection');
    check('says 5 vs 3', /5/.test(errorText(res)) && /3/.test(errorText(res)), errorText(res));
  });

  await test('guard rejects a duplicate index', async () => {
    const files = await goodExport(3);
    files.push(await photoFile('2_IMG_9999.HEIC.jpg', 10));
    files[files.findIndex(f => f.name === 'manifest.json')] = manifestFile(
      { album: 'Triage', count: 4, first: 'IMG_1001.HEIC', last: 'IMG_1003.HEIC', exportedAt: 'x' });
    const res = await pc.validateSelection(files);
    check('rejected', !!res.errors, 'expected rejection');
    check('names index 2', /index 2\b/.test(errorText(res)), errorText(res));
  });

  await test('guard rejects a gap in the run', async () => {
    const files = [
      await photoFile('1_A.jpg'), await photoFile('2_B.jpg'), await photoFile('4_C.jpg'),
      manifestFile({ album: 'Triage', count: 3, first: 'A', last: 'C', exportedAt: 'x' }),
    ];
    const res = await pc.validateSelection(files);
    check('rejected', !!res.errors, 'expected rejection');
    check('names the break', /continuous run/.test(errorText(res)), errorText(res));
  });

  await test('guard rejects a stray file', async () => {
    const files = await goodExport(2);
    files.push(textFile('notes.txt', 'hello'));
    const res = await pc.validateSelection(files);
    check('rejected', !!res.errors, 'expected rejection');
    check('names the stray', /notes\.txt/.test(errorText(res)), errorText(res));
  });

  await test('guard rejects a first/last name mismatch', async () => {
    const files = await goodExport(3, { last: 'IMG_9999.HEIC' });
    const res = await pc.validateSelection(files);
    check('rejected', !!res.errors, 'expected rejection');
    check('names last', /last item/.test(errorText(res)), errorText(res));
  });

  await test('guard accepts a category sidecar and tags entries', async () => {
    const files = await goodExport(4);
    files.push(textFile('group-whatsapp.txt', 'IMG_1002.HEIC\nIMG_1004.HEIC\n'));
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    eq('sidecar is not counted as media', res.entries.length, 4);
    eq('tags 2 and 4', res.entries.map(e => e.kind || null), [null, 'whatsapp', null, 'whatsapp']);
  });

  await test('sidecar matches names written without an extension', async () => {
    const files = await goodExport(3);
    files.push(textFile('group-screenshot.txt', 'IMG_1002\n'));
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    eq('tagged', res.entries.map(e => e.kind || null), [null, 'screenshot', null]);
  });

  await test('an empty sidecar is harmless', async () => {
    const files = await goodExport(2);
    files.push(textFile('group-whatsapp.txt', ''));
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    eq('nothing tagged', res.entries.filter(e => e.kind).length, 0);
  });

  await test('a sidecar naming an absent asset tags nothing', async () => {
    const files = await goodExport(2);
    files.push(textFile('group-whatsapp.txt', 'IMG_5555.HEIC'));
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    eq('nothing tagged', res.entries.filter(e => e.kind).length, 0);
  });

  await test('videos are detected and load as video', async () => {
    const files = [
      await photoFile('1_IMG_1.HEIC.jpg'),
      videoFile('2_IMG_2.MOV.mp4'),
      manifestFile({ album: 'Triage', count: 2, first: 'IMG_1.HEIC', last: 'IMG_2.MOV', exportedAt: 'x' }),
    ];
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    pc.startSession(res.entries, res.manifest, { quick: false });
    eq('second item is a video', pc.photos.map(p => p.type), ['image', 'video']);
    eq('no staging, straight to swiper', pc.activeScreen(), 'swiper');
  });

  await test('an export with a category opens the staging grid', async () => {
    const files = await goodExport(5);
    files.push(textFile('group-whatsapp.txt', 'IMG_1002.HEIC\nIMG_1003.HEIC\nIMG_1005.HEIC'));
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    eq('staging screen', pc.activeScreen(), 'stage');
    eq('3 items staged', pc.stageItems.length, 3);
    eq('grid cells rendered', document.querySelectorAll('#stage-grid .stage-cell').length, 3);
    eq('nothing picked yet', pc.stagePicked.size, 0);
  });

  await test('untapped staged items go to the delete pile, tapped ones to the stack', async () => {
    const files = await goodExport(5);
    files.push(textFile('group-whatsapp.txt', 'IMG_1002.HEIC\nIMG_1003.HEIC\nIMG_1005.HEIC'));
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    // Tap the middle one.
    document.querySelectorAll('#stage-grid .stage-cell')[1].click();
    eq('one picked', pc.stagePicked.size, 1);
    pc.commitStage();
    eq('now swiping', pc.activeScreen(), 'swiper');
    eq('decisions', pc.photos.map(p => p.decision), [null, 'delete', null, null, 'delete']);
    eq('delete indices', pc.indicesFor('delete'), [2, 5]);
    eq('starts at first undecided', pc.index, 0);
  });

  await test('"Swipe all" leaves the whole category undecided', async () => {
    const files = await goodExport(4);
    files.push(textFile('group-whatsapp.txt', 'IMG_1001.HEIC\nIMG_1002.HEIC'));
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    document.getElementById('btn-stage-all').click();
    eq('now swiping', pc.activeScreen(), 'swiper');
    eq('nothing decided', pc.photos.filter(p => p.decision).length, 0);
  });

  await test('two categories are staged one after the other', async () => {
    const files = await goodExport(6);
    files.push(textFile('group-whatsapp.txt', 'IMG_1001.HEIC'));
    files.push(textFile('group-screenshot.txt', 'IMG_1004.HEIC\nIMG_1005.HEIC'));
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    eq('whatsapp first', document.getElementById('stage-title').textContent, 'WhatsApp');
    pc.commitStage();
    eq('screenshots second', document.getElementById('stage-title').textContent, 'Screenshots');
    eq('still staging', pc.activeScreen(), 'stage');
    pc.commitStage();
    eq('then swiping', pc.activeScreen(), 'swiper');
    eq('all three binned', pc.indicesFor('delete'), [1, 4, 5]);
    eq('swiper starts on the first survivor', pc.index, 1);
  });

  await test('a fully staged-out export goes straight to confirm', async () => {
    const files = await goodExport(2);
    files.push(textFile('group-whatsapp.txt', 'IMG_1001.HEIC\nIMG_1002.HEIC'));
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.commitStage();
    eq('confirm screen', pc.activeScreen(), 'confirm');
    eq('delete string', pc.buildInput(), '1,2');
  });

  await test('index strings are sorted, deduped and comma separated', async () => {
    const res = await pc.validateSelection(await goodExport(5));
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.photos[4].decision = 'delete';
    pc.photos[0].decision = 'delete';
    pc.photos[2].decision = 'delete';
    pc.photos[1].decision = 'album';
    eq('delete', pc.buildInput(), '1,3,5');
    eq('album', pc.buildAlbumInput(), '2');
  });

  await test('quick pick can sort but offers no way to delete', async () => {
    const entries = [
      { file: await photoFile('IMG_0007.jpg', 10), idx: null, name: 'IMG_0007.jpg' },
      { file: await photoFile('IMG_0008.jpg', 90), idx: null, name: 'IMG_0008.jpg' },
    ];
    pc.startSession(entries, null, { quick: true });
    eq('quick mode on', pc.quickMode, true);
    eq('no manifest', pc.manifest, null);
    eq('straight to swiping', pc.activeScreen(), 'swiper');
    pc.photos[1].decision = 'delete';
    pc.showConfirm();
    eq('quick warning shown', document.getElementById('quick-note').style.display, '');
    eq('export banner hidden', document.getElementById('export-banner').style.display, 'none');
    eq('album shortcut hidden', document.getElementById('btn-album-shortcut').style.display, 'none');
    // A filename list must never reach a Shortcut: matching by name resolved 40
    // names to 120 arbitrary assets on a real library.
    eq('no delete button at all', document.getElementById('btn-delete').style.display, 'none');
    check('and it points at the safe route',
      /Curate Selected/.test(document.getElementById('quick-note').textContent),
      document.getElementById('quick-note').textContent);
  });

  await test('quick pick with an empty delete pile still offers nothing', async () => {
    const entries = [{ file: await photoFile('IMG_1.jpg'), idx: null, name: 'IMG_1.jpg' }];
    pc.startSession(entries, null, { quick: true });
    pc.photos[0].decision = 'keep';
    pc.showConfirm();
    const btn = document.getElementById('btn-delete');
    eq('hidden', btn.style.display, 'none');
    check('not styled as the finish button', !btn.classList.contains('btn-finish'), btn.className);
  });

  await test('an export session restores the index-based confirm screen', async () => {
    const res = await pc.validateSelection(await goodExport(3));
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.photos[0].decision = 'delete';
    pc.showConfirm();
    eq('quick warning hidden', document.getElementById('quick-note').style.display, 'none');
    eq('export banner shown', document.getElementById('export-banner').style.display, '');
    eq('delete button', document.getElementById('btn-delete').textContent, 'Delete');
    eq('index summary', document.getElementById('delete-index-summary').textContent, '1 index · #1');
  });

  await test('export timestamps parse and turn into a duration', () => {
    check('space separated date parses',
      !!pc.parseExportDate('2026-09-06 18:30:00'), 'returned null');
    eq('ISO parses too', pc.parseExportDate('2026-09-06T18:30:00Z').getUTCHours(), 18);
    eq('garbage is null', pc.parseExportDate('not a date'), null);
    eq('seconds', pc.exportDuration({ startedAt: '2026-09-06 18:30:00', exportedAt: '2026-09-06 18:30:42' }), '42s');
    eq('minutes', pc.exportDuration({ startedAt: '2026-09-06 18:30:00', exportedAt: '2026-09-06 18:32:05' }), '2m 05s');
    eq('missing field', pc.exportDuration({ exportedAt: '2026-09-06 18:30:00' }), null);
    eq('nonsense span ignored', pc.exportDuration({ startedAt: '2020-01-01 00:00:00', exportedAt: '2026-09-06 18:30:00' }), null);
  });

  await test('the confirm banner reports how long the export took', async () => {
    const files = await goodExport(2, { startedAt: '2026-09-06 09:00:00', exportedAt: '2026-09-06 09:01:12' });
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.showConfirm();
    const meta = document.getElementById('export-meta').textContent;
    check('shows the duration', /exported in 1m 12s/.test(meta), meta);
    check('still shows the album', /Triage/.test(meta), meta);
  });

  await test('an old manifest without timestamps still loads', async () => {
    const files = [
      await photoFile('1_A.jpg'),
      manifestFile({ album: 'Triage', count: 1, exportedAt: '2026-08-31T16:55:00Z' }),
    ];
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.showConfirm();
    const meta = document.getElementById('export-meta').textContent;
    check('no duration claimed', !/exported in/.test(meta), meta);
  });

  await test('an export whose asset names are UUIDs still loads and stages', async () => {
    // Get Name returns the asset's UUID on a real library, not IMG_1234.HEIC.
    const ids = ['1ec281b5-78d0-4b19-9f21-f802e49f3380',
                 'fe576d67-8e29-4a37-b1c7-b497f8367cc0',
                 '2053490d-cb44-4e61-9ab1-5a2e32b9e0be'];
    const files = [];
    for (let i = 0; i < ids.length; i++) files.push(await photoFile(`${i + 1}_${ids[i]}.jpg`, i * 60));
    files.push(manifestFile({
      album: 'Triage', count: 3, first: ids[0], last: ids[2],
      startedAt: '6 September 2026 at 22:16', exportedAt: '6 September 2026 at 22:18',
    }));
    files.push(textFile('group-whatsapp.txt', ids[1]));
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    eq('names parsed whole', res.entries.map(e => e.name), ids);
    eq('sidecar matched a UUID', res.entries.map(e => e.kind || null), [null, 'whatsapp', null]);
    pc.startSession(res.entries, res.manifest, { quick: false });
    eq('staged', pc.activeScreen(), 'stage');
  });

  await test('a localised date string is shown as-is, with no invented duration', async () => {
    const files = await goodExport(2, {
      startedAt: '6 September 2026 at 22:16', exportedAt: '6 September 2026 at 22:18',
    });
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.showConfirm();
    eq('shown verbatim', document.getElementById('export-when').textContent,
       '6 September 2026 at 22:18');
    const meta = document.getElementById('export-meta').textContent;
    check('no duration claimed', !/exported in/.test(meta), meta);
  });

  await test('diagnostic sidecars are carried, not treated as strays', async () => {
    const files = await goodExport(2);
    files.push(textFile('diag-types.txt', 'Image\nQuickTime Movie\n'));
    const res = await pc.validateSelection(files);
    check('no errors', !res.errors, errorText(res));
    eq('not counted as media', res.entries.length, 2);
    eq('nothing tagged from it', res.entries.filter(e => e.kind).length, 0);
  });

  await test('the staging grid says how much of the export it covers', async () => {
    const files = await goodExport(10);
    files.push(textFile('group-screenshot.txt', 'IMG_1003.HEIC\nIMG_1004.HEIC'));
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    const sub = document.getElementById('stage-sub').textContent;
    check('reports 2 of 10', /^2 of 10 items/.test(sub), sub);
  });

  await test('the staging buttons name what they will do', async () => {
    const files = await goodExport(8);
    files.push(textFile('group-whatsapp.txt', 'IMG_1001.HEIC\nIMG_1002.HEIC\nIMG_1003.HEIC\nIMG_1004.HEIC'));
    const res = await pc.validateSelection(files);
    pc.startSession(res.entries, res.manifest, { quick: false });
    const go = document.getElementById('btn-stage-go');
    const all = document.getElementById('btn-stage-all');
    eq('nothing tapped is stated as a deletion', go.textContent, 'Delete all 4');
    check('tally warns', /all <b>4<\/b> would go to the delete pile/.test(
      document.getElementById('stage-tally').innerHTML),
      document.getElementById('stage-tally').innerHTML);
    eq('escape hatch counts too', all.textContent, 'Swipe all 4');
    document.querySelectorAll('#stage-grid .stage-cell')[0].click();
    eq('splits once tapped', go.textContent, 'Delete 3, swipe 1');
    document.querySelectorAll('#stage-grid .stage-cell')[1].click();
    eq('updates again', go.textContent, 'Delete 2, swipe 2');
    document.querySelectorAll('#stage-grid .stage-cell')[1].click();
    eq('untapping reverts', go.textContent, 'Delete 3, swipe 1');
  });

  await test('replays the real 7 Sep export: 11 WhatsApp UUIDs + 6 named screenshots', async () => {
    // Taken verbatim from TriageExport/17-2053490d-.../ on the phone. Asset names
    // are UUIDs for library photos but readable IMG_nnnn for screenshots, and the
    // one video is an uppercase UUID — none of which was true of the fixtures
    // written before a real export existed.
    const wa = ['2053490d-cb2e-4d5e-bea1-5a2e32b9e0be', 'b9f16bab-c935-47c5-acd2-bb6da2986ee2',
                'e61f47ec-5bd0-47ca-b438-2fd48e86dbf6', 'a6199744-b0d9-48bf-a0fd-a8e91e490760',
                'c16f7479-618d-4754-8fcf-e85fbfb81df2', '115227e2-23ff-4aa6-8ff2-2865e1c614d9',
                '1c6d78bf-2ab3-49e3-b654-1a5bc3d8bf3a', '93f75945-2854-4aa7-a2b4-7b0dc3849ad4',
                '2c421896-ebac-478a-b212-c1667669a686', '214C10D6-D6A9-4CF1-99F1-BE839AB9FF9B',
                '60071445-c747-4bcc-b458-427b1d8a9775'];
    const shots = ['IMG_2987', 'IMG_2988', 'IMG_2989', 'IMG_2990', 'IMG_2991', 'IMG_2992'];
    const names = [...wa, ...shots];
    const files = [];
    for (let i = 0; i < names.length; i++) files.push(await photoFile(`${i + 1}_${names[i]}.jpg`, i * 21));
    files.push(manifestFile({
      album: 'Triage', count: 17, first: wa[0], last: 'IMG_2992',
      startedAt: '7 Sep 2026 at 07:34', exportedAt: '7 Sep 2026 at 07:34',
      folder: '17-' + wa[0], windowDays: 3, build: '7294d8a2',
    }));
    files.push(textFile('group-whatsapp.txt', wa.join('\n')));
    // The real sidecar lists 53 screenshots newest-first; only six are in the export.
    files.push(textFile('group-screenshot.txt',
      [...shots].reverse().concat(['IMG_2025', 'IMG_0935', 'IMG_0003']).join('\n')));

    const res = await pc.validateSelection(files);
    check('accepted', !res.errors, errorText(res));
    eq('17 items', res.entries.length, 17);
    eq('11 whatsapp', res.entries.filter(e => e.kind === 'whatsapp').length, 11);
    eq('6 screenshots', res.entries.filter(e => e.kind === 'screenshot').length, 6);
    eq('nothing untagged', res.entries.filter(e => !e.kind).length, 0);

    pc.startSession(res.entries, res.manifest, { quick: false });
    eq('whatsapp staged first', document.getElementById('stage-title').textContent, 'WhatsApp');
    eq('covers 11 of 17', document.getElementById('stage-sub').textContent.startsWith('11 of 17 items'), true);
    pc.commitStage();
    eq('then screenshots', document.getElementById('stage-title').textContent, 'Screenshots');
    pc.commitStage();
    // Every item was staged out, so there is nothing left to swipe.
    eq('straight to confirm', pc.activeScreen(), 'confirm');
    eq('all 17 marked', pc.indicesFor('delete').length, 17);
  });

  await test('a batch with nothing to delete still offers to record itself', async () => {
    const res = await pc.validateSelection(await goodExport(3));
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.photos.forEach(p => { p.decision = 'keep'; });
    pc.showConfirm();
    const btn = document.getElementById('btn-delete');
    eq('button is shown, not hidden', btn.style.display, '');
    eq('and relabelled', btn.textContent, 'Finish \u2014 mark all as triaged');
    check('and no longer looks destructive', btn.classList.contains('btn-finish'), btn.className);
    eq('nothing to emit', pc.buildInput(), '');
  });

  await test('with something to delete it is the delete button again', async () => {
    const res = await pc.validateSelection(await goodExport(3));
    pc.startSession(res.entries, res.manifest, { quick: false });
    pc.photos[0].decision = 'delete';
    pc.photos[1].decision = 'keep';
    pc.showConfirm();
    const btn = document.getElementById('btn-delete');
    eq('label', btn.textContent, 'Delete');
    check('destructive styling back', !btn.classList.contains('btn-finish'), btn.className);
    eq('emits the index', pc.buildInput(), '1');
  });

  await test('a companion video is paired with its poster and plays as video', async () => {
    const files = await goodExport(3);
    files.push(videoFile('v_IMG_1002.HEIC.mp4'));
    const res = await pc.validateSelection(files);
    check('accepted', !res.errors, errorText(res));
    eq('companion is not an item of its own', res.entries.length, 3);
    eq('paired to index 2', res.entries.map(e => !!e.videoFile), [false, true, false]);

    pc.startSession(res.entries, res.manifest, { quick: false });
    eq('types', pc.photos.map(p => p.type), ['image', 'video', 'image']);
    const v = pc.photos[1];
    check('media url is the video', v.url !== v.poster, `${v.url} vs ${v.poster}`);
    eq('file swapped for the video', v.file.name, 'v_IMG_1002.HEIC.mp4');
    eq('thumbnail is the poster, not a decoded frame', v.thumb, v.poster);
    eq('index preserved', v.idx, 2);
  });

  await test('a companion naming nothing is dropped, not an error', async () => {
    const files = await goodExport(2);
    files.push(videoFile('v_IMG_9999.HEIC.mp4'));
    const res = await pc.validateSelection(files);
    check('accepted', !res.errors, errorText(res));
    eq('nothing paired', res.entries.filter(e => e.videoFile).length, 0);
    eq('count still 2', res.entries.length, 2);
  });

  await test('companions do not disturb the count check', async () => {
    // The manifest counts assets, not files. Three assets plus two companions is
    // five files and must still read as a count of three.
    const files = await goodExport(3);
    files.push(videoFile('v_IMG_1001.HEIC.mp4'));
    files.push(videoFile('v_IMG_1003.HEIC.mp4'));
    const res = await pc.validateSelection(files);
    check('accepted', !res.errors, errorText(res));
    eq('two paired', res.entries.filter(e => e.videoFile).length, 2);
  });

  await test('companion matching ignores the original extension', async () => {
    const files = await goodExport(2);
    // Export writes v_<Get Name>.mp4, and Get Name gives a bare name.
    files.push(videoFile('v_IMG_1001.mp4'));
    const res = await pc.validateSelection(files);
    check('accepted', !res.errors, errorText(res));
    eq('matched despite .HEIC in the item name', res.entries[0].videoFile.name, 'v_IMG_1001.mp4');
  });

  const failed = results.filter(r => !r.pass);
  return {
    total: results.length,
    passed: results.length - failed.length,
    failed: failed.length,
    failures: failed,
  };
}
