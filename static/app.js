let currentState = null;
let isOperating = false;

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) throw new Error('Status fetch failed');
    const data = await res.json();
    updateUI(data);
  } catch (err) {
    console.error(err);
    document.getElementById('status-title').textContent = 'Backend Offline';
    document.getElementById('status-desc').textContent = 'Cannot reach local controller on 127.0.0.1:5350';
    document.getElementById('status-badge').textContent = 'DISCONNECTED';
    document.getElementById('status-dot').className = 'status-dot';
    document.getElementById('toggle-btn').disabled = true;
  }
}

function updateUI(data) {
  currentState = data;
  if (isOperating) return;

  const dot = document.getElementById('status-dot');
  const title = document.getElementById('status-title');
  const desc = document.getElementById('status-desc');
  const badge = document.getElementById('status-badge');
  const btn = document.getElementById('toggle-btn');
  const btnIcon = document.getElementById('btn-icon');
  const btnText = document.getElementById('btn-text');

  document.getElementById('val-interface').textContent = data.interface || 'None';
  document.getElementById('val-dns').textContent = (data.current_dns && data.current_dns.length > 0) ? data.current_dns.join(', ') : 'Standard DHCP';

  // Dynamic VPS target display (token masked by backend)
  const vtEl = document.getElementById('val-vps-target');
  if (vtEl) vtEl.textContent = data.vps_target || 'Not Configured';

  if (!data.is_configured) {
    dot.className = 'status-dot inactive';
    title.textContent = 'Setup Required';
    desc.textContent = 'No AdGuard DoH endpoint configured. Click ⚙️ Settings above to configure.';
    badge.textContent = 'NOT CONFIGURED';
    badge.style.color = '#f39c12';
    btn.className = 'btn btn-primary';
    btnIcon.textContent = '⚙️';
    btnText.textContent = 'Configure Endpoint';
    btn.onclick = openSettings;
    btn.disabled = false;
  } else if (data.state === 'ACTIVE') {
    dot.className = 'status-dot active';
    title.textContent = 'VPS AdGuard Blocker Active';
    desc.textContent = `Filtered via DoH (${data.local_stub || '127.0.2.1'}) • Fallback: ${data.fallback_dns || '1.1.1.1'}`;
    badge.textContent = 'PROTECTED 🛡️';
    badge.style.color = '#2ecc71';
    btn.className = 'btn btn-primary turn-off';
    btnIcon.textContent = '⚪';
    btnText.textContent = 'Disable VPS Blocker';
    btn.onclick = toggleDNS;
    btn.disabled = false;
  } else if (data.state === 'VPN_ACTIVE') {
    dot.className = 'status-dot vpn';
    title.textContent = 'VPN Active';
    desc.textContent = `Managed by ${data.vpn_interface || 'VPN'}. DNS is routed through VPN tunnel.`;
    badge.textContent = 'VPN MANAGED 🔒';
    badge.style.color = '#3498db';
    btn.className = 'btn btn-primary';
    btnIcon.textContent = '🔒';
    btnText.textContent = 'Controlled by VPN';
    btn.onclick = null;
    btn.disabled = true;
  } else {
    dot.className = 'status-dot inactive';
    title.textContent = 'Standard Network Active';
    desc.textContent = 'Using default Wi-Fi / DHCP network settings.';
    badge.textContent = 'STANDARD (DHCP)';
    badge.style.color = '#8b9bb4';
    btn.className = 'btn btn-primary';
    btnIcon.textContent = '🛡️';
    btnText.textContent = 'Enable VPS Blocker';
    btn.onclick = toggleDNS;
    btn.disabled = false;
  }

  // Update logs
  if (data.events) {
    const list = document.getElementById('log-list');
    list.innerHTML = data.events.map(e => `
      <div class="log-entry ${e.level}">
        <span class="log-time">[${e.time}]</span>
        <span class="log-msg">${escapeHtml(e.msg)}</span>
      </div>
    `).join('');
  }
}

