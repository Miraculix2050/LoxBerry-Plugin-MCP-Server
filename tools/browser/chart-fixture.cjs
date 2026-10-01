'use strict';
// Loopback-only synthetic transport for the actual shipped chart scripts/uPlot.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const assets = new Map([
  ['/probe.js', path.join(__dirname, 'chart-probe.js')],
  ...['api.js', 'charts.js', 'charts.css', 'vendor/uplot/uPlot.iife.min.js', 'vendor/uplot/uPlot.min.css']
    .map((name) => ['/' + name, path.join(root, 'webfrontend/htmlauth/event-history', name)]),
  ['/mcp-ui.css', path.join(root, 'webfrontend/htmlauth/mcp-ui.css')],
]);
const source = (index) => ({control_uuid: `00000000-0000-0000-${String(index).padStart(16, '0')}`,
  state_uuid: `10000000-0000-0000-${String(index).padStart(16, '0')}`});
function events(query, dense, now) {
  const start = now - 172800, total = dense ? 100000 : 24, step = 172800 / total;
  const first = Math.max(1, Math.ceil((query.start - start) / step), Number(query.after_id) + 1);
  const last = Math.min(total, Math.floor((query.end - start) / step));
  const count = Math.max(0, last - first + 1), size = Math.min(count, 2000);
  return {events: Array.from({length: size}, (_, index) => {
    const id = size === 1 ? first : first + Math.floor(index * (count - 1) / (size - 1));
    return {id, observed_at: start + id * step, old_value: 0, new_value: Math.sin(id / 20)};
  }), reduced: count > size, has_more: false, latest_id: total, next_id: last,
  generation: 1, coverage: [{started_at: start, ended_at: now}],
  capture_started_at: start, retained_from: start,
  recording_ended_at: null};
}
function createServer() {
  const now = Date.now() / 1000;
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    res.setHeader('Cache-Control', 'no-store');
    if (req.method === 'GET' && assets.has(url.pathname)) {
      res.setHeader('Content-Type', url.pathname.endsWith('.css') ? 'text/css' : 'text/javascript');
      return res.end(fs.readFileSync(assets.get(url.pathname)));
    }
    if (req.method === 'GET' && url.pathname === '/') {
      const count = Number(url.searchParams.get('count') || 1);
      if (![1, 2, 3, 4].includes(count)) {res.statusCode = 400; return res.end();}
      const selected = Array.from({length: count}, (_, index) => source(index + 1));
      let html = fs.readFileSync(path.join(root, 'templates/event-history-charts.html'), 'utf8')
        .replace(/<TMPL_VAR [^>]*>/g, 'Fixture').replaceAll('event-history/', '')
        .replace(/\?v=[^" ]*/g, '');
      html = '<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">' +
        '<link rel="stylesheet" href="mcp-ui.css"><script src="probe.js"></script>' +
        '<script>window.chartProbe=window.chartProbe||ChartMeasurement.install(window);' +
        'sessionStorage.removeItem("mcp-event-history-chart-v1");history.replaceState(null,"",' +
        JSON.stringify('/?case=' + (url.searchParams.get('case') === 'dense' ? 'dense' : 'sparse')
          + '&count=' + count + '&view=charts&sources=' + encodeURIComponent(JSON.stringify(selected))) +
        ');</script>' + html;
      res.setHeader('Content-Type', 'text/html'); return res.end(html);
    }
    if (req.method === 'POST' && url.pathname === '/event_history.cgi') {
      let body = '';
      for await (const chunk of req) {
        body += chunk;
        if (body.length > 16384) {res.statusCode = 413; return res.end();}
      }
      const fields = new URLSearchParams(body), action = fields.get('action');
      try {
        let data;
        if (action === 'event_history_chart_prepare') {
          const sources = JSON.parse(fields.get('sources'));
          if (!Array.isArray(sources) || sources.length > 4) throw new Error();
          data = {generation: 'a'.repeat(24), history_generation: 1, verified_at: Date.now() / 1000,
            sources: sources.map((item) => ({...item, control_name: 'Synthetic', state_name: 'Value',
              room: 'Fixture', category: 'Fixture', control_type: 'Number'}))};
        } else if (action === 'event_history_chart_query') {
          const queries = JSON.parse(fields.get('queries'));
          if (!Array.isArray(queries) || queries.length > 4) throw new Error();
          const dense = new URL(req.headers.referer || '/', 'http://127.0.0.1').searchParams.get('case') === 'dense';
          data = {results: queries.map((query) => events(query, dense, now))};
        } else if (action === 'event_history_wait_update') {
          await new Promise((resolve) => setTimeout(resolve, 1000));
          data = {availability: 'available', token: 'a'.repeat(16), changed: false};
        } else {res.statusCode = 403; return res.end('{}');}
        res.setHeader('Content-Type', 'application/json'); return res.end(JSON.stringify({ok: true, data}));
      } catch {res.statusCode = 400; return res.end('{"ok":false}');}
    }
    res.statusCode = 404; res.end();
  });
}
if (require.main === module) {
  const port = Number(process.argv[2] || 8766);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid port');
  createServer().listen(port, '127.0.0.1', () => console.log('Synthetic chart fixture ready'));
}
module.exports = {createServer, events};
