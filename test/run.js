#!/usr/bin/env node
//
// Headless runner for test/suite.js.
//
//     node test/run.js            # all of it
//     node test/run.js burst      # only tests whose name matches /burst/i
//     node test/run.js --head     # watch it happen in a real window
//
// The suite already ran the real page's real functions — what it did not have was a
// way to run without a human opening a browser, pasting an import into the console
// and reading a table. A suite you have to *decide* to run is a suite that gets run
// after the bug, not before it.
//
// No dependencies, deliberately, because this repo has none and adding a browser
// automation framework to a 3000-line HTML file is the wrong trade. Chrome is already
// on the machine and speaks CDP over a WebSocket; Node 22 has a WebSocket client
// built in. That is the whole runner.

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const CHROME = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
].find(p => fs.existsSync(p));

const TYPES = {
  '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json',
  '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml',
};

function serve() {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '');
    const file = path.join(ROOT, rel || 'index.html');
    // Everything is served from the repo; refuse anything that climbs out of it.
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404).end('not found');
      return;
    }
    res.writeHead(200, {
      'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream',
      'Cache-Control': 'no-store',
    });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server)));
}

// Chrome with --remote-debugging-port=0 picks a free port and writes it into the
// profile directory. Polling that file is more reliable than scraping stderr.
function devtoolsPort(profile, timeoutMs = 15000) {
  const file = path.join(profile, 'DevToolsActivePort');
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    (function poll() {
      if (fs.existsSync(file)) {
        const first = fs.readFileSync(file, 'utf8').split('\n')[0].trim();
        if (first) return resolve(Number(first));
      }
      if (Date.now() > deadline) return reject(new Error('Chrome never reported a debugging port'));
      setTimeout(poll, 50);
    })();
  });
}

function get(url) {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let body = '';
      res.on('data', d => (body += d));
      res.on('end', () => resolve(JSON.parse(body)));
    }).on('error', reject);
  });
}

// Minimal CDP client: send a command, resolve on the matching id, surface events.
function cdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  const pending = new Map();
  const listeners = [];
  let nextId = 1;
  ws.addEventListener('message', ev => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method) {
      listeners.forEach(fn => fn(msg));
    }
  });
  const ready = new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', () => reject(new Error('could not connect to Chrome')));
  });
  return {
    ready,
    on: fn => listeners.push(fn),
    send(method, params = {}, sessionId) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params, sessionId }));
      });
    },
    close: () => ws.close(),
  };
}

async function main() {
  const args = process.argv.slice(2);
  const headed = args.includes('--head');
  const filter = args.find(a => !a.startsWith('--')) || '';

  if (!CHROME) {
    console.error('No Chrome/Chromium/Edge found. Install one, or run the suite by hand:');
    console.error('  python3 -m http.server 8765   then open index.html?test=1');
    process.exit(2);
  }

  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}`;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'pc-test-'));

  const chrome = spawn(CHROME, [
    headed ? '--auto-open-devtools-for-tabs' : '--headless=new',
    '--remote-debugging-port=0',
    `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    // Video autoplay and canvas decoding are part of what the suite exercises.
    '--autoplay-policy=no-user-gesture-required',
    'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'] });

  let failed = true;
  try {
    const port = await devtoolsPort(profile);
    const version = await get(`http://127.0.0.1:${port}/json/version`);
    const client = cdp(version.webSocketDebuggerUrl);
    await client.ready;

    const { targetId } = await client.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await client.send('Target.attachToTarget', { targetId, flatten: true });

    // Surface whatever the page says. An uncaught exception in the app is itself a
    // test failure — the glitch that started all this was exactly that, and it was
    // invisible because nobody was looking at a console.
    const pageErrors = [];
    client.on(msg => {
      if (msg.params && msg.params.sessionId !== sessionId) return;
      if (msg.method === 'Runtime.consoleAPICalled') {
        const text = (msg.params.args || []).map(a => a.value ?? a.description ?? '').join(' ');
        if (msg.params.type === 'error') pageErrors.push(text);
        else if (process.env.PC_VERBOSE) console.log('  page:', text);
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        pageErrors.push(d.exception?.description || d.text);
      }
    });
    await client.send('Runtime.enable', {}, sessionId);
    await client.send('Page.enable', {}, sessionId);

    await client.send('Page.navigate', { url: `${base}/index.html?test=1` }, sessionId);
    await new Promise(resolve => {
      const done = msg => { if (msg.method === 'Page.loadEventFired') resolve(); };
      client.on(done);
    });

    const expr = `(async () => {
      const m = await import('${base}/test/suite.js?v=' + Date.now());
      return JSON.stringify(await m.run(${JSON.stringify(filter)}));
    })()`;
    const res = await client.send(
      'Runtime.evaluate',
      { expression: expr, awaitPromise: true, returnByValue: true },
      sessionId,
    );
    if (res.exceptionDetails) {
      throw new Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text);
    }

    const out = JSON.parse(res.result.value);
    for (const f of out.failures) {
      console.log(`FAIL  ${f.test} — ${f.label}`);
      if (f.detail) console.log(`        ${f.detail}`);
    }
    if (pageErrors.length) {
      console.log('');
      for (const e of pageErrors) console.log(`PAGE ERROR  ${e.split('\n')[0]}`);
    }
    console.log('');
    const bad = out.failed > 0 || pageErrors.length > 0;
    console.log(`${bad ? 'FAILED' : 'ok'}  ${out.passed}/${out.total} checks passed` +
                (filter ? ` (filter: ${filter})` : '') +
                (pageErrors.length ? `, ${pageErrors.length} page error(s)` : ''));
    failed = bad;
    client.close();
  } catch (err) {
    console.error('runner error:', err.message);
  } finally {
    // Chrome keeps writing to the profile for a moment after SIGTERM, so removing it
    // immediately races and throws ENOTEMPTY over a green run. Wait for the exit, and
    // treat a leftover temp profile as not worth failing a test run over.
    const exited = new Promise(resolve => chrome.once('exit', resolve));
    chrome.kill();
    await Promise.race([exited, new Promise(r => setTimeout(r, 3000))]);
    server.close();
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  }
  process.exit(failed ? 1 : 0);
}

main();
