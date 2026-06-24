/* ═══════════════════════════════════════════════════════
   Second Innings — Dashboard App JS
   Vanilla JS, no framework, talks to FastAPI backend
═══════════════════════════════════════════════════════ */

// ── State ─────────────────────────────────────────────
let currentTab = 'overview';
let jobsPage = 0;
const PAGE_SIZE = 50;
let sourceChart = null;
let typeChart = null;
let pollInterval = null;
let fastPollInterval = null;   // fires every 5s during apply
let lastPendingCount = 0;

// ── Init ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadPendingCount();
  loadJobs();
  loadCompanyQueue();
  loadHistory();
  loadTaskStatus();
  // Poll for stats + pending count + task status every 15 seconds
  pollInterval = setInterval(() => {
    loadStats();
    loadPendingCount();
    loadTaskStatus();
  }, 15000);
});

// ── Tab switching ─────────────────────────────────────
function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
  const el = document.getElementById(`tab-${tab}`);
  if (el) el.classList.add('active');
  const btn = document.querySelector(`[data-tab="${tab}"]`);
  if (btn) btn.classList.add('active');

  if (tab === 'tracker')  loadJobs();
  if (tab === 'company')  loadCompanyQueue();
  if (tab === 'history')  loadHistory();
  if (tab === 'pending')  loadPendingAnswers();
  if (tab === 'settings') loadSettings();
}

// ── API helpers ───────────────────────────────────────
async function api(url, opts = {}) {
  try {
    const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return await res.json();
  } catch (err) {
    toast(`API error: ${err.message}`, 'error');
    throw err;
  }
}

// ── Stats / Overview ──────────────────────────────────
async function loadStats() {
  try {
    const data = await api('/api/stats');
    const p = data.pipeline;

    animateValue('v-scraped',       0, p.total_scraped,         800);
    animateValue('v-easy',          0, p.easy_apply_done,        800);
    animateValue('v-company',       0, p.company_site_pending,   800);
    animateValue('v-total-applied', 0, p.easy_apply_done + p.company_site_applied, 800);

    renderSourceTable(data.sources);
    renderCharts(data.sources, p);
  } catch (_) {}
}

function animateValue(id, from, to, duration) {
  const el = document.getElementById(id);
  if (!el) return;
  const start = performance.now();
  const update = (now) => {
    const progress = Math.min((now - start) / duration, 1);
    const value = Math.round(from + (to - from) * easeOut(progress));
    el.textContent = value.toLocaleString();
    if (progress < 1) requestAnimationFrame(update);
  };
  requestAnimationFrame(update);
}
function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

function renderSourceTable(sources) {
  const tbody = document.getElementById('source-tbody');
  if (!tbody) return;
  tbody.innerHTML = sources.map(s => `
    <tr>
      <td><strong>${s.source}</strong></td>
      <td>${s.total}</td>
      <td>${s.easy_apply}</td>
      <td>${s.company_site}</td>
      <td><span class="score-val score-high">${s.applied}</span></td>
      <td>${s.high_priority}</td>
    </tr>`).join('');
}

