window.McpEventHistoryApi = (() => {
  const request = async (action, fields = {}, timeoutMs = 45000) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    const body = new URLSearchParams({action, ...fields});
    try {
      const response = await fetch('event_history.cgi', {
        method: 'POST', body, signal: controller.signal,
        headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      const result = await response.json();
      if (!response.ok || !result.ok) {
        const error = new Error(result.error?.message || 'Request failed');
        error.code = result.error?.code || 'request_failed';
        error.requestId = result.error?.request_id || null;
        throw error;
      }
      return result.data;
    } catch (error) {
      if (error.name === 'AbortError') {
        const timeout = new Error('Request timed out');
        timeout.code = 'outcome_unknown';
        throw timeout;
      }
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  };
  const subscribeUpdates = (onChange, onUnavailable) => {
    let stopped = false;
    let token = '';
    const visible = () => new Promise((resolve) => {
      const resume = () => {
        if (document.hidden) return;
        document.removeEventListener('visibilitychange', resume);
        resolve();
      };
      document.addEventListener('visibilitychange', resume);
      resume();
    });
    const pause = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve,
      milliseconds));
    void (async () => {
      while (!stopped) {
        if (document.hidden) await visible();
        if (stopped) break;
        try {
          const update = await request('event_history_wait_update', {token}, 30000);
          if (update.availability !== 'available' || !/^[0-9a-f]{16}$/.test(update.token)) {
            throw new Error('Recorder updates unavailable');
          }
          token = update.token;
          if (update.changed && !document.hidden) onChange();
        } catch {
          if (!document.hidden) onUnavailable();
          await pause(10000);
        }
      }
    })();
    return () => { stopped = true; };
  };
  return {request, subscribeUpdates};
})();
