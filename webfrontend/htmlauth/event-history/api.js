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
  return {request};
})();
