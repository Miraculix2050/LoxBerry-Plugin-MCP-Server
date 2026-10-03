'use strict';
// Synthetic browser comparison only: no target writes or backend timing claims.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');

async function measure(page, assets) {
  const reports = [];
  for (const width of [1280, 390]) {
    for (const language of ['en', 'de']) {
      for (const dense of [false, true]) {
        const tab = await page.context().newPage();
        await tab.setViewportSize({width, height: width === 390 ? 844 : 800});
        let total = dense ? 4000 : 24;
        const now = Math.floor(Date.now() / 1000), calls = [], errors = [];
        const sources = [1, 2].map((index) => ({
          control_uuid: `00000000-0000-0000-${String(index).padStart(16, '0')}`,
          state_uuid: `10000000-0000-0000-${String(index).padStart(16, '0')}`}));
        tab.on('pageerror', (error) => errors.push(error.name));
        tab.on('console', (message) => { if (message.type() === 'error') errors.push('console_error'); });
        await tab.route('https://fixture371.test/**', async (route) => {
          const url = new URL(route.request().url());
          if (url.pathname !== '/event_history.cgi') {
            return route.fulfill({contentType: 'text/html', body: assets.html[language]});
          }
          const fields = new URLSearchParams(route.request().postData());
          let data;
          if (fields.get('action') === 'event_history_chart_prepare') {
            data = {generation: 'a'.repeat(24), history_generation: 1, verified_at: now,
              sources: sources.map((source, index) => ({...source, control_name: `Synthetic ${index}`,
                state_name: 'Value', room: 'Fixture', category: 'Fixture', control_type: 'Number'}))};
          } else {
            const queries = JSON.parse(fields.get('queries'));
            data = {results: queries.map((query) => {
              const primary = query.state_uuid === sources[0].state_uuid;
              const count = primary ? total : 24;
              const event = (id) => ({id, observed_at: now - 60000 + id * 10,
                new_value: Math.sin(id / 20)});
              const eligible = Array.from({length: count}, (_, index) => index + 1)
                .filter((id) => event(id).observed_at >= query.start
                  && event(id).observed_at <= query.end);
              const reduced = query.after_id === 0 && eligible.length > 4000;
              const remaining = eligible.filter((id) => id > query.after_id);
              const ids = reduced ? eligible.filter((_id, index) => index % 16 === 0
                || index === eligible.length - 1) : remaining.slice(0, 500);
              return {events: ids.map(event), generation: 1, reduced,
                has_more: !reduced && remaining.length > 500,
                latest_id: eligible.at(-1) || 0, next_id: ids.at(-1) || query.after_id,
                coverage: [{started_at: now - 86400, ended_at: null, outcome: 'recording'}],
                capture_started_at: now - 86400, retained_from: now - 86400,
                recording_ended_at: null};
            })};
          }
          const body = JSON.stringify({ok: true, data});
          calls.push({action: fields.get('action'), bytes: body.length,
            sources: data.results?.length || 0});
          await tab.waitForTimeout(15);
          await route.fulfill({contentType: 'application/json', body});
        });
        try {
          const start = Date.now();
          await tab.goto('https://fixture371.test/?sources=' + encodeURIComponent(JSON.stringify(sources)));
          const settled = async () => {
            await tab.waitForFunction(() => window.fixtureActive === 0
              && document.querySelectorAll('.uplot').length === 2
              && !document.getElementById('chart-status').textContent);
            await tab.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
          };
          await settled();
          const initial = {ms: Date.now() - start, requests: calls.length,
            bytes: calls.reduce((sum, row) => sum + row.bytes, 0)};
          const updates = [];
          for (let index = 0; index < 5; index++) {
            total++;
            const offset = calls.length, started = Date.now();
            await tab.evaluate(() => window.fixtureTick());
            await settled();
            updates.push({ms: Date.now() - started, requests: calls.length - offset,
              bytes: calls.slice(offset).reduce((sum, row) => sum + row.bytes, 0),
              sources: calls.slice(offset).map((row) => row.sources)});
          }
          const updateUi = await tab.evaluate(() => ({
            destroyed: window.fixtureDestroyed, emptyDraws: window.fixtureEmptyDraws,
            notices: [...document.querySelectorAll('#chart-panels p[role="status"]')].map((el) => el.textContent)}));
          const interactions = [];
          for (const id of ['chart-zoom-in', 'chart-previous']) {
            const started = Date.now();
            await tab.locator('#' + id).click(); await settled();
            interactions.push({action: id, ms: Date.now() - started});
          }
          const ui = await tab.evaluate(() => {
            const host = document.querySelector('.mcp-history-chart-plot');
            host?.focus(); host?.dispatchEvent(new KeyboardEvent('keydown', {key: 'End', bubbles: true}));
            return {width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
              plots: document.querySelectorAll('.uplot').length,
              notices: [...document.querySelectorAll('#chart-panels p[role="status"]')].map((el) => el.textContent),
              destroyed: window.fixtureDestroyed,
              emptyDraws: window.fixtureEmptyDraws,
              keyboard: [...document.querySelectorAll('[aria-live="polite"]')].some((el) => el.textContent)};
          });
          reports.push({width, language, dense, initial, updates, updateUi, interactions, ui, errors});
        } catch (error) {
          reports.push({width, language, dense, failed: error.name, calls: calls.length,
            errors, diagnostic: await tab.evaluate(() => ({active: window.fixtureActive,
              plots: document.querySelectorAll('.uplot').length,
              status: document.getElementById('chart-status')?.textContent}))});
          return reports;
        } finally { await tab.close(); }
      }
    }
  }
  return reports;
}

