const $ = (id) => document.getElementById(id);
let dashboard = null;
const node = (tag, className, value) => {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (value !== undefined) result.textContent = value;
  return result;
};
const fmtNumber = (value) => new Intl.NumberFormat('en-US', {maximumFractionDigits: 1}).format(Number(value));
const fmtDate = (seconds) => seconds ? new Date(seconds * 1000).toLocaleString() : 'Unknown';
const duration = (seconds) => {
  if (!seconds) return 'Unknown';
  const left = Math.max(0, seconds - Date.now() / 1000);
  if (left === 0) return 'Due now';
  const days = Math.floor(left / 86400), hours = Math.floor(left % 86400 / 3600), minutes = Math.ceil(left % 3600 / 60);
  return [days ? `${days}d` : '', hours ? `${hours}h` : '', `${minutes}m`].filter(Boolean).join(' ');
};
const remaining = (window) => window?.usedPercent == null ? null : Math.max(0, Math.min(100, 100 - Number(window.usedPercent)));

function windowBlock(label, window) {
  const box = node('div', 'window');
  const top = node('div', 'window-top');
  top.append(node('span', 'window-title', label), node('span', 'remaining', remaining(window) == null ? '—' : `${fmtNumber(remaining(window))}%`));
  const meta = node('div', 'window-meta');
  meta.append(node('span', '', window?.resetsAt ? `Resets in ${duration(window.resetsAt)}` : 'Reset time unavailable'),
    node('span', '', window?.resetsAt ? fmtDate(window.resetsAt) : ''));
  const progress = node('div', 'progress');
  const fill = node('div', `progress-fill${remaining(window) != null && remaining(window) <= 20 ? ' low' : ''}`);
  fill.style.width = `${remaining(window) || 0}%`;
  progress.append(fill);
  box.append(top, meta, progress);
  return box;
}

function stat(label, value) {
  const box = node('div', 'stat');
  box.append(node('div', 'stat-label', label), node('div', 'stat-value', value));
  return box;
}

function renderHistory(history) {
  const wrapper = node('div', 'details');
  wrapper.append(node('div', 'details-title', 'Recent five-hour capacity'));
  const samples = history.slice(0, 25).reverse();
  if (!samples.length) { wrapper.append(node('div', 'empty', 'History starts after the first successful sync.')); return wrapper; }
  const chart = node('div', 'history');
  samples.forEach(sample => {
    const bucket = sample.limits?.rateLimitsByLimitId?.codex || sample.limits?.rateLimits;
    const value = remaining(bucket?.primary);
    const bar = node('div', 'history-bar');
    bar.style.height = `${Math.max(2, value || 0)}%`;
    bar.title = `${fmtDate(sample.captured_at)} · ${value == null ? 'unknown' : fmtNumber(value) + '%'} remaining`;
    chart.append(bar);
  });
  wrapper.append(chart, node('div', 'history-caption', 'Observed snapshots, newest on the right'));
  return wrapper;
}

function removeButton(account) {
  const button = node('button', 'remove-button', 'Remove');
  button.type = 'button';
  button.title = `Remove ${account.name}`;
  button.addEventListener('click', async () => {
    if (!window.confirm(`Remove ${account.name}? Its saved sign-in and usage history will be deleted from this app.`)) return;
    button.disabled = true;
    await request(`/api/accounts/${encodeURIComponent(account.id)}`, {method: 'DELETE'});
    button.disabled = false;
  });
  return button;
}

function connectedCard(account) {
  const latest = account.latest;
  const raw = latest?.limits || {};
  const limits = raw.rateLimitsByLimitId?.codex || raw.rateLimits || {};
  const credits = limits.credits || raw.rateLimits?.credits || {};
  const resets = raw.rateLimitResetCredits;
  const header = node('div', 'account-head');
  const identity = node('div');
  identity.append(node('h2', '', account.name), node('div', 'account-email', account.auth.email || latest?.email || 'Signed in'));
  const stale = !latest || Date.now() / 1000 - latest.captured_at > dashboard.refresh_interval * 2 + 60;
  const controls = node('div', 'card-controls');
  controls.append(node('span', `badge${stale ? ' stale' : ''}`, stale ? 'WAITING FOR SYNC' : 'LIVE'), removeButton(account));
  header.append(identity, controls);
  const body = node('div');
  body.append(header);
  const plan = node('div', 'plan-row');
  plan.append(node('span', 'plan-pill', account.auth.plan_type || latest?.plan_type || 'ChatGPT'), node('span', '', 'Codex and Work plan limits'));
  body.append(plan);
  body.append(windowBlock('Five-hour limit', limits.primary), windowBlock('Weekly limit', limits.secondary));
  const stats = node('div', 'stat-grid');
  stats.append(stat('Credit balance', credits.balance == null ? '—' : fmtNumber(credits.balance)),
    stat('Available resets', resets?.availableCount == null ? '—' : fmtNumber(resets.availableCount)));
  body.append(stats);
  const details = node('div', 'details');
  details.append(node('div', 'details-title', 'Reset credits'));
  const resetRows = resets?.credits || [];
  if (resetRows.length) {
    resetRows.forEach(item => {
      const line = node('div', 'reset-item');
      line.append(node('strong', '', item.title || 'Rate-limit reset'));
      line.append(node('div', '', `Expires ${fmtDate(item.expiresAt)}`));
      details.append(line);
    });
  } else {
    details.append(node('div', 'empty', resets?.availableCount === 0 ? 'No available reset credits.' : 'Reset details are unavailable.'));
  }
  body.append(details);
  const summary = latest?.usage?.summary;
  if (summary && Object.values(summary).some(value => value != null)) {
    const activity = node('div', 'details');
    activity.append(node('div', 'details-title', 'Token activity'));
    const line = node('div', 'reset-item', `Lifetime ${summary.lifetimeTokens == null ? '—' : fmtNumber(summary.lifetimeTokens)} tokens · Current streak ${summary.currentStreakDays == null ? '—' : summary.currentStreakDays + ' days'}`);
    activity.append(line);
    body.append(activity);
  }
  body.append(renderHistory(account.history));
  if (account.error) body.append(node('div', 'error', account.error));
  const actions = node('div', 'foot-actions');
  const sync = node('button', '', 'Sync now');
  sync.type = 'button';
  sync.addEventListener('click', async () => { sync.disabled = true; await post(`/api/accounts/${account.id}/sync`); sync.disabled = false; });
  actions.append(sync, node('span', '', latest ? `Last synced ${fmtDate(latest.captured_at)}` : 'Awaiting first sync'));
  body.append(actions);
  return body;
}

