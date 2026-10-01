'use strict';
// Use an existing authenticated Playwright page. No browser package is required here.
const fs = require('node:fs');
const path = require('node:path');
const probeSource = fs.readFileSync(path.join(__dirname, 'chart-probe.js'), 'utf8');
async function measure(page, {width = 390, height = 844, mobile = true, timeout = 30000} = {}) {
  if (![width, height, timeout].every((value) => Number.isInteger(value) && value > 0)
    || timeout > 120000 || typeof mobile !== 'boolean') throw new Error('Invalid measurement bounds');
  const url = page.url();
  const target = await page.context().newPage();
  try {
    return await measurePage(target, {width, height, mobile, timeout}, url);
  } finally {
    await target.close();
  }
}
async function measurePage(page, {width, height, mobile, timeout}, url) {
  await page.setViewportSize({width, height});
  await page.addInitScript({content: probeSource +
    '\nwindow.chartProbe = window.chartProbe || window.ChartMeasurement.install(window);'});
  let cdp = null, baseline = null, threadCpu = false;
  const metrics = async () => {
    const response = await cdp.send('Performance.getMetrics');
    const allowed = new Set(['TaskDuration', 'JSHeapUsedSize', 'JSHeapTotalSize']);
    return Object.fromEntries(response.metrics.filter(({name, value}) => allowed.has(name)
      && Number.isFinite(value) && value >= 0).map(({name, value}) => [name, value]));
  };
  let result;
  try {
    try {
      cdp = await page.context().newCDPSession(page);
      if (mobile) await cdp.send('Emulation.setDeviceMetricsOverride',
        {width, height, deviceScaleFactor: 1, mobile: true});
      try {
        await cdp.send('Performance.enable', {timeDomain: 'threadTicks'});
        threadCpu = true;
      } catch {await cdp.send('Performance.enable', {timeDomain: 'timeTicks'});}
    } catch {
      if (cdp) {
        if (mobile) await cdp.send('Emulation.clearDeviceMetricsOverride').catch(() => {});
        await cdp.detach().catch(() => {});
      }
      cdp = null;
    }
    await page.goto(url, {waitUntil: 'domcontentloaded', timeout});
    if (cdp) baseline = await metrics().catch(() => null);
    let ready = true;
    try {
      await page.waitForFunction(() => window.chartProbe?.report().first_content_ms !== null
        && window.chartProbe?.report().first_content_ms !== undefined, null, {timeout});
    } catch {ready = false;}
    const settled = async () => page.waitForFunction(() => {
      const report = window.chartProbe.report();
      const requests = report.requests.filter((row) => row.action !== 'event_history_wait_update');
      return requests.every((row) => row.status !== 'pending') && requests.every((row) =>
        performance.now() - (row.start_ms + (row.body_ms ?? 0)) >= 150);
    }, null, {timeout});
    if (ready) {
      await settled().catch(() => {ready = false;});
    }
    if (ready) {
      for (const id of ['chart-zoom-in', 'chart-previous']) {
        const before = await page.evaluate(() => window.chartProbe.report().interactions.length);
        await page.locator('#' + id).click({timeout});
        try {
          await page.waitForFunction((count) => {
            const rows = window.chartProbe.report().interactions;
            return rows.length > count && rows[count].status === 'completed';
          }, before, {timeout});
        } catch { /* Report the bounded failure, never an invented latency. */ }
        await settled().catch(() => {ready = false;});
      }
    }
    result = await page.evaluate(() => ({...window.chartProbe.stop(),
      status_clear: document.getElementById('chart-status')?.textContent.trim() === ''}));
    for (const row of result.interactions) if (row.status === 'pending') row.status = 'timed_out';
    result.ready = ready;
    const view = result.viewport;
    result.viewport_exact = view.width === width && view.height === height
      && view.visual_width === width && view.visual_height === height && view.visual_scale === 1;
    result.requested_viewport = {width, height};
    if (cdp && baseline) {
      try {
      const last = await metrics();
      const delta = last.TaskDuration - baseline.TaskDuration;
      result.cpu = threadCpu && Number.isFinite(delta) && delta >= 0 ? {
        renderer_thread_cpu_ms: delta * 1000, scope: 'domcontentloaded_to_end'} : null;
      result.heap = Number.isFinite(last.JSHeapUsedSize) && Number.isFinite(last.JSHeapTotalSize)
        ? {used_bytes: last.JSHeapUsedSize, total_bytes: last.JSHeapTotalSize} : null;
      } catch {result.cpu = null; result.heap = null;}
    }
    result.accepted = ready && result.status_clear && result.viewport_exact && result.dropped === 0
      && result.interactions.length === 2 && result.interactions.every((row) =>
        row.status === 'completed' && row.trusted && row.visible)
      && result.requests.filter((row) => row.action !== 'event_history_wait_update')
        .every((row) => row.status === 'completed');
    return result;
  } finally {
    await page.evaluate(() => window.chartProbe?.stop()).catch(() => {});
    if (cdp) {
      if (mobile) await cdp.send('Emulation.clearDeviceMetricsOverride').catch(() => {});
      await cdp.detach().catch(() => {});
    }
  }
}
function bundle({width = 390, height = 844, mobile = true, timeout = 30000} = {}) {
  return 'async (page) => { const probeSource = ' + JSON.stringify(probeSource)
    + '; const measurePage = ' + measurePage.toString()
    + '; const measure = ' + measure.toString() + '; return await measure(page, '
    + JSON.stringify({width, height, mobile, timeout}) + '); }';
}
if (require.main === module && process.argv[2] === '--bundle') console.log(bundle());
module.exports = {measure, bundle};
