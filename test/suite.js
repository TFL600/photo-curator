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

// A filter lets the headless runner re-run one area while a fix is being iterated
// on, without waiting for the burst clustering tests to decode their fixtures.
let nameFilter = null;

async function test(name, fn) {
  if (nameFilter && !nameFilter.test(name)) return;
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

// Flat colours are deliberate above: a dHash of a solid block has no bits set,
// which the app treats as "no structure to compare" and leaves as a singleton.
// Burst tests need real structure, so these draw a deterministic block pattern —
// same seed means near-identical frames, and `detail` adds fine lines that lift
// the Laplacian variance without moving the hash much, which is what "sharper
// frame, same shot" looks like to the ranker.
function patternBlob(seed, detail) {
  const c = document.createElement('canvas');
  c.width = 64; c.height = 64;
  const ctx = c.getContext('2d');
  let st = seed;
  const rnd = () => (st = (st * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  for (let y = 0; y < 8; y++) {
    for (let x = 0; x < 8; x++) {
      const v = Math.round(rnd() * 255);
      ctx.fillStyle = `rgb(${v},${v},${v})`;
      ctx.fillRect(x * 8, y * 8, 8, 8);
    }
  }
  if (detail) {
    // Faint, not bold. At this alpha the Laplacian variance rises about a third
    // while the 9x8 hash moves by two bits, which is the relationship a sharper
    // frame of the same shot actually has. Turn it up and the "sharp" frame stops
    // being a near-duplicate at all, which is a different test.
    ctx.fillStyle = 'rgba(255,255,255,0.18)';
    for (let x = 0; x < 64; x += 2) ctx.fillRect(x, 0, 1, 64);
  }
  return new Promise(res => c.toBlob(res, 'image/jpeg', 0.92));
}

async function patternFile(name, seed, detail) {
  return new File([await patternBlob(seed, detail)], name, { type: 'image/jpeg' });
}

// specs: one entry per photo, either a seed number or [seed, detail].
async function burstExport(specs, extra = {}) {
  const files = [];
  for (let i = 0; i < specs.length; i++) {
    const spec = Array.isArray(specs[i]) ? specs[i] : [specs[i], false];
    files.push(await patternFile(`${i + 1}_IMG_${1000 + i + 1}.HEIC.jpg`, spec[0], spec[1]));
  }
  files.push(manifestFile({
    album: 'Triage',
    count: specs.length,
    first: 'IMG_1001.HEIC',
    last: `IMG_${1000 + specs.length}.HEIC`,
    exportedAt: '2026-09-06T09:00:00Z',
    ...extra,
  }));
  return files;
}

function burstCards() {
  return [...document.querySelectorAll('#burst-scroll .burst-card')];
}

// A tap is one click, and it acts at once.
async function tapCard(n) {
  burstCards()[n].click();
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
export async function run(filter) {
  const pc = window.__pc;
  if (!pc) throw new Error('window.__pc missing — load the page with ?test=1');
  results.length = 0;
  nameFilter = filter ? new RegExp(filter, 'i') : null;

  // Every test here uses the same manifest fields, so they would all share one
  // persistence key and inherit each other's decisions. Off by default; the one
  // test that is about persistence turns it on around its own export.
  pc.setPersistence(false);

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
    await pc.startSession(res.entries, res.manifest);
    eq('second item is a video', pc.photos.map(p => p.type), ['image', 'video']);
    eq('no staging, straight to swiper', pc.activeScreen(), 'swiper');
  });

  await test('an export with a category opens the staging grid', async () => {
    const files = await goodExport(5);
    files.push(textFile('group-whatsapp.txt', 'IMG_1002.HEIC\nIMG_1003.HEIC\nIMG_1005.HEIC'));
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    eq('staging screen', pc.activeScreen(), 'stage');
    eq('3 items staged', pc.stageItems.length, 3);
    eq('grid cells rendered', document.querySelectorAll('#stage-grid .stage-cell').length, 3);
    eq('nothing picked yet', pc.stagePicked.size, 0);
  });

  await test('the staging grid shows every tile at full strength, newest last', async () => {
    const files = await goodExport(30);
    files.push(textFile('group-whatsapp.txt',
      Array.from({ length: 30 }, (_, i) => `IMG_${1001 + i}.HEIC`).join('\n')));
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    const cells = [...document.querySelectorAll('#stage-grid .stage-cell')];
    eq('all thirty in one grid', cells.length, 30);
    const img = cells[0].querySelector('img');
    eq('untapped is not dimmed', getComputedStyle(img).opacity, '1');
    cells[0].click();
    eq('tapped is not dimmed either', getComputedStyle(img).opacity, '1');
    eq('three across on a phone, five on anything wider', getComputedStyle(document.getElementById('stage-grid'))
      .gridTemplateColumns.split(' ').length, innerWidth >= 600 ? 5 : 3);
    const g = document.getElementById('stage-grid');
    check('opens at the bottom, like the camera roll',
      g.scrollHeight <= g.clientHeight || g.scrollTop + g.clientHeight >= g.scrollHeight - 2,
      `${g.scrollTop} + ${g.clientHeight} of ${g.scrollHeight}`);
  });

  await test('untapped staged items go to the delete pile, tapped ones to the stack', async () => {
    const files = await goodExport(5);
    files.push(textFile('group-whatsapp.txt', 'IMG_1002.HEIC\nIMG_1003.HEIC\nIMG_1005.HEIC'));
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
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
    await pc.startSession(res.entries, res.manifest);
    document.getElementById('btn-stage-all').click();
    eq('now swiping', pc.activeScreen(), 'swiper');
    eq('nothing decided', pc.photos.filter(p => p.decision).length, 0);
  });

  await test('two categories are staged one after the other', async () => {
    const files = await goodExport(6);
    files.push(textFile('group-whatsapp.txt', 'IMG_1001.HEIC'));
    files.push(textFile('group-screenshot.txt', 'IMG_1004.HEIC\nIMG_1005.HEIC'));
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
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
    await pc.startSession(res.entries, res.manifest);
    pc.commitStage();
    eq('confirm screen', pc.activeScreen(), 'confirm');
    eq('delete string', pc.buildInput(), '1,2');
  });

  await test('index strings are sorted, deduped and comma separated', async () => {
    const res = await pc.validateSelection(await goodExport(5));
    await pc.startSession(res.entries, res.manifest);
    pc.photos[4].decision = 'delete';
    pc.photos[0].decision = 'delete';
    pc.photos[2].decision = 'delete';
    pc.photos[1].decision = 'album';
    eq('delete', pc.buildInput(), '1,3,5');
    eq('album', pc.buildAlbumInput(), '2');
  });

  await test('an export session restores the index-based confirm screen', async () => {
    const res = await pc.validateSelection(await goodExport(3));
    await pc.startSession(res.entries, res.manifest);
    pc.photos[0].decision = 'delete';
    pc.showConfirm();
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
    await pc.startSession(res.entries, res.manifest);
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
    await pc.startSession(res.entries, res.manifest);
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
    await pc.startSession(res.entries, res.manifest);
    eq('staged', pc.activeScreen(), 'stage');
  });

  await test('a localised date string is shown as-is, with no invented duration', async () => {
    const files = await goodExport(2, {
      startedAt: '6 September 2026 at 22:16', exportedAt: '6 September 2026 at 22:18',
    });
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
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
    await pc.startSession(res.entries, res.manifest);
    const sub = document.getElementById('stage-sub').textContent;
    check('reports 2 of 10', /^2 of 10 items/.test(sub), sub);
  });

  await test('the staging buttons name what they will do', async () => {
    const files = await goodExport(8);
    files.push(textFile('group-whatsapp.txt', 'IMG_1001.HEIC\nIMG_1002.HEIC\nIMG_1003.HEIC\nIMG_1004.HEIC'));
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
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

    await pc.startSession(res.entries, res.manifest);
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
    await pc.startSession(res.entries, res.manifest);
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
    await pc.startSession(res.entries, res.manifest);
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

    await pc.startSession(res.entries, res.manifest);
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

  // ── Burst clustering ──────────────────────────────────
  await test('a run of near-identical frames becomes one burst', async () => {
    const files = await burstExport([7, 7, 7, 41, 99, 123]);
    const res = await pc.validateSelection(files);
    check('accepted', !res.errors, errorText(res));
    await pc.startSession(res.entries, res.manifest);
    eq('burst review opened', pc.activeScreen(), 'burst');
    eq('one cluster', pc.burstQueue.length + 1, 1 + 0);
    eq('three frames in it', pc.burstCurrent.photos.length, 3);
    eq('the three are the matching ones', pc.burstCurrent.photos.map(p => p.idx).sort((a, b) => a - b), [1, 2, 3]);
    eq('a card per frame', burstCards().length, 3);
  });

  await test('flat images are never clustered', async () => {
    // The existing fixtures are solid colours. Their hashes carry no structure,
    // so treating them as "similar" would cluster the whole export into one burst.
    const res = await pc.validateSelection(await goodExport(6));
    await pc.startSession(res.entries, res.manifest);
    eq('straight to swiping', pc.activeScreen(), 'swiper');
    eq('no clusters', pc.burstQueue.length, 0);
  });

  await test('the sharpest frame leads and is pre-ticked', async () => {
    const files = await burstExport([[7, false], [7, true], [7, false], 41]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    eq('cluster of three', pc.burstCurrent.photos.length, 3);
    eq('the detailed frame is first', pc.burstCurrent.photos[0].idx, 2);
    eq('one ticked', pc.burstCurrent.ticked.size, 1);
    check('and it is the first', pc.burstCurrent.ticked.has(pc.burstCurrent.photos[0]));
    eq('first card reads as kept', burstCards()[0].classList.contains('ticked'), true);
    eq('the rest read as deleting', burstCards()[1].classList.contains('ticked'), false);
  });

  await test('keeping four of seven is four taps and one Done', async () => {
    const files = await burstExport([7, 7, 7, 7, 7, 7, 7]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    eq('one burst of seven', pc.burstCurrent.photos.length, 7);
    const kept = [pc.burstCurrent.photos[0].idx];
    // One is already ticked, so three taps add three more. The fourth tap is the
    // one that would untick something, which is the point: keeping four costs four
    // interactions including Done.
    for (const n of [1, 2, 3]) {
      await tapCard(n);
      kept.push(pc.burstCurrent.photos[n].idx);
    }
    eq('four ticked', pc.burstCurrent.ticked.size, 4);
    eq('tally says so', document.getElementById('burst-tally').textContent.replace(/\s+/g, ' '), 'Keeping 4 · Deleting 3');
    pc.finishBurst();
    eq('kept photos are kept', pc.indicesFor('keep').sort((a, b) => a - b), kept.sort((a, b) => a - b));
    eq('the other three are for deletion', pc.indicesFor('delete').length, 3);
    check('no overlap', !pc.indicesFor('delete').some(i => kept.includes(i)));
  });

  await test('kept burst photos never reappear in the swipe stack', async () => {
    const files = await burstExport([7, 7, 7, 41]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    const decided = pc.burstCurrent.photos.map(p => p.idx);
    pc.finishBurst();
    eq('now swiping the singleton', pc.activeScreen(), 'swiper');
    eq('on the one photo nobody has judged', pc.photos[pc.index].idx, 4);
    check('every clustered photo is settled',
      pc.photos.filter(p => decided.includes(p.idx)).every(p => p.decision !== null));
  });

  await test('the index string is exactly the unticked clustered photos', async () => {
    const files = await burstExport([7, 7, 7, 41]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    const order = pc.burstCurrent.photos.map(p => p.idx);
    pc.finishBurst();
    pc.decide('keep');            // the singleton
    const expected = order.slice(1).sort((a, b) => a - b).join(',');
    eq('delete string', pc.buildInput(), expected);
  });

  await test('deleting a whole burst has to be confirmed', async () => {
    const files = await burstExport([7, 7, 7]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    await tapCard(0);                     // untick the only ticked one
    eq('nothing ticked', pc.burstCurrent.ticked.size, 0);
    const realConfirm = window.confirm;
    let asked = '';
    window.confirm = (msg) => { asked = msg; return false; };
    pc.finishBurst();
    window.confirm = realConfirm;
    check('it asked', /Delete all 3/.test(asked), asked);
    eq('and nothing was decided', pc.photos.filter(p => p.decision).length, 0);
  });

  await test('a tap on a burst card keeps it at once, and the zoom never ticks', async () => {
    const files = await burstExport([7, 7, 7, 41]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    burstCards()[1].click();
    check('kept with no wait', pc.burstCurrent.ticked.has(pc.burstCurrent.photos[1]));
    burstCards()[1].querySelector('.burst-badge').click();
    check('the tick toggles too', !pc.burstCurrent.ticked.has(pc.burstCurrent.photos[1]));
    burstCards()[2].querySelector('.burst-zoom-btn').click();
    eq('zoom opened', document.getElementById('burst-zoom').classList.contains('open'), true);
    check('and did not tick', !pc.burstCurrent.ticked.has(pc.burstCurrent.photos[2]));
    document.getElementById('burst-zoom-close').click();
  });

  await test('Done can be taken back', async () => {
    const files = await burstExport([7, 7, 7, 41]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    pc.finishBurst();
    eq('decisions made', pc.photos.filter(p => p.decision).length, 3);
    document.getElementById('undo-toast-btn').click();
    eq('back on the burst', pc.activeScreen(), 'burst');
    eq('nothing decided', pc.photos.filter(p => p.decision).length, 0);
    eq('same cluster, same size', burstCards().length, 3);
  });

  await test('a photo bound for deletion can be rescued on the confirm screen', async () => {
    const files = await burstExport([7, 7, 7]);
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    pc.finishBurst();
    eq('confirm screen', pc.activeScreen(), 'confirm');
    eq('two for deletion', pc.indicesFor('delete').length, 2);
    document.querySelectorAll('#thumb-grid .thumb-item')[0].click();
    eq('one rescued', pc.indicesFor('delete').length, 1);
    eq('and it is kept', pc.indicesFor('keep').length, 2);
  });

  await test('decisions survive closing the tab', async () => {
    pc.setPersistence(true);
    const stamp = 'persist-' + Date.now();
    const files = await burstExport([7, 7, 7, 41], { folder: stamp, exportedAt: stamp });
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    pc.finishBurst();
    const before = { keep: pc.indicesFor('keep'), del: pc.indicesFor('delete') };
    // Same folder, opened again: this is what reloading the page does.
    const again = await pc.validateSelection(await burstExport([7, 7, 7, 41], { folder: stamp, exportedAt: stamp }));
    await pc.startSession(again.entries, again.manifest);
    eq('keeps came back', pc.indicesFor('keep'), before.keep);
    eq('deletes came back', pc.indicesFor('delete'), before.del);
    pc.forgetDecisions();
    pc.setPersistence(false);
  });

  await test('hashing and distance', () => {
    const a = { h0: 0, h1: 0 }, b = { h0: 1, h1: 0 }, c = { h0: 0, h1: 3 };
    eq('identical', pc.hamming(a, a), 0);
    eq('one bit low word', pc.hamming(a, b), 1);
    eq('two bits high word', pc.hamming(a, c), 2);
    eq('symmetric', pc.hamming(b, c), pc.hamming(c, b));
  });

  // ── Regressions from the session that went wrong on 2026-09-19 ──────────
  //
  // All three are about the 290ms window between a swipe and the card being gone.
  // None of them were reachable from the old suite, because the old suite only ever
  // called decide() one at a time and never from the end of the stack.

  await test('a second swipe inside the animation window decides the next photo', async () => {
    const res = await pc.validateSelection(await goodExport(4));
    await pc.startSession(res.entries, res.manifest);
    // Two swipes back to back, faster than the 290ms settle. This is how the app is
    // actually used. The second one used to overwrite the first photo's decision and
    // leave the second undecided.
    pc.decide('delete');
    pc.decide('keep');
    eq('each decision landed on its own photo', pc.photos.map(p => p.decision),
       ['delete', 'keep', null, null]);
    eq('no duplicate in the undo stack', pc.decisionStack, [0, 1]);
    // The second card is still animating, so the index has moved once, not twice.
    eq('showing the second photo', pc.index, 1);
    pc.settleNow();
    eq('and the third once its card is gone', pc.index, 2);
  });

  await test('swiping at the end of the stack is a no-op, not a crash', async () => {
    const res = await pc.validateSelection(await goodExport(3));
    await pc.startSession(res.entries, res.manifest);
    pc.decide('delete');
    pc.decide('delete');
    pc.decide('delete');
    pc.settleNow();                       // flush the last card away
    eq('index is past the end', pc.index, 3);
    // #end-of-stack lives inside #screen-swiper, so the swipe listeners are still
    // live here. This used to throw on photos[photos.length].decision and wedge the
    // session with nothing on screen to say why.
    pc.decide('keep');
    eq('decisions untouched', pc.photos.map(p => p.decision), ['delete', 'delete', 'delete']);
    eq('index untouched', pc.index, 3);
    eq('undo stack untouched', pc.decisionStack, [0, 1, 2]);
  });

  await test('undo inside the animation window is not undone by the pending advance', async () => {
    const res = await pc.validateSelection(await goodExport(4));
    await pc.startSession(res.entries, res.manifest);
    pc.decide('delete');
    pc.undo();                            // before the 290ms settle fires
    eq('decision cleared', pc.photos[0].decision, null);
    eq('back on the first photo', pc.index, 0);
    await new Promise(r => setTimeout(r, 400));
    eq('still on the first photo after the window closes', pc.index, 0);
    eq('still cleared', pc.photos[0].decision, null);
  });

  await test('a decision still in flight does not leak into the next session', async () => {
    const first = await pc.validateSelection(await goodExport(4));
    await pc.startSession(first.entries, first.manifest);
    pc.decide('delete');                  // deliberately left mid-animation
    // Loading another export now — "Select new photos", or just a second folder —
    // used to let the pending advance run against the new photos array, moving the
    // index by a number computed for photos that were no longer loaded.
    const second = await pc.validateSelection(await goodExport(3));
    await pc.startSession(second.entries, second.manifest);
    eq('new session starts at the first photo', pc.index, 0);
    eq('nothing decided', pc.photos.map(p => p.decision), [null, null, null]);
    await new Promise(r => setTimeout(r, 400));
    eq('and the old timer never fires into it', pc.index, 0);
    eq('still nothing decided', pc.photos.map(p => p.decision), [null, null, null]);
    eq('undo stack is empty', pc.decisionStack, []);
  });

  await test('the delete string never contains an undecided photo', async () => {
    const res = await pc.validateSelection(await goodExport(5));
    await pc.startSession(res.entries, res.manifest);
    pc.decide('delete');                  // 1
    pc.decide('keep');                    // 2
    pc.decide('delete');                  // 3
    pc.settleNow();
    eq('only the two deletes', pc.buildInput(), '1,3');
    eq('4 and 5 are still undecided', pc.photos.slice(3).map(p => p.decision), [null, null]);
  });

  // ── The string that goes to Shortcuts ────────────────────────────────────

  await test('the shortcut input carries the keep list, not just the deletes', async () => {
    const res = await pc.validateSelection(await goodExport(5));
    await pc.startSession(res.entries, res.manifest);
    pc.decide('delete');                  // 1
    pc.decide('keep');                    // 2
    pc.decide('delete');                  // 3
    pc.decide('album');                   // 4  — starred is kept, not deleted
    pc.decide('keep');                    // 5
    pc.settleNow();
    eq('deletes on the left', pc.buildInput(), '1,3');
    eq('keeps and stars on the right', pc.buildKeepInput(), '2,4,5');
    eq('combined', pc.buildShortcutInput(), '1,3|2,4,5');
    // What is actually sent, not just what the helper can produce. The keep list is
    // the whole fix; a backlog batch that ships without it puts the shortcut back to
    // inferring the keeps from the album, which is the 2026-09-19 failure.
    eq('and that is what gets sent', pc.deleteShortcutInput(), '1,3|2,4,5');
    // Every index appears exactly once across the two lists, or the shortcut either
    // misses a photo or marks one it deleted.
    const all = pc.buildShortcutInput().split('|').flatMap(x => x ? x.split(',') : []);
    eq('every position accounted for once', all.map(Number).sort((a, b) => a - b),
       [1, 2, 3, 4, 5]);
  });

  await test('an all-keep batch still sends something to mark', async () => {
    const res = await pc.validateSelection(await goodExport(3));
    await pc.startSession(res.entries, res.manifest);
    pc.decide('keep'); pc.decide('keep'); pc.decide('keep');
    pc.settleNow();
    // This used to be a second shortcut that only ran when the delete pile was empty,
    // and so had never run once. Now it is the same call with an empty left side.
    eq('empty delete side', pc.deleteShortcutInput(), '|1,2,3');
    eq('same shortcut as always', pc.deleteShortcutName(), 'Photo Curator Delete');
  });

  await test('an undecided photo is in neither list', async () => {
    const res = await pc.validateSelection(await goodExport(4));
    await pc.startSession(res.entries, res.manifest);
    pc.decide('delete');
    pc.decide('keep');
    pc.settleNow();
    eq('only what was decided', pc.deleteShortcutInput(), '1|2');
    // Marking an undecided photo as triaged would retire it without it ever having
    // been looked at, which is the silent version of losing it.
    check('3 and 4 are absent', !/3|4/.test(pc.deleteShortcutInput()), pc.deleteShortcutInput());
  });

  await test('a hand-picked batch never reaches the backlog shortcut', async () => {
    const files = await goodExport(3, { album: 'Triage Manual' });
    const res = await pc.validateSelection(files);
    await pc.startSession(res.entries, res.manifest);
    pc.decide('delete'); pc.decide('keep'); pc.decide('delete');
    pc.settleNow();
    check('recognised as manual', pc.isManualBatch(), 'manifest album was ' + pc.manifest.album);
    eq('its own shortcut', pc.deleteShortcutName(), 'Photo Curator Delete Manual');
    // Positions counted in Triage Manual mean nothing in Triage. Sending the pair
    // format to the backlog shortcut would resolve them against the wrong album, and
    // would mark hand-picked photos as triaged on top of that.
    eq('plain index list, no keep side', pc.deleteShortcutInput(), '1,3');
    check('no separator', !pc.deleteShortcutInput().includes('|'), pc.deleteShortcutInput());
  });

  await test('a backlog batch is recognised as one', async () => {
    const res = await pc.validateSelection(await goodExport(2));
    await pc.startSession(res.entries, res.manifest);
    check('not manual', !pc.isManualBatch(), 'album was ' + pc.manifest.album);
    eq('backlog shortcut', pc.deleteShortcutName(), 'Photo Curator Delete');
  });

  await test('photos picked from the library are rejected with the manual route offered', async () => {
    // Exactly what iOS hands the page when "Photo Library" is chosen in the picker:
    // media, no manifest, no index in any name.
    const res = await pc.validateSelection([
      await photoFile('IMG_4021.HEIC'),
      await photoFile('IMG_4022.HEIC'),
    ]);
    check('rejected', !!res.errors, 'expected rejection');
    check('offers the manual route', res.manualHint === true, JSON.stringify(res.errors));
    check('says why, in one message', res.errors.length === 1, JSON.stringify(res.errors));
    check('mentions deletion safety', /delete/i.test(res.errors[0]), res.errors[0]);
  });

  await test('a real export is never mistaken for a library pick', async () => {
    const res = await pc.validateSelection(await goodExport(3));
    check('accepted', !res.errors, errorText(res));
    const noManifest = (await goodExport(3)).filter(f => f.name !== 'manifest.json');
    const res2 = await pc.validateSelection(noManifest);
    check('missing manifest still rejected', !!res2.errors, 'expected rejection');
    check('but not as a library pick', !res2.manualHint, 'wrongly offered the manual route');
  });

  await test('every batch sent to Shortcuts is written to the log', async () => {
    localStorage.removeItem('batchLog');
    const res = await pc.validateSelection(await goodExport(4));
    await pc.startSession(res.entries, res.manifest);
    pc.decide('delete'); pc.decide('keep'); pc.decide('delete'); pc.decide('album');
    pc.settleNow();
    const entry = pc.logBatch('delete');
    eq('what was deleted', entry.deleted, [1, 3]);
    eq('what was kept', entry.kept, [2, 4]);
    eq('nothing left over', entry.undecided, []);
    eq('the exact string sent', entry.input, '1,3|2,4');
    eq('which shortcut', entry.shortcut, 'Photo Curator Delete');
    eq('which album the positions mean', entry.album, 'Triage');
    const log = pc.readLog();
    eq('one entry', log.length, 1);
    eq('round-trips through storage', log[0].input, '1,3|2,4');
  });

  await test('the manual route is reachable and explains itself', async () => {
    document.getElementById('btn-manual-help').click();
    eq('shows the manual screen', pc.activeScreen(), 'manual');
    const body = document.getElementById('screen-manual').textContent;
    check('names the shortcut to run', /Photo Curator Export Selected/.test(body), body.slice(0, 200));
    check('says the backlog is untouched', /Triage Manual/.test(body), body.slice(0, 200));
    // The copy wraps across lines in the markup, so normalise before matching.
    const flat = body.replace(/\s+/g, ' ');
    check('explains why not an in-app picker', /filenames are not unique/i.test(flat), flat.slice(0, 300));
    document.getElementById('btn-manual-back').click();
    eq('back to landing', pc.activeScreen(), 'landing');
  });

  await test('an export of nothing is good news, not a broken folder', async () => {
    // What the 18:00 automation writes on a day with nothing left to triage. Verified
    // against the real Shortcuts behaviour by tools/probe_empty_album.py: First Item
    // and Get Name survive an empty album, so the run completes with count 0.
    const res = await pc.validateSelection([
      manifestFile({ album: 'Triage', count: 0, first: '', last: '',
                     exportedAt: '2026-09-20T18:00:00Z' }),
    ]);
    check('not an error', !res.errors, errorText(res));
    check('recognised as empty', res.emptyExport === true, JSON.stringify(res));
  });

  await test('an empty export is not a way past the guard', async () => {
    // The friendly path must depend on the manifest actually saying zero. A folder
    // whose media failed to sync says count 5 with nothing there, and that is the
    // dangerous case the guard exists for — it must still be rejected outright.
    const res = await pc.validateSelection([
      manifestFile({ album: 'Triage', count: 5, first: 'IMG_1.HEIC', last: 'IMG_5.HEIC',
                     exportedAt: 'x' }),
    ]);
    check('rejected', !!res.errors, 'expected rejection');
    check('not treated as empty', !res.emptyExport, 'wrongly waved through as empty');
    check('says the count disagrees', /counts 5/.test(errorText(res)), errorText(res));

    // And a count-0 manifest that arrives with media anyway is a contradiction, not
    // an empty export.
    const res2 = await pc.validateSelection([
      await photoFile('1_IMG_1001.HEIC.jpg'),
      manifestFile({ album: 'Triage', count: 0, first: '', last: '', exportedAt: 'x' }),
    ]);
    check('contradiction rejected', !!res2.errors, 'expected rejection');
    check('not treated as empty', !res2.emptyExport, 'wrongly waved through as empty');
  });

  const failed = results.filter(r => !r.pass);
  return {
    total: results.length,
    passed: results.length - failed.length,
    failed: failed.length,
    failures: failed,
  };
}