function renderCharts(sources, pipeline) {
  const colors = ['#6366f1','#22c55e','#f59e0b','#3b82f6','#a855f7','#ef4444','#14b8a6','#f97316'];
  const chartDefaults = {
    plugins: { legend: { labels: { color: '#8b92a8', font: { family: 'Inter', size: 12 } } } },
    scales: { x: { ticks: { color: '#545b73' }, grid: { color: 'rgba(255,255,255,0.05)' } },
               y: { ticks: { color: '#545b73' }, grid: { color: 'rgba(255,255,255,0.05)' } } },
  };

  // Source bar chart
  const srcCtx = document.getElementById('source-chart');
  if (srcCtx) {
    if (sourceChart) sourceChart.destroy();
    sourceChart = new Chart(srcCtx, {
      type: 'bar',
      data: {
        labels: sources.map(s => s.source),
        datasets: [
          { label: 'Scraped',  data: sources.map(s => s.total),     backgroundColor: 'rgba(99,102,241,0.6)' },
          { label: 'Applied',  data: sources.map(s => s.applied),   backgroundColor: 'rgba(34,197,94,0.6)' },
        ],
      },
      options: { ...chartDefaults, responsive: true, maintainAspectRatio: false,
        plugins: { ...chartDefaults.plugins, legend: { ...chartDefaults.plugins.legend, position: 'top' } } },
    });
  }

  // Apply type doughnut
  const typeCtx = document.getElementById('type-chart');
  if (typeCtx) {
    if (typeChart) typeChart.destroy();
    typeChart = new Chart(typeCtx, {
      type: 'doughnut',
      data: {
        labels: ['Easy Apply', 'Company Site', 'Unknown'],
        datasets: [{
          data: [pipeline.easy_apply_total, pipeline.company_site_total,
                 pipeline.total_scraped - pipeline.easy_apply_total - pipeline.company_site_total],
          backgroundColor: ['rgba(34,197,94,0.7)', 'rgba(245,158,11,0.7)', 'rgba(100,116,139,0.5)'],
          borderColor: ['#22c55e', '#f59e0b', '#64748b'],
          borderWidth: 1,
        }],
      },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { color: '#8b92a8', padding: 16,
          font: { family: 'Inter', size: 12 } } } } },
    });
  }
}

// ── Pending answers (bell) ────────────────────────────
async function loadPendingCount() {
  try {
    const data = await api('/api/pending-answers');
    const badge = document.getElementById('bell-badge');
    if (!badge) return;
    if (data.count > 0) {
      badge.textContent = data.count;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  } catch (_) {}
}

async function loadPendingAnswers() {
  const list = document.getElementById('pending-list');
  if (!list) return;
  list.innerHTML = '<div class="no-pending"><div class="spinner"></div></div>';
  try {
    const data = await api('/api/pending-answers');
    if (!data.items.length) {
      list.innerHTML = `<div class="no-pending">
        <div class="empty-state-icon">✅</div>
        <p>No pending questions — the apply bot has everything it needs!</p>
      </div>`;
      return;
    }
    list.innerHTML = data.items.map(item => `
      <div class="pending-card" id="pending-card-${item.id}">
        <div class="pending-meta">${item.company} — ${item.role}</div>
        <div class="pending-question">${escapeHtml(item.question)}</div>
        <div class="pending-answer-row">
          <input type="text" class="pending-input" id="ans-${item.id}"
                 placeholder="Type your answer…" onkeydown="if(event.key==='Enter') submitAnswer(${item.id})"/>
          <button class="btn-primary" onclick="submitAnswer(${item.id})">Save</button>
        </div>
      </div>`).join('');

  } catch (_) {}
}

async function submitAnswer(pendingId) {
  const input = document.getElementById(`ans-${pendingId}`);
  if (!input || !input.value.trim()) return;
  try {
    await api('/api/pending-answers/answer', {
      method: 'POST',
      body: JSON.stringify({ pending_id: pendingId, answer: input.value.trim() }),
    });
    document.getElementById(`pending-card-${pendingId}`)?.remove();
    toast('Answer saved! Run Apply to retry this job.', 'success');
    loadPendingCount();
  } catch (_) {}
}

// ── Jobs tracker ──────────────────────────────────────
async function loadJobs(page = 0) {
  jobsPage = page;
  const tbody = document.getElementById('jobs-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr class="loading-row"><td colspan="9"><div class="spinner"></div></td></tr>';

  const status = document.getElementById('filter-status')?.value || '';
  const type   = document.getElementById('filter-type')?.value   || '';
  const source = document.getElementById('filter-source')?.value || '';
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: page * PAGE_SIZE });
  if (status) params.set('status', status);
  if (type)   params.set('apply_type', type);
  if (source) params.set('source', source);

  try {
    const jobs = await api(`/api/jobs?${params}`);
    if (!jobs.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="loading-row" style="text-align:center;color:var(--text-3)">No jobs found with these filters.</td></tr>';
      return;
    }
    tbody.innerHTML = jobs.map(j => `
      <tr>
        <td><span class="score-val ${scoreClass(j.score)}">${j.score}</span></td>
        <td><strong>${escapeHtml(j.company)}</strong></td>
        <td class="link-cell"><a href="${j.source_url}" target="_blank" rel="noopener">${escapeHtml(j.role)}</a></td>
        <td>${j.source}</td>
        <td>${applyTypePill(j.apply_type)}</td>
        <td>${statusBadge(j.status)}</td>
        <td>${escapeHtml(j.location || '—')}</td>
        <td>${escapeHtml(j.posted || '—')}</td>
        <td>${jobActions(j)}</td>
      </tr>`).join('');

    renderPagination(page, jobs.length);
  } catch (_) {}
}

