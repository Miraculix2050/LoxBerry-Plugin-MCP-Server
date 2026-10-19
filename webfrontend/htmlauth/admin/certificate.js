window.McpAdmin.createCertificate = (core, queueBackgroundHydration) => {
  const {label, postAjax, setSummaryBadge, parseExpiry, expiryFormatter} = core;
  const accessSection = document.getElementById('access');
  const certificateSummaryBadge = document.getElementById('certificate-summary-badge');
  const certificatePanel = document.getElementById('certificate-panel');
  const certificateDetails = document.getElementById('certificate-details');
  const certificateSource = document.getElementById('certificate-source');
  const certificateUnavailable = document.getElementById('certificate-unavailable');
  const certificateUnsupported = document.getElementById('certificate-unsupported');
  const certificateRenewalInfo = document.getElementById('certificate-renewal-info');
  const certificateRenewalForm = document.getElementById('certificate-renewal-form');
  const certificateRenewalState = document.getElementById('certificate-renewal-state');
  const certificateExpiry = document.getElementById('certificate-expiry');
  const certificateDnsCount = document.getElementById('certificate-dns-count');
  const certificateIpCount = document.getElementById('certificate-ip-count');
  const certificateOriginMatch = document.getElementById('certificate-origin-match');
  const certificateHostnameMatch = document.getElementById('certificate-hostname-match');
  const certificateWarning = document.getElementById('certificate-warning');
  let certificateLoaded = false;
  let certificateLoadInFlight = false;
  let certificateStatusVersion = 0;
  const certificateStateLabels = certificatePanel ? {
    idle: certificatePanel.dataset.stateIdle,
    scheduled: certificatePanel.dataset.stateScheduled,
    running: certificatePanel.dataset.stateRunning,
    success: certificatePanel.dataset.stateSuccess,
    error: certificatePanel.dataset.stateError,
  } : {};
  const certificateBadgeState = (certificate, nowSeconds = Date.now() / 1000) => {
    if (certificate?.available !== true) {
      return certificate?.available === false
        ? [label('SUMMARY.UNAVAILABLE'), '']
        : [label('SUMMARY.UNKNOWN'), ''];
    }
    const validUntil = certificate.expires_at;
    if (typeof certificate.origin_configured !== 'boolean'
        || typeof certificate.origin_matches !== 'boolean'
        || typeof certificate.hostname_matches !== 'boolean'
        || typeof validUntil !== 'number' || !Number.isFinite(validUntil)) {
      return [label('SUMMARY.UNKNOWN'), ''];
    }
    const checksPass = certificate.origin_configured === true
      && certificate.origin_matches === true && certificate.hostname_matches === true
      && validUntil > nowSeconds;
    return checksPass
      ? [label('SUMMARY.OK'), 'success']
      : [label('SUMMARY.WARNING'), 'error'];
  };
  const updateCertificate = (certificate) => {
    const available = Boolean(certificate?.available);
    setSummaryBadge(certificateSummaryBadge, ...certificateBadgeState(certificate));
    certificatePanel.setAttribute('aria-busy', 'false');
    certificateDetails.hidden = !available;
    certificateUnavailable.hidden = available;
    if (!available) {
      certificateUnavailable.textContent = label('CERTIFICATE.UNAVAILABLE');
      certificateUnsupported.hidden = true;
      certificateRenewalInfo.hidden = true;
      certificateRenewalForm.hidden = true;
      return;
    }
    certificateSource.textContent = certificate.source === 'loxberry_ca'
      ? label('CERTIFICATE.SOURCE_LOXBERRY')
      : label('CERTIFICATE.SOURCE_EXTERNAL');
    if (certificateDnsCount) certificateDnsCount.textContent = String(certificate.dns_san_count);
    if (certificateIpCount) certificateIpCount.textContent = String(certificate.ip_san_count);
    if (certificateOriginMatch) certificateOriginMatch.textContent = certificate.origin_configured
      ? (certificate.origin_matches ? certificatePanel.dataset.yes : certificatePanel.dataset.no)
      : certificatePanel.dataset.notConfigured;
    if (certificateHostnameMatch) certificateHostnameMatch.textContent = certificate.hostname_matches
      ? certificatePanel.dataset.yes : certificatePanel.dataset.no;
    if (certificateWarning) certificateWarning.hidden = certificate.origin_matches && certificate.hostname_matches;
    const expiresAt = parseExpiry(String(certificate.expires_at));
    if (certificateExpiry && expiresAt !== null) {
      const date = new Date(expiresAt * 1000);
      certificateExpiry.dataset.expiresAt = String(expiresAt);
      certificateExpiry.dateTime = date.toISOString();
      certificateExpiry.textContent = expiryFormatter.format(date);
    }
    const renewalState = certificate.renewal?.state || 'idle';
    certificateRenewalInfo.hidden = false;
    certificateRenewalState.textContent = certificateStateLabels[renewalState] || certificateStateLabels.error;
    certificateRenewalForm.hidden = !certificate.renewal_supported;
    certificateUnsupported.hidden = Boolean(certificate.renewal_supported);
  };
  const loadCertificateStatus = async (suppliedResult) => {
    if (certificateLoaded || certificateLoadInFlight) return;
    certificateLoadInFlight = true;
    const requestVersion = certificateStatusVersion;
    certificatePanel.setAttribute('aria-busy', 'true');
    try {
      const body = new URLSearchParams();
      body.set('action', 'certificate_status');
      body.set('ajax', '1');
      const result = await postAjax(body, 15000, suppliedResult);
      if (requestVersion !== certificateStatusVersion) return;
      updateCertificate(result.data.certificate);
      certificateLoaded = true;
    } catch {
      if (core.unloading) return;
      if (requestVersion !== certificateStatusVersion) return;
      updateCertificate(null);
      setSummaryBadge(certificateSummaryBadge, label('SUMMARY.UNKNOWN'));
      certificateUnavailable.textContent = label('AJAX.ERROR');
    } finally {
      certificateLoadInFlight = false;
      if (requestVersion !== certificateStatusVersion) {
        queueBackgroundHydration([loadCertificateStatus]);
      }
    }
  };
  const refreshCertificateAfterOriginChange = () => {
    certificateStatusVersion += 1;
    certificateLoaded = false;
    setSummaryBadge(certificateSummaryBadge, label('AJAX.WORKING'));
    queueBackgroundHydration([loadCertificateStatus]);
  };
  const pollCertificateRenewal = async (button) => {
    const deadline = Date.now() + 75000;
    try {
      while (certificateRenewalState && Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        try {
          const body = new URLSearchParams();
          body.set('action', 'certificate_status');
          body.set('ajax', '1');
          const result = await postAjax(body, 15000);
          const state = result.data.certificate?.renewal?.state || 'error';
          certificateRenewalState.textContent = certificateStateLabels[state] || certificateStateLabels.error;
          if (state === 'success' || state === 'error' || state === 'idle') {
            updateCertificate(result.data.certificate);
          }
          if (state === 'success' || state === 'error' || state === 'idle') return;
        } catch {
          // Apache restarts while the LoxBerry Core installs the new certificate.
        }
      }
      if (certificateRenewalState) certificateRenewalState.textContent = certificateStateLabels.error;
      setSummaryBadge(certificateSummaryBadge, label('SUMMARY.UNKNOWN'));
    } finally {
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  };
  const onRenewScheduled = (button) => {
    certificateRenewalState.textContent = certificateStateLabels.scheduled;
    setSummaryBadge(certificateSummaryBadge, label('AJAX.WORKING'));
    pollCertificateRenewal(button);
  };
  return {loadCertificateStatus, updateCertificate,
    refreshAfterOriginChange: refreshCertificateAfterOriginChange, onRenewScheduled};
};