function showMessage(msg, isError = false) {
  const el = document.getElementById('action-message');
  el.className = isError ? 'action-message error' : 'action-message success';
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 5000);
}

async function toggleDNS() {
  if (isOperating || !currentState) return;
  if (!currentState.is_configured) {
    openSettings();
    return;
  }
  if (currentState.state === 'VPN_ACTIVE') {
    showMessage('Cannot toggle while VPN is active.', true);
    return;
  }

  isOperating = true;
  const btn = document.getElementById('toggle-btn');
  btn.disabled = true;
  btn.querySelector('#btn-text').textContent = 'Verifying & Switching...';

  const action = (currentState.state === 'ACTIVE') ? 'disable' : 'enable';

  try {
    const res = await fetch('/api/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action })
    });
    const data = await res.json();
    showMessage(data.message, !data.ok);
  } catch (err) {
    showMessage('Error sending command to controller: ' + err.message, true);
  } finally {
    isOperating = false;
    fetchStatus();
  }
}

async function runProbeTest() {
  showMessage('Probing remote AdGuard resolver via DoH (out-of-band test)...', false);
  try {
    const res = await fetch('/api/test', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      showMessage(`✓ Probe Successful: ${data.message}`, false);
    } else {
      showMessage(`✗ Probe Failed: ${data.message}`, true);
    }
  } catch (err) {
    showMessage('Error probing VPS: ' + err.message, true);
  } finally {
    fetchStatus();
  }
}

async function emergencyReset() {
  if (!confirm('Execute 3-stage emergency reset? This will immediately restore standard DHCP DNS.')) return;
  try {
    const res = await fetch('/api/reset', { method: 'POST' });
    const data = await res.json();
    showMessage(data.message, false);
  } catch (err) {
    showMessage('Reset error: ' + err.message, true);
  } finally {
    fetchStatus();
  }
}

// Settings Modal Handling
async function openSettings() {
  const modal = document.getElementById('settings-modal');
  const msgEl = document.getElementById('modal-msg');
  msgEl.classList.add('hidden');

  try {
    const res = await fetch('/api/config');
    if (res.ok) {
      const cfg = await res.json();
      const input = document.getElementById('cfg-doh-url');
      if (cfg.is_configured && !input.value) {
        input.placeholder = cfg.doh_url_masked;
      }
    }
  } catch (err) {
    console.error('Failed to load current config', err);
  }

  modal.style.display = 'flex';
}

function closeSettings() {
  const modal = document.getElementById('settings-modal');
  if (modal) modal.style.display = 'none';
}

function handleModalClick(e) {
  if (e.target.id === 'settings-modal') {
    closeSettings();
  }
}

async function saveSettings() {
  const dohUrl = document.getElementById('cfg-doh-url').value.trim();
  const msgEl = document.getElementById('modal-msg');

  if (!dohUrl) {
    msgEl.className = 'action-message error';
    msgEl.textContent = 'Please enter a valid DoH URL.';
    msgEl.classList.remove('hidden');
    return;
  }

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doh_url: dohUrl })
    });
    const data = await res.json();
    if (data.ok) {
      msgEl.className = 'action-message success';
      msgEl.textContent = 'Configuration saved!';
      msgEl.classList.remove('hidden');
      setTimeout(() => {
        closeSettings();
        fetchStatus();
      }, 1000);
    } else {
      msgEl.className = 'action-message error';
      msgEl.textContent = data.message || 'Save failed';
      msgEl.classList.remove('hidden');
    }
  } catch (err) {
    msgEl.className = 'action-message error';
    msgEl.textContent = 'Error saving config: ' + err.message;
    msgEl.classList.remove('hidden');
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Initialize
fetch('/adguard.png').catch(() => {});
fetchStatus();
setInterval(fetchStatus, 2500);