function bundle({charts, cache} = {}) {
  const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
  const template = read('templates/event-history-charts.html');
  const assets = {html: {}};
  for (const lang of ['de', 'en']) {
    const strings = Object.fromEntries(read(`templates/lang/language_${lang}.ini`).split(/\r?\n/)
      .filter((line) => /^[A-Z_]+=/.test(line)).map((line) => {
        const index = line.indexOf('='); return [line.slice(0, index), line.slice(index + 1)];
      }));
    let html = template.replace(/<TMPL_VAR ([^ >]+)[^>]*>/g, (_match, key) =>
      (strings[key.replace('EVENT_HISTORY.', '')] || 'Fixture').replaceAll('&', '&amp;').replaceAll('"', '&quot;'))
      .replace(/<link[^>]+>/g, '').replace(/<script[^>]*>[\s\S]*?<\/script>/g, '');
    const init = `window.fixtureActive=0;window.fixtureDestroyed=0;window.fixtureEmptyDraws=0;
      window.McpEventHistoryApi={request:async(action,fields)=>{window.fixtureActive++;
        try{const response=await fetch('/event_history.cgi',{method:'POST',body:new URLSearchParams({action,...fields})});
          return (await response.json()).data;}finally{window.fixtureActive--; }},
        subscribeUpdates:(callback)=>{window.fixtureTick=callback;}};
      const Original=uPlot;window.uPlot=class extends Original {
        constructor(...args){super(...args);const destroy=this.destroy.bind(this),setData=this.setData.bind(this);
          this.destroy=()=>{window.fixtureDestroyed++;return destroy();};
          this.setData=(data,...rest)=>{if(!data[0]?.length)window.fixtureEmptyDraws++;return setData(data,...rest);};}};`;
    assets.html[lang] = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
      + '<style>' + ['webfrontend/htmlauth/mcp-ui.css', 'webfrontend/htmlauth/event-history/charts.css',
        'webfrontend/htmlauth/event-history/vendor/uplot/uPlot.min.css'].map(read).join('\n') + '</style>'
      + html + '<script>' + read('webfrontend/htmlauth/event-history/vendor/uplot/uPlot.iife.min.js') + '</script>'
      + '<script>' + init + '</script><script>' + (cache || read('webfrontend/htmlauth/event-history/chart-cache.js'))
      + '</script><script>' + (charts || read('webfrontend/htmlauth/event-history/charts.js')) + '</script>';
  }
  return `async (page) => {const assets=${JSON.stringify(assets)}; return (${measure.toString()})(page,assets);}`;
}
module.exports = {bundle};