function jobActions(j) {
  const url = encodeURIComponent(j.source_url);
  let html = `<a href="${j.source_url}" target="_blank" rel="noopener"><button class="tbl-btn">Open</button></a>`;
  if (j.status !== 'applied') {
    html += `<button class="tbl-btn tbl-btn-green" onclick="markApplied('${encodeURIComponent(j.source_url)}')">Mark Applied</button>`;
  }
  return html;
}

async function markApplied(encodedUrl) {
  const url = decodeURIComponent(encodedUrl);
  try {
    await api(`/api/jobs/${encodeURIComponent(url)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status: 'applied', applied_date: today() }),
    });
    toast('Marked as applied!', 'success');
    loadJobs(jobsPage);
    loadStats();
  } catch (_) {}
}

function renderPagination(page, count) {
  const pg = document.getElementById('pagination');
  if (!pg) return;
  pg.innerHTML = '';
  if (page > 0) {
    const prev = document.createElement('button');
    prev.className = 'page-btn'; prev.textContent = '←';
    prev.onclick = () => loadJobs(page - 1);
    pg.appendChild(prev);
  }
  const cur = document.createElement('button');
  cur.className = 'page-btn active'; cur.textContent = page + 1;
  pg.appendChild(cur);
  if (count === PAGE_SIZE) {
    const next = document.createElement('button');
    next.className = 'page-btn'; next.textContent = '→';
    next.onclick = () => loadJobs(page + 1);
    pg.appendChild(next);
  }
}

// ── Company queue ─────────────────────────────────────
async function loadCompanyQueue() {
  const tbody = document.getElementById('company-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr class="loading-row"><td colspan="8"><div class="spinner"></div></td></tr>';
  try {
    const jobs = await api('/api/jobs?apply_type=company_site&limit=200');
    if (!jobs.length) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--text-3)">
        No company-site jobs yet. Run a scrape to find some!</td></tr>`;
      return;
    }
    tbody.innerHTML = jobs.map(j => {
      let applyHostname = '';
      try { applyHostname = j.external_url ? new URL(j.external_url).hostname.replace('www.', '') : ''; } catch (_) {}
      const applyUrl = j.external_url
        ? `<a href="${escapeHtml(j.external_url)}" target="_blank" class="ext-link" title="${escapeHtml(j.external_url)}">${escapeHtml(applyHostname || j.external_url)}</a>`
        : `<a href="${j.source_url}" target="_blank" class="ext-link dim">LinkedIn →</a>`;

      return `
      <tr>
        <td><span class="score-val ${scoreClass(j.score)}">${j.score}</span></td>
        <td><strong>${escapeHtml(j.company)}</strong></td>
        <td class="link-cell"><a href="${j.source_url}" target="_blank">${escapeHtml(j.role)}</a></td>
        <td>${j.source}</td>
        <td>${escapeHtml(j.location || '—')}</td>
        <td>${applyUrl}</td>
        <td>${statusBadge(j.status)}</td>
        <td>
          <a href="${j.external_url || j.source_url}" target="_blank"><button class="tbl-btn">Open & Apply</button></a>
          ${j.status !== 'applied'
            ? `<button class="tbl-btn tbl-btn-green" onclick="markApplied('${encodeURIComponent(j.source_url)}')">Mark Applied</button>`
            : ''}
        </td>
      </tr>`;
    }).join('');
  } catch (_) {}
}