function disconnectedCard(account) {
  const body = node('div');
  const header = node('div', 'account-head');
  const controls = node('div', 'card-controls');
  controls.append(node('span', 'badge offline', 'NOT CONNECTED'), removeButton(account));
  header.append(node('h2', '', account.name), controls);
  body.append(header);
  const connect = node('div', 'connect');
  connect.append(node('p', '', 'Sign in with this ChatGPT account to read its Codex plan limits. Each card has its own separate sign-in.'));
  const button = node('button', '', account.login_pending ? 'Get a new code' : 'Connect account');
  button.type = 'button';
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const result = await post(`/api/accounts/${account.id}/login`);
      if (result) await load();
    } finally { button.disabled = false; }
  });
  connect.append(button);
  if (account.login_pending?.user_code) {
    const box = node('div', 'login-box');
    box.append(node('div', '', 'Open the official sign-in page and enter this code:'));
    const link = node('a', '', 'Open ChatGPT device sign-in');
    link.href = 'https://auth.openai.com/codex/device';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    box.append(node('div', 'code', account.login_pending.user_code), link,
      node('div', 'hint', 'Choose the correct ChatGPT account in the browser. This page will update after sign-in completes.'));
    connect.append(box);
  }
  if (account.error) connect.append(node('div', 'error', account.error));
  body.append(connect);
  if (account.latest) body.append(node('div', 'empty', `Last saved reading: ${fmtDate(account.latest.captured_at)}. Reconnect to update it.`));
  return body;
}

function render(data) {
  dashboard = data;
  const container = $('accounts');
  container.replaceChildren();
  container.dataset.count = String(data.accounts.length);
  data.accounts.forEach(account => {
    const card = node('article', 'account-card');
    card.append(account.auth.connected ? connectedCard(account) : disconnectedCard(account));
    container.append(card);
  });
  if (!data.accounts.length) container.append(node('div', 'no-accounts', 'No accounts yet. Add one to start monitoring.'));
  $('updated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
}

async function request(path, options = {method: 'POST'}) {
  try {
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Request failed (${response.status})`);
    await load();
    return result;
  } catch (error) {
    window.alert(error.message);
    return null;
  }
}

const post = (path) => request(path);

async function load() {
  try {
    const response = await fetch('/api/dashboard', {cache: 'no-store'});
    if (!response.ok) throw new Error(`Dashboard returned HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $('accounts').replaceChildren(node('div', 'error', `Could not load dashboard: ${error.message}`));
    $('updated').textContent = 'Connection error';
  }
}

$('addToggle').addEventListener('click', () => {
  $('addForm').hidden = false;
  $('accountName').focus();
});
$('addCancel').addEventListener('click', () => {
  $('addForm').hidden = true;
  $('addForm').reset();
});
$('addForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('addForm').querySelector('button[type="submit"]');
  button.disabled = true;
  const result = await request('/api/accounts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: $('accountName').value.trim()})
  });
  button.disabled = false;
  if (result) {
    $('addForm').reset();
    $('addForm').hidden = true;
  }
});

$('refresh').addEventListener('click', async () => {
  const button = $('refresh');
  button.disabled = true;
  await Promise.all((dashboard?.accounts || []).filter(a => a.auth.connected).map(a => post(`/api/accounts/${a.id}/sync`)));
  await load();
  button.disabled = false;
});
load();
setInterval(load, 15000);
setInterval(() => { if (dashboard) render(dashboard); }, 60000);