async function findCompanyEmails() {
  const domain = document.getElementById('ce-domain')?.value?.trim();
  if (!domain) { toast('Enter a company domain e.g. reddit.com', 'error'); return; }

  const status = document.getElementById('ce-status');
  const results = document.getElementById('ce-results');
  if (status) status.textContent = 'Searching…';
  if (results) results.style.display = 'none';

  try {
    const res = await api('/api/contact/domain-search', {
      method: 'POST',
      body: JSON.stringify({ company_domain: domain }),
    });

    if (status) status.textContent = '';
    if (!results) return;

    const sourceLabel = res.source === 'hunter'
      ? `<span class="pill-verified">✓ Hunter.io — verified results</span>`
      : `<span class="pill-pattern">Generic patterns — add Hunter.io key in Settings for real results</span>`;

    results.innerHTML = `
      <div style="margin-bottom:10px">${sourceLabel}</div>
      <div class="email-contact-grid">
        ${res.contacts.map(c => `
          <div class="email-contact-card">
            <span class="contact-email" onclick="copyText('${escapeHtml(c.email)}',this)" title="Click to copy">${escapeHtml(c.email)}</span>
            ${c.name  ? `<span class="contact-meta">${escapeHtml(c.name)}</span>` : ''}
            ${c.title ? `<span class="contact-meta">${escapeHtml(c.title)}</span>` : ''}
          </div>`).join('')}
      </div>`;
    results.style.display = 'block';
  } catch (_) {
    if (status) status.textContent = 'Lookup failed';
  }
}

function copyText(text, el) {
  navigator.clipboard?.writeText(text).then(() => {
    const orig = el.textContent;
    el.textContent = 'Copied!';
    setTimeout(() => { el.textContent = orig; }, 1200);
  });
}

// ── Scrape history ────────────────────────────────────
async function loadHistory() {
  const tbody = document.getElementById('history-tbody');
  if (!tbody) return;
  try {
    const rows = await api('/api/scrape-history?limit=50');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text-3)">No scrape runs yet.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${formatTime(r.run_at)}</td>
        <td>${r.source}</td>
        <td>${r.label || '—'}</td>
        <td>${r.jobs_found}</td>
        <td><span class="score-val score-high">${r.jobs_new}</span></td>
        <td>${r.jobs_duplicate || 0}</td>
        <td>${r.duration_seconds?.toFixed(1)}s</td>
      </tr>`).join('');
  } catch (_) {}
}

// ── Task status polling ───────────────────────────────
async function loadTaskStatus() {
  try {
    const data = await api('/api/task-status');
    const scrapeBtn = document.getElementById('scrape-btn');
    const applyBtn = document.getElementById('apply-btn');

    if (data.scrape) {
      scrapeBtn.disabled = true;
      scrapeBtn.innerHTML = '<div class="spinner"></div> Scraping…';
    } else {
      scrapeBtn.disabled = false;
      scrapeBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
      </svg> Scrape`;
    }

    if (data.apply) {
      applyBtn.disabled = true;
      applyBtn.innerHTML = '<div class="spinner"></div> Applying…';
      // Start fast-poll while apply is running
      if (!fastPollInterval) {
        fastPollInterval = setInterval(async () => {
          await loadPendingCount();
          // Auto-surface pending tab when new questions arrive
          const badge = document.getElementById('bell-badge');
          const count = badge ? parseInt(badge.textContent || '0') : 0;
          if (count > lastPendingCount) {
            lastPendingCount = count;
            toast(`🔔 ${count} question(s) need your answer to continue applying!`, 'info');
            // Auto-open pending tab so user sees questions immediately
            switchTab('pending');
          }
          lastPendingCount = count;
        }, 5000);
      }
    } else {
      applyBtn.disabled = false;
      applyBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
      </svg> Apply`;
      // Stop fast-poll when apply finishes
      if (fastPollInterval) {
        clearInterval(fastPollInterval);
        fastPollInterval = null;
        lastPendingCount = 0;
      }
    }
  } catch (_) {}
}

// ── Scrape / Apply triggers ───────────────────────────
async function triggerScrape() {
  const btn = document.getElementById('scrape-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Scraping…';
  try {
    const res = await api('/api/scrape', { method: 'POST' });
    toast(res.message, res.ok ? 'info' : 'error');
    if (res.ok) {
      setTimeout(() => { loadStats(); loadJobs(); loadHistory(); loadTaskStatus(); }, 3000);
    }
  } catch (_) {
    loadTaskStatus();
  }
}

async function triggerApply() {
  const btn = document.getElementById('apply-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Applying…';
  try {
    const res = await api('/api/apply', { method: 'POST' });
    toast(res.message, res.ok ? 'info' : 'error');
    if (res.ok) {
      setTimeout(() => { loadStats(); loadJobs(); loadPendingCount(); loadTaskStatus(); }, 5000);
    }
  } catch (_) {
    loadTaskStatus();
  }
}

// ── Content generation ────────────────────────────────
async function generateContent(type) {
  const company = document.getElementById('cg-company')?.value?.trim();
  const role    = document.getElementById('cg-role')?.value?.trim();
  if (!company || !role) { toast('Please enter company and role', 'error'); return; }

  const output = document.getElementById('content-output');
  const title  = document.getElementById('output-title');
  const copyBtn = document.getElementById('copy-btn');
  const emailSubject = document.getElementById('email-subject');

  output.innerHTML = '<div class="spinner" style="margin:40px auto;display:block;width:24px;height:24px"></div>';
  copyBtn.style.display = 'none';
  emailSubject?.classList.add('hidden');

  const body = {
    company,
    role,
    jd_text: document.getElementById('cg-jd')?.value?.trim() || '',
    hiring_manager: document.getElementById('cg-manager')?.value?.trim() || '',
  };

  const endpointMap = {
    'cover-letter': '/api/content/cover-letter',
    'cold-email':   '/api/content/cold-email',
    'linkedin-dm':  '/api/content/linkedin-dm',
  };
  const titleMap = {
    'cover-letter': '📄 Cover Letter',
    'cold-email':   '✉️ Cold Email',
    'linkedin-dm':  '💬 LinkedIn DM',
  };

  try {
    const res = await api(endpointMap[type], { method: 'POST', body: JSON.stringify(body) });
    title.textContent = titleMap[type];
    copyBtn.style.display = 'block';

    if (type === 'cold-email' && res.subject) {
      output.textContent = res.body;
      emailSubject.textContent = `Subject: ${res.subject}`;
      emailSubject.classList.remove('hidden');
    } else {
      output.textContent = res.content || res.body || '';
    }
  } catch (_) {
    output.innerHTML = '<p class="output-placeholder">Generation failed. Check your AI config.</p>';
  }
}

function copyOutput() {
  const output = document.getElementById('content-output');
  const emailSubject = document.getElementById('email-subject');
  let text = output.textContent || '';
  if (emailSubject && !emailSubject.classList.contains('hidden')) {
    text = emailSubject.textContent + '\n\n' + text;
  }
  navigator.clipboard.writeText(text).then(() => toast('Copied to clipboard!', 'success'));
}

// ── Helpers ───────────────────────────────────────────
function statusBadge(status) {
  const cls = `badge badge-${status?.replace(/_/g, '_') || 'new'}`;
  return `<span class="${cls}">${status || 'new'}</span>`;
}

function applyTypePill(type) {
  if (type === 'easy_apply')   return `<span class="pill-easy">Easy Apply</span>`;
  if (type === 'company_site') return `<span class="pill-company">Company Site</span>`;
  return `<span class="pill-unknown">Unknown</span>`;
}

function scoreClass(score) {
  if (score >= 70) return 'score-high';
  if (score >= 40) return 'score-mid';
  return 'score-low';
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function formatTime(ts) {
  if (!ts) return '—';
  try {
    return new Date(ts.replace(' ', 'T') + 'Z').toLocaleString(undefined,
      { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch (_) { return ts; }
}

function toast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── Settings ─────────────────────────────────
function _setVal(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.tagName === 'SELECT') {
    // match boolean or string
    const str = String(val);
    for (const opt of el.options) {
      if (opt.value === str || opt.text === str) { el.value = opt.value; break; }
    }
  } else {
    el.value = val ?? '';
  }
}

async function loadSettings() {
  try {
    const s = await api('/api/settings');
    const p = s.profile || {};
    _setVal('s-full_name',     p.full_name);
    _setVal('s-email',         p.email);
    _setVal('s-phone',         p.phone);
    _setVal('s-current_ctc_lpa',    p.current_ctc_lpa);
    _setVal('s-expected_ctc_lpa',   p.expected_ctc_lpa);
    _setVal('s-notice_period_days', p.notice_period_days);
    _setVal('s-years_experience',   p.years_experience);
    _setVal('s-current_location',   p.current_location);
    _setVal('s-willing_to_relocate',    p.willing_to_relocate);
    _setVal('s-work_authorization',     p.work_authorization);
    _setVal('s-visa_sponsorship_required', p.visa_sponsorship_required);
    _setVal('s-comfortable_onsite', p.comfortable_onsite);
    _setVal('s-comfortable_remote', p.comfortable_remote);
    _setVal('s-earliest_start',     p.earliest_start);
    _setVal('s-is_veteran',         p.is_veteran ?? 'No');
    _setVal('s-linkedin_url',       p.linkedin_url);
    _setVal('s-resume_path',        p.resume_path);
    // preferred_locations is a list in config, show as comma-separated string
    const locs = p.preferred_locations;
    _setVal('s-preferred_locations', Array.isArray(locs) ? locs.join(', ') : (locs || ''));

    const ai = s.ai || {};
    _setVal('s-ai-provider', ai.provider);
    _setVal('s-ai-api_key',  ai.api_key);

    const sc = s.scraper || {};
    _setVal('s-scraper-max_jobs_per_search',     sc.max_jobs_per_search);
    _setVal('s-scraper-fresh_only_days',         sc.fresh_only_days);
    _setVal('s-scraper-enrich_details',          sc.enrich_details);
    _setVal('s-scraper-enrich_limit_per_search', sc.enrich_limit_per_search);
    // Render scraper site checkboxes
    _renderSiteChecks('scraper-sites', s.all_scraper_sites || [], sc.sources || [], false);

    const sc2 = s.scoring || {};
    _setVal('s-scoring-priority_threshold',  sc2.priority_threshold);
    _setVal('s-scoring-shortlist_threshold', sc2.shortlist_threshold);

    const ap = s.applier || {};
    _setVal('s-applier-max_per_run',            ap.max_per_run);
    _setVal('s-applier-delay_seconds',          ap.delay_seconds);
    _setVal('s-applier-dry_run',                ap.dry_run);
    _setVal('s-applier-pause_on_unknown_form',  ap.pause_on_unknown_form);
    _setVal('s-applier-unknown_question_wait_seconds', ap.unknown_question_wait_seconds ?? 600);
    // Render applier site checkboxes
    _renderSiteChecks('applier-sites', s.all_applier_sites || [], ap.sources || [], true);
  } catch (_) {
    toast('Could not load settings', 'error');
  }
}

async function saveSettings(section) {
  let data = {};

  if (section === 'profile') {
    data = {
      full_name:     document.getElementById('s-full_name')?.value,
      email:         document.getElementById('s-email')?.value,
      phone:         document.getElementById('s-phone')?.value,
      current_ctc_lpa:    document.getElementById('s-current_ctc_lpa')?.value,
      expected_ctc_lpa:   document.getElementById('s-expected_ctc_lpa')?.value,
      notice_period_days: document.getElementById('s-notice_period_days')?.value,
      years_experience:   Number(document.getElementById('s-years_experience')?.value),
      current_location:   document.getElementById('s-current_location')?.value,
      willing_to_relocate:    document.getElementById('s-willing_to_relocate')?.value,
      work_authorization:     document.getElementById('s-work_authorization')?.value,
      visa_sponsorship_required: document.getElementById('s-visa_sponsorship_required')?.value,
      comfortable_onsite: document.getElementById('s-comfortable_onsite')?.value,
      comfortable_remote: document.getElementById('s-comfortable_remote')?.value,
      earliest_start:     document.getElementById('s-earliest_start')?.value,
      is_veteran:         document.getElementById('s-is_veteran')?.value,
      linkedin_url:       document.getElementById('s-linkedin_url')?.value,
      resume_path:        document.getElementById('s-resume_path')?.value,
      // split comma-separated locations back to a list
      preferred_locations: (document.getElementById('s-preferred_locations')?.value || '')
        .split(',').map(s => s.trim()).filter(Boolean),
    };
  } else if (section === 'ai') {
    data = {
      provider: document.getElementById('s-ai-provider')?.value,
      api_key:  document.getElementById('s-ai-api_key')?.value,
    };
  } else if (section === 'scraper') {
    data = {
      max_jobs_per_search:     Number(document.getElementById('s-scraper-max_jobs_per_search')?.value),
      fresh_only_days:         Number(document.getElementById('s-scraper-fresh_only_days')?.value),
      enrich_details:          document.getElementById('s-scraper-enrich_details')?.value === 'true',
      enrich_limit_per_search: Number(document.getElementById('s-scraper-enrich_limit_per_search')?.value),
      sources: _getCheckedSites('scraper-sites'),
    };
  } else if (section === 'scoring') {
    data = {
      priority_threshold:  Number(document.getElementById('s-scoring-priority_threshold')?.value),
      shortlist_threshold: Number(document.getElementById('s-scoring-shortlist_threshold')?.value),
    };
  } else if (section === 'applier') {
    data = {
      max_per_run:           Number(document.getElementById('s-applier-max_per_run')?.value),
      delay_seconds:         Number(document.getElementById('s-applier-delay_seconds')?.value),
      dry_run:               document.getElementById('s-applier-dry_run')?.value === 'true',
      pause_on_unknown_form: document.getElementById('s-applier-pause_on_unknown_form')?.value === 'true',
      unknown_question_wait_seconds: Number(document.getElementById('s-applier-unknown_question_wait_seconds')?.value) || 600,
      sources: _getCheckedSites('applier-sites'),
    };
  }

  try {
    const res = await api('/api/settings', {
      method: 'POST',
      body: JSON.stringify({ section, data }),
    });
    toast(res.message || 'Saved!', 'success');
  } catch (_) {
    toast('Save failed', 'error');
  }
}

function _renderSiteChecks(containerId, allSites, enabledSites, caseSensitive) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const enabledLower = enabledSites.map(s => s.toLowerCase());
  el.innerHTML = allSites.map(site => {
    const checked = enabledLower.includes(site.toLowerCase()) ? 'checked' : '';
    const label = site.charAt(0).toUpperCase() + site.slice(1);
    return `<label class="site-check-label">
      <input type="checkbox" value="${site}" ${checked}/>
      <span>${label}</span>
    </label>`;
  }).join('');
}

function _getCheckedSites(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return [];
  return [...el.querySelectorAll('input[type=checkbox]:checked')].map(cb => cb.value);
}
