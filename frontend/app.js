// =============================================================
// Rivyu frontend: vanilla JS, no build step.
// Routing is hash-based (#/sources, #/dashboard, #/theme/<id>, #/ask).
// =============================================================
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
    status: null,          // last /api/status payload
    dashboard: null,       // last /api/dashboard payload
    timeFilter: 'all',
    themeScope: 'all',
    feed: { q: '', source: '', bucket: '', tone: '' },
    chatStarted: false,
    asking: false,
    analyzing: false,
    serverAwake: false,
    offline: false,
};

const SOURCE_META = {
    google_play: { label: 'Google Play', icon: 'phone' },
    reddit: { label: 'Reddit', icon: 'chat' },
    csv: { label: 'CSV', icon: 'file' },
    demo: { label: 'Demo dataset', icon: 'sparkles' },
    gmail: { label: 'Gmail', icon: 'mail' },
    x: { label: 'X', icon: 'at' },
    youtube_comments: { label: 'YouTube', icon: 'chat' },
};

const RISK_LABELS = {
    revenue_risk: 'Revenue risk',
    churn_risk: 'Churn risk',
    stability_risk: 'Stability risk',
    trust_risk: 'Trust risk',
    ux_risk: 'UX risk',
    support_risk: 'Support risk',
    retention_risk: 'Retention risk',
};

const PAGE_TITLES = {
    landing: 'Rivyu · AI product feedback analysis',
    sources: 'Sources · Rivyu',
    dashboard: 'Dashboard · Rivyu',
    theme: 'Theme · Rivyu',
    ask: 'Ask Rivyu',
};

const APP_ID_RE = /^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$/;
const SUBREDDIT_RE = /^[A-Za-z0-9][A-Za-z0-9_]{1,20}$/;
const MAX_CSV_BYTES = 5 * 1024 * 1024;

// -------------------------------------------------------------
// Small helpers
// -------------------------------------------------------------

function esc(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function icon(name, cls = 'i') {
    return `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function plural(n, one, many = one + 's') {
    return `${Number(n).toLocaleString()} ${n === 1 ? one : many}`;
}

function sourceLabel(type) {
    return (SOURCE_META[type] || {}).label || String(type || 'Unknown').replace(/_/g, ' ');
}

function parseDate(value) {
    if (!value) return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
}

function timeAgo(value) {
    const d = parseDate(value);
    if (!d) return '';
    const secs = Math.round((Date.now() - d.getTime()) / 1000);
    if (secs < 45) return 'just now';
    const mins = Math.round(secs / 60);
    if (mins < 60) return `${mins} min ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs} h ago`;
    const days = Math.round(hrs / 24);
    if (days < 30) return `${days} d ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function shortDate(value) {
    const d = parseDate(value);
    return d ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';
}

function toneOf(sentiment) {
    const s = Number(sentiment) || 0;
    if (s <= -0.25) return 'negative';
    if (s >= 0.25) return 'positive';
    return 'mixed';
}

function fmtSentiment(s) {
    const n = Number(s) || 0;
    return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(2);
}

// -------------------------------------------------------------
// API wrapper: readable errors, timeouts and cold-start banner
// -------------------------------------------------------------

class ApiError extends Error {
    constructor(message, status = 0) {
        super(message);
        this.status = status;
    }
}

let inFlight = 0;
let wakeTimer = null;

function showWake(show) {
    $('#wake-banner').hidden = !show;
}

function trackStart() {
    inFlight += 1;
    if (!state.serverAwake && !wakeTimer) {
        wakeTimer = setTimeout(() => showWake(true), 2500);
    }
}

function trackEnd() {
    inFlight = Math.max(0, inFlight - 1);
    if (inFlight === 0 || state.serverAwake) {
        clearTimeout(wakeTimer);
        wakeTimer = null;
        if (state.serverAwake) showWake(false);
    }
}

async function api(path, { method = 'GET', body, form, timeout = 120000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const opts = { method, signal: controller.signal, headers: { Accept: 'application/json' } };
    if (form) {
        opts.body = form;
    } else if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }

    trackStart();
    try {
        let res;
        try {
            res = await fetch(path, opts);
        } catch (err) {
            if (err.name === 'AbortError') {
                throw new ApiError('The server took too long to respond. Please try again.');
            }
            throw new ApiError("Can't reach the server. Check your connection and try again.");
        }

        // Render returns 502/503 while a sleeping instance boots.
        if (res.status === 502 || res.status === 503) {
            throw new ApiError('The server is still starting up. Give it a few seconds and try again.', res.status);
        }

        state.serverAwake = true;
        setOffline(false);

        let data = null;
        if ((res.headers.get('content-type') || '').includes('application/json')) {
            try { data = await res.json(); } catch (_) { data = null; }
        }

        if (!res.ok) {
            let msg = data && data.detail;
            if (Array.isArray(msg)) msg = msg.map(d => d.msg).join('; ');
            if (!msg) msg = res.status >= 500
                ? 'The server hit an unexpected error. Please try again.'
                : `Request failed (${res.status}).`;
            throw new ApiError(msg, res.status);
        }
        return data;
    } finally {
        clearTimeout(timer);
        trackEnd();
    }
}

function setOffline(offline) {
    state.offline = offline;
    renderSessionPill();
}

// -------------------------------------------------------------
// Toasts
// -------------------------------------------------------------

function toast(kind, title, message = '', timeout = 5000) {
    const region = $('#toasts');
    const el = document.createElement('div');
    el.className = 'toast';
    el.dataset.kind = kind;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    el.innerHTML = `
        <div class="toast-body">
            <div class="toast-title">${esc(title)}</div>
            ${message ? `<div class="toast-msg">${esc(message)}</div>` : ''}
        </div>
        <button class="toast-close" type="button" aria-label="Dismiss notification">&times;</button>`;
    const close = () => {
        el.classList.add('leaving');
        setTimeout(() => el.remove(), 180);
    };
    el.querySelector('.toast-close').addEventListener('click', close);
    region.appendChild(el);
    while (region.children.length > 4) region.firstElementChild.remove();
    if (timeout) setTimeout(close, kind === 'error' ? timeout * 1.6 : timeout);
}

// -------------------------------------------------------------
// Modal (used for analysis progress and confirmations)
// -------------------------------------------------------------

let lastFocus = null;

function openModal(html, { labelledBy, onKeydown } = {}) {
    lastFocus = document.activeElement;
    const root = $('#modal-root');
    root.innerHTML = `
        <div class="modal-backdrop">
            <div class="card modal" role="dialog" aria-modal="true" ${labelledBy ? `aria-labelledby="${labelledBy}"` : ''} tabindex="-1">
                ${html}
            </div>
        </div>`;
    const dialog = $('.modal', root);
    dialog.addEventListener('keydown', e => {
        if (onKeydown) onKeydown(e);
        if (e.key === 'Tab') trapFocus(e, dialog);
    });
    (dialog.querySelector('[autofocus]') || dialog).focus();
    return dialog;
}

function closeModal() {
    $('#modal-root').innerHTML = '';
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}

function trapFocus(e, container) {
    const focusable = $$('button:not([disabled]), a[href], input, textarea, select, [tabindex]:not([tabindex="-1"])', container);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

function confirmDialog({ title, message, confirmLabel = 'Confirm' }) {
    return new Promise(resolve => {
        const dialog = openModal(`
            <h2 id="confirm-title">${esc(title)}</h2>
            <p>${esc(message)}</p>
            <div class="modal-actions">
                <button class="btn" type="button" data-choice="cancel" autofocus>Cancel</button>
                <button class="btn btn-primary" type="button" data-choice="ok">${esc(confirmLabel)}</button>
            </div>`, {
            labelledBy: 'confirm-title',
            onKeydown: e => { if (e.key === 'Escape') { closeModal(); resolve(false); } },
        });
        dialog.addEventListener('click', e => {
            const btn = e.target.closest('[data-choice]');
            if (!btn) return;
            closeModal();
            resolve(btn.dataset.choice === 'ok');
        });
    });
}

// -------------------------------------------------------------
// Session status
// -------------------------------------------------------------

async function refreshStatus() {
    try {
        state.status = await api('/api/status');
    } catch (err) {
        if (!state.status) setOffline(true);
        throw err;
    } finally {
        renderSessionPill();
        renderRail();
    }
    return state.status;
}

function sessionState() {
    return (state.status && state.status.state) || 'empty';
}

function renderSessionPill() {
    const dot = $('#session-dot');
    const label = $('#session-label');
    const pill = $('#session-pill');
    let dotState = 'empty';
    let text = 'Connecting…';

    if (state.analyzing) {
        dotState = 'busy'; text = 'Analyzing…';
    } else if (state.offline) {
        dotState = 'error'; text = 'Server unreachable';
    } else if (state.status) {
        const s = state.status;
        dotState = s.state;
        text = s.state === 'analyzed' ? `${plural(s.processed_count, 'item')} analyzed`
            : s.state === 'ingested' ? `${plural(s.raw_count, 'item')} loaded · not analyzed`
            : 'No data loaded';
    }
    dot.dataset.state = dotState;
    label.textContent = text;
    pill.title = `Session status: ${text}`;
}

// -------------------------------------------------------------
// Router
// -------------------------------------------------------------

let firstRoute = true;

function parseRoute() {
    const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
    const name = parts[0] || 'landing';
    return { name: PAGE_TITLES[name] ? name : 'landing', param: parts[1] ? decodeURIComponent(parts[1]) : '' };
}

function route() {
    const { name, param } = parseRoute();

    $$('.page').forEach(p => { p.hidden = p.dataset.page !== name; });
    $$('.nav-link').forEach(a => {
        const active = a.dataset.route === name || (name === 'theme' && a.dataset.route === 'dashboard');
        if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    document.title = PAGE_TITLES[name];

    if (name === 'sources') renderRail();
    if (name === 'dashboard') loadDashboard();
    if (name === 'theme') loadTheme(param);
    if (name === 'ask') renderAsk();

    if (!firstRoute) {
        window.scrollTo(0, 0);
        const heading = $(`#page-${name} h1`);
        if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus({ preventScroll: true }); }
    }
    firstRoute = false;
}

function go(hash) {
    if (location.hash === hash) route(); else location.hash = hash;
}

// -------------------------------------------------------------
// Sources page
// -------------------------------------------------------------

function setFieldError(input, message) {
    const err = document.getElementById((input.getAttribute('aria-describedby') || '').split(' ')[0]);
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (err) err.textContent = message || '';
}

function setButtonBusy(btn, busy, busyText) {
    if (busy) {
        btn.dataset.label = btn.innerHTML;
        btn.innerHTML = `<span class="spinner" aria-hidden="true"></span>${esc(busyText)}`;
        btn.disabled = true;
        btn.setAttribute('aria-busy', 'true');
    } else {
        if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
        btn.disabled = false;
        btn.removeAttribute('aria-busy');
    }
}

function clampCount(input) {
    const n = parseInt(input.value, 10);
    const v = Number.isFinite(n) ? Math.max(10, Math.min(300, n)) : 80;
    input.value = v;
    return v;
}

function normalizeAppId(raw) {
    const value = raw.trim();
    const m = value.match(/[?&]id=([A-Za-z0-9_.]+)/);
    return m ? m[1] : value;
}

function normalizeSubreddit(raw) {
    return raw.trim().replace(/^\/?r\//i, '').replace(/\/+$/, '');
}

async function submitSource(form) {
    const btn = form.querySelector('button[type="submit"]');
    const type = form.dataset.source;
    let request;
    let busyText = 'Fetching…';

    if (type === 'google_play') {
        const input = $('#gp-app-id', form);
        const appId = normalizeAppId(input.value);
        if (!appId) return setFieldError(input, 'Enter an app ID, e.g. com.whatsapp.'), input.focus();
        if (!APP_ID_RE.test(appId)) return setFieldError(input, 'That doesn\'t look like an app ID. It should look like com.company.app.'), input.focus();
        setFieldError(input, '');
        request = { path: '/api/ingest/playstore', body: { app_id: appId, count: clampCount($('#gp-count', form)) } };
    } else if (type === 'reddit') {
        const input = $('#reddit-sub', form);
        const sub = normalizeSubreddit(input.value);
        if (!sub) return setFieldError(input, 'Enter a subreddit, e.g. whatsapp.'), input.focus();
        if (!SUBREDDIT_RE.test(sub)) return setFieldError(input, 'Subreddit names are 2–21 letters, numbers or underscores.'), input.focus();
        setFieldError(input, '');
        request = { path: '/api/ingest/reddit', body: { subreddit: sub, query: $('#reddit-query', form).value.trim(), count: clampCount($('#reddit-count', form)) } };
    } else if (type === 'csv') {
        const input = $('#csv-file', form);
        const file = input.files[0];
        if (!file) return setFieldError(input, 'Choose a CSV file first.'), input.focus();
        if (!/\.(csv|txt)$/i.test(file.name)) return setFieldError(input, 'That isn\'t a .csv file.'), input.focus();
        if (file.size > MAX_CSV_BYTES) return setFieldError(input, 'The file is over 5 MB. Split it into smaller files.'), input.focus();
        if (file.size === 0) return setFieldError(input, 'The file is empty.'), input.focus();
        setFieldError(input, '');
        const data = new FormData();
        data.append('file', file);
        request = { path: '/api/ingest/csv', form: data };
        busyText = 'Uploading…';
    } else if (type === 'demo') {
        if (sessionState() !== 'empty') {
            const ok = await confirmDialog({
                title: 'Replace current session?',
                message: 'Loading the demo dataset clears the sources and results in this session.',
                confirmLabel: 'Load demo',
            });
            if (!ok) return;
        }
        request = { path: '/api/ingest/demo' };
        busyText = 'Loading…';
    }

    setButtonBusy(btn, true, busyText);
    try {
        const res = await api(request.path, { method: 'POST', body: request.body, form: request.form, timeout: 90000 });
        const what = type === 'google_play' ? 'reviews' : type === 'reddit' ? 'posts' : 'items';
        toast('success', `Added ${res.count} ${what}`, `${sourceLabel(type)} · ${(res.total_raw ?? res.count)} items in session`);
        if (type === 'csv') resetCsvInput();
        state.dashboard = null;
        await refreshStatus().catch(() => {});
    } catch (err) {
        const fieldInput = form.querySelector('[aria-describedby]');
        if (fieldInput && err.status && err.status < 500) setFieldError(fieldInput, err.message);
        toast('error', `Couldn't add ${sourceLabel(type)}`, err.message);
    } finally {
        setButtonBusy(btn, false);
    }
}

function resetCsvInput() {
    const input = $('#csv-file');
    input.value = '';
    $('#csv-file-name').textContent = 'Choose a file or drop it here';
}

function renderRail() {
    const s = state.status;
    const st = sessionState();
    const sources = (s && s.sources) || [];
    const list = $('#source-list');
    const stateEl = $('#rail-state');
    const analyzeBtn = $('#analyze-btn');

    if (!s) {
        stateEl.textContent = state.offline ? 'Can\'t reach the server right now.' : 'Loading session…';
    } else if (st === 'empty') {
        stateEl.textContent = 'No data loaded yet. Add a source or load the demo dataset.';
    } else if (st === 'ingested') {
        stateEl.textContent = `${plural(s.raw_count, 'item')} ready to analyze.`;
    } else {
        stateEl.textContent = `Analyzed ${plural(s.processed_count, 'item')} ${timeAgo(s.analyzed_at)}.`;
    }

    list.hidden = sources.length === 0;
    list.innerHTML = sources.map(src => `
        <li>
            ${icon((SOURCE_META[src.type] || {}).icon || 'database')}
            <span class="name" title="${esc(src.id)}">${esc(src.type === 'demo' ? 'Demo dataset' : src.id)}</span>
            <span class="num">${Number(src.count || 0).toLocaleString()}</span>
        </li>`).join('');

    $('#rail-total').hidden = sources.length === 0;
    $('#rail-total-num').textContent = s ? Number(s.raw_count).toLocaleString() : '0';

    analyzeBtn.disabled = st === 'empty' || state.analyzing;
    $('#analyze-label').textContent = st === 'analyzed' ? 'Re-run analysis' : 'Run analysis';
    $('#view-dash-btn').hidden = st !== 'analyzed';
    $('#clear-btn').hidden = st === 'empty';

    const limit = (s && s.analyze_limit) || 220;
    $('#rail-note').textContent = s && s.raw_count > limit
        ? `Analysis uses the first ${limit} items to keep it fast.`
        : 'Adding a source clears previous results until you re-run the analysis.';

    // Card badges reflect what's actually connected.
    $$('form.source-card').forEach(form => {
        const connected = sources.some(src => src.type === form.dataset.source);
        const badge = form.querySelector('[data-badge]');
        form.classList.toggle('is-connected', connected);
        if (!badge) return;
        if (form.dataset.source === 'demo') {
            badge.textContent = connected ? 'Loaded' : 'Sample';
            badge.className = `badge ${connected ? 'badge-live' : 'badge-accent'}`;
        } else {
            badge.textContent = connected ? 'Connected' : 'Live';
            badge.className = `badge ${connected ? 'badge-live' : 'badge-outline'}`;
        }
    });
}

async function clearSession() {
    const ok = await confirmDialog({
        title: 'Clear this session?',
        message: 'This removes all loaded sources and analysis results.',
        confirmLabel: 'Clear session',
    });
    if (!ok) return;
    try {
        await api('/api/reset', { method: 'POST' });
        state.dashboard = null;
        state.chatStarted = false;
        $('#chat-log').innerHTML = '';
        await refreshStatus();
        toast('info', 'Session cleared');
    } catch (err) {
        toast('error', 'Couldn\'t clear the session', err.message);
    }
}

// -------------------------------------------------------------
// Analysis (stepper modal)
// -------------------------------------------------------------

const STEPS = [
    ['Preparing data', 'Normalizing items from every source'],
    ['Classifying feedback', 'Topic, sentiment, urgency and risk for each item'],
    ['Grouping themes', 'Clustering related feedback'],
    ['Computing trends', 'Week-over-week movement per theme'],
    ['Generating alerts', 'Ranking risks and suggesting actions'],
];

async function runAnalysis({ useDemo = false, after = '#/dashboard' } = {}) {
    if (state.analyzing) return;
    state.analyzing = true;
    renderSessionPill();
    renderRail();

    const dialog = openModal(`
        <h2 id="analysis-title">Analyzing feedback</h2>
        <p id="analysis-sub">This usually takes 10–40 seconds.</p>
        <div class="progress" role="progressbar" aria-label="Analysis progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="progress-fill" id="analysis-fill"></div></div>
        <ol class="stepper" id="analysis-steps">
            ${STEPS.map(([t, d], i) => `
                <li data-state="${i === 0 ? 'active' : 'pending'}">
                    <span class="dot" aria-hidden="true"></span>
                    <span class="step-text">${esc(t)}<small>${esc(d)}</small></span>
                </li>`).join('')}
        </ol>
        <div class="modal-actions" id="analysis-actions" hidden></div>`, { labelledBy: 'analysis-title' });

    const items = $$('#analysis-steps li', dialog);
    const fill = $('#analysis-fill', dialog);
    const bar = $('.progress', dialog);
    let current = 0;

    const setStep = idx => {
        items.forEach((li, i) => {
            li.dataset.state = i < idx ? 'done' : i === idx ? 'active' : 'pending';
            li.querySelector('.dot').innerHTML = i < idx ? icon('check') : '';
        });
        const pct = Math.round((idx / STEPS.length) * 100);
        fill.style.width = `${Math.max(6, pct)}%`;
        bar.setAttribute('aria-valuenow', String(pct));
    };
    setStep(0);

    // The backend runs all stages in one request, so we pace the stepper
    // and hold on the last stage until the response arrives.
    const ticker = setInterval(() => {
        if (current < STEPS.length - 1) setStep(++current);
    }, 2200);

    try {
        if (useDemo) await api('/api/ingest/demo', { method: 'POST' });
        const res = await api('/api/analyze', { method: 'POST', body: { use_demo: false }, timeout: 180000 });
        clearInterval(ticker);
        setStep(STEPS.length);
        fill.style.width = '100%';
        $('#analysis-sub', dialog).textContent = `Done: ${plural(res.analyzed_count, 'item')}, ${plural(res.theme_count, 'theme')}, ${plural(res.alert_count, 'alert')}.`;
        state.dashboard = null;
        state.analyzing = false;
        await refreshStatus().catch(() => {});
        await new Promise(r => setTimeout(r, 650));
        closeModal();
        toast('success', 'Analysis complete', `${plural(res.alert_count, 'priority alert')} across ${plural(res.theme_count, 'theme')}.`);
        go(after);
    } catch (err) {
        clearInterval(ticker);
        state.analyzing = false;
        items[current].dataset.state = 'error';
        items[current].querySelector('.dot').innerHTML = icon('x');
        $('#analysis-title', dialog).textContent = 'Analysis failed';
        $('#analysis-sub', dialog).textContent = err.message;
        const actions = $('#analysis-actions', dialog);
        actions.hidden = false;
        actions.innerHTML = `
            <button class="btn" type="button" data-choice="close">Close</button>
            <button class="btn btn-primary" type="button" data-choice="retry">Try again</button>`;
        actions.querySelector('[data-choice="retry"]').focus();
        actions.addEventListener('click', e => {
            const choice = e.target.closest('[data-choice]');
            if (!choice) return;
            closeModal();
            if (choice.dataset.choice === 'retry') runAnalysis({ useDemo, after });
        }, { once: true });
        await refreshStatus().catch(() => {});
    } finally {
        renderSessionPill();
        renderRail();
    }
}

async function tryDemo(after = '#/dashboard') {
    // If the demo is already analyzed, don't redo the work.
    const s = state.status;
    const demoOnly = s && s.sources.length === 1 && s.sources[0].type === 'demo';
    if (s && s.state === 'analyzed' && demoOnly) return go(after);
    await runAnalysis({ useDemo: true, after });
}

// -------------------------------------------------------------
// Dashboard
// -------------------------------------------------------------

function emptyState({ iconName = 'chart', title, body, actions = '' , small = false }) {
    return `
        <div class="empty ${small ? 'empty-sm' : ''}">
            <div class="empty-icon">${icon(iconName)}</div>
            <h2>${esc(title)}</h2>
            <p>${esc(body)}</p>
            ${actions ? `<div class="empty-actions">${actions}</div>` : ''}
        </div>`;
}

function noAnalysisState(context) {
    const s = state.status;
    if (s && s.state === 'ingested') {
        return emptyState({
            iconName: 'sparkles',
            title: `${plural(s.raw_count, 'item')} loaded, not analyzed yet`,
            body: `Run the analysis to ${context}.`,
            actions: `<button class="btn btn-primary" type="button" data-action="analyze-here">${icon('sparkles')} Run analysis</button>
                      <a class="btn" href="#/sources">Add more sources</a>`,
        });
    }
    return emptyState({
        iconName: 'chart',
        title: 'No analysis yet',
        body: `Load the demo dataset or connect a source to ${context}.`,
        actions: `<button class="btn btn-primary" type="button" data-action="try-demo-here">${icon('sparkles')} Load demo &amp; analyze</button>
                  <a class="btn" href="#/sources">Connect sources</a>`,
    });
}

function dashboardSkeleton() {
    const metric = `<div class="card metric"><div class="skeleton sk-line" style="width:50%"></div><div class="skeleton sk-title" style="height:28px;width:40%"></div></div>`;
    const block = `<div class="skeleton sk-block"></div>`;
    return `
        <div class="metrics">${metric.repeat(4)}</div>
        <div class="section"><div class="skeleton sk-title" style="width:180px"></div><div class="grid grid-2">${block.repeat(2)}</div></div>
        <div class="section"><div class="skeleton sk-title" style="width:140px"></div><div class="grid grid-3">${block.repeat(3)}</div></div>`;
}

async function loadDashboard() {
    const body = $('#dash-body');
    const meta = $('#run-meta');
    $('#dash-actions').hidden = true;

    if (!state.status) {
        body.innerHTML = dashboardSkeleton();
        try { await refreshStatus(); } catch (err) {
            body.innerHTML = emptyState({ iconName: 'alert', title: 'Couldn\'t load the dashboard', body: err.message,
                actions: `<button class="btn" type="button" data-action="reload-dashboard">${icon('refresh')} Try again</button>` });
            return;
        }
    }

    if (sessionState() !== 'analyzed') {
        meta.innerHTML = '';
        body.innerHTML = noAnalysisState('see themes, alerts and evidence here');
        return;
    }

    body.setAttribute('aria-busy', 'true');
    if (!state.dashboard) body.innerHTML = dashboardSkeleton();
    try {
        state.dashboard = await api(`/api/dashboard?time_filter=${encodeURIComponent(state.timeFilter)}`);
        renderDashboard();
    } catch (err) {
        if (err.status === 404) {
            await refreshStatus().catch(() => {});
            body.innerHTML = noAnalysisState('see themes, alerts and evidence here');
        } else {
            body.innerHTML = emptyState({ iconName: 'alert', title: 'Couldn\'t load the dashboard', body: err.message,
                actions: `<button class="btn" type="button" data-action="reload-dashboard">${icon('refresh')} Try again</button>` });
            toast('error', 'Dashboard failed to load', err.message);
        }
    } finally {
        body.setAttribute('aria-busy', 'false');
    }
}

function severityBadge(sev) {
    const s = String(sev || 'low').toLowerCase();
    return `<span class="badge sev sev-${esc(s)}">${esc(s)}</span>`;
}

function riskBadge(tag) {
    return RISK_LABELS[tag] ? `<span class="badge">${esc(RISK_LABELS[tag])}</span>` : '';
}

function trendBadge(trend, pct) {
    const t = String(trend || 'stable');
    if (t === 'stable') return `<span class="badge trend">Stable</span>`;
    if (t === 'new') return `<span class="badge trend trend-new">New</span>`;
    const n = Number(pct) || 0;
    const sign = n > 0 ? '+' : n < 0 ? '−' : '';
    return `<span class="badge trend trend-${esc(t)}">${esc(t[0].toUpperCase() + t.slice(1))} ${sign}${Math.abs(n)}%</span>`;
}

function sentimentMeter(value) {
    const tone = toneOf(value);
    const width = Math.max(8, Math.min(100, Math.abs(Number(value) || 0) * 100));
    const label = tone === 'negative' ? 'Negative' : tone === 'positive' ? 'Positive' : 'Mixed';
    return `<span class="sentiment" data-tone="${tone}" title="Average sentiment ${fmtSentiment(value)} (−1 to +1)">
        <span class="meter" aria-hidden="true"><i style="left:0;width:${width}%"></i></span>
        ${label} ${fmtSentiment(value)}
    </span>`;
}

function sparkline(timeBuckets, label) {
    const values = Object.keys(timeBuckets || {}).sort().map(k => timeBuckets[k]);
    if (!values.length) return '';
    const w = 96, h = 28, pad = 3;
    const pts = values.length === 1 ? [values[0], values[0]] : values;
    const max = Math.max(...pts, 1);
    const step = (w - pad * 2) / (pts.length - 1);
    const coords = pts.map((v, i) => [pad + i * step, h - pad - (v / max) * (h - pad * 2)]);
    const line = coords.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
    const area = `${line} L${coords[coords.length - 1][0].toFixed(1)} ${h} L${coords[0][0].toFixed(1)} ${h} Z`;
    const [lx, ly] = coords[coords.length - 1];
    return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(label)}: weekly mentions ${values.join(', ')}">
        <path class="area" d="${area}"/><path class="line" d="${line}"/><circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="2.5"/>
    </svg>`;
}

function barChart(entries, { colorVar = '--chart-1' } = {}) {
    if (!entries.length) return '<p class="rail-note">No data in this time range.</p>';
    const max = Math.max(...entries.map(([, v]) => v), 1);
    const colors = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-5'];
    return `<div class="bars">${entries.map(([label, value], i) => `
        <div class="bar-row">
            <span class="bar-label" title="${esc(label)}">${esc(label)}</span>
            <span class="bar-track" aria-hidden="true"><span class="bar-fill" style="display:block;width:${(value / max) * 100}%;background:var(${colorVar === 'multi' ? colors[i % colors.length] : colorVar})"></span></span>
            <span class="bar-num">${Number(value).toLocaleString()}</span>
        </div>`).join('')}</div>`;
}

function renderDashboard() {
    const d = state.dashboard;
    const stats = d.stats || {};
    const run = d.run_meta || {};
    const alerts = d.alerts || [];
    const themes = d.themes || [];
    const primaryThemes = themes.filter(t => !t.parent_theme_id);
    const sources = d.sources_connected || [];
    const mentions = stats.filtered_items ?? stats.total_items ?? 0;
    const complaints = stats.complaint_count || 0;
    const criticalCount = alerts.filter(a => a.severity === 'critical').length;
    const isDemo = sources.length > 0 && sources.every(s => s.type === 'demo');

    $('#dash-actions').hidden = false;
    $('#run-meta').innerHTML = `
        <span>${icon('clock')} Analyzed ${esc(timeAgo(run.analyzed_at) || 'recently')}</span>
        <span>${icon('database')} ${plural(stats.total_items || 0, 'item')}</span>
        <span>${icon('layers')} ${plural(sources.length, 'source')}${isDemo ? ' · demo data' : ''}</span>`;

    const filterLabel = { all: 'all time', '7d': 'the last 7 days', '24h': 'the last 24 hours' }[state.timeFilter];
    const topAlert = alerts[0];
    const breakdown = Object.entries(d.source_breakdown || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => [sourceLabel(k), v]);

    $('#dash-body').innerHTML = `
        <div class="toolbar">
            <div class="segmented" role="group" aria-label="Time range" data-control="time">
                ${[['all', 'All time'], ['7d', '7 days'], ['24h', '24 hours']].map(([v, l]) =>
                    `<button type="button" data-value="${v}" aria-pressed="${state.timeFilter === v}">${l}</button>`).join('')}
            </div>
            <span class="count">Showing ${plural(mentions, 'item')} from ${filterLabel}</span>
        </div>

        <div class="metrics">
            <div class="card metric">
                <div class="metric-label">Mentions</div>
                <div class="metric-value">${Number(mentions).toLocaleString()}</div>
                <div class="metric-sub">${state.timeFilter === 'all' ? `${(stats.window_counts || {}).mentions_7d || 0} in the last 7 days` : `of ${stats.total_items || 0} total`}</div>
            </div>
            <div class="card metric">
                <div class="metric-label">Complaints</div>
                <div class="metric-value">${Number(complaints).toLocaleString()}</div>
                <div class="metric-sub">${mentions ? Math.round((complaints / mentions) * 100) : 0}% negative or urgent</div>
            </div>
            <div class="card metric ${criticalCount ? 'is-alert' : ''}">
                <div class="metric-label">Priority alerts</div>
                <div class="metric-value">${alerts.length}</div>
                <div class="metric-sub">${criticalCount ? `${criticalCount} critical` : 'None critical'}</div>
            </div>
            <div class="card metric">
                <div class="metric-label">Themes</div>
                <div class="metric-value">${primaryThemes.length}</div>
                <div class="metric-sub">${themes.length - primaryThemes.length} sub-patterns</div>
            </div>
        </div>

        <div class="brief">
            <div class="card brief-main">
                <p class="eyebrow">Top priority</p>
                ${topAlert ? `
                    <h2>${esc(topAlert.title)}</h2>
                    <p>${esc(topAlert.suggested_action || topAlert.description)}</p>
                    <div class="brief-tags">${severityBadge(topAlert.severity)}${riskBadge(topAlert.risk_tag)}<span class="badge">${plural(topAlert.evidence_count || 0, 'report')}</span></div>
                ` : `<h2>No urgent risks detected</h2><p>None of the themes crossed the alert threshold in this run.</p>`}
            </div>
            <div class="card card-pad">
                <h2 class="section-title" style="font-size:var(--text-md)">Feedback by source</h2>
                ${barChart(breakdown, { colorVar: 'multi' })}
            </div>
        </div>

        <section class="section" aria-labelledby="alerts-h">
            <div class="section-head">
                <h2 id="alerts-h" class="section-title">Priority alerts <span class="count">${alerts.length}</span></h2>
                <p>Ranked by severity, then risk score. Based on all-time data.</p>
            </div>
            ${alerts.length ? `<div class="grid grid-2">${alerts.map(a => `
                <a class="card card-interactive alert-card" data-severity="${esc(a.severity)}" ${a.theme_id ? `href="#/theme/${encodeURIComponent(a.theme_id)}"` : ''}>
                    <div class="alert-top">${severityBadge(a.severity)}${riskBadge(a.risk_tag)}<span class="score">Risk score ${a.risk_score || 0}</span></div>
                    <h3>${esc(a.title)}</h3>
                    <p>${esc(a.description)}</p>
                    <div class="alert-action"><strong>Suggested action:</strong> ${esc(a.suggested_action)}</div>
                    ${a.theme_id ? `<span class="card-link">View ${plural(a.evidence_count || 0, 'report')} ${icon('arrow-right')}</span>` : ''}
                </a>`).join('')}</div>`
            : emptyState({ iconName: 'check', title: 'No alerts', body: 'No theme crossed the alert threshold. That\'s good news.', small: true })}
        </section>

        <section class="section" aria-labelledby="themes-h">
            <div class="section-head">
                <h2 id="themes-h" class="section-title">Themes <span class="count" id="theme-count"></span></h2>
                <div class="segmented" role="group" aria-label="Theme type" data-control="scope">
                    ${[['all', 'All'], ['primary', 'Core'], ['pattern', 'Sub-patterns']].map(([v, l]) =>
                        `<button type="button" data-value="${v}" aria-pressed="${state.themeScope === v}">${l}</button>`).join('')}
                </div>
            </div>
            <div id="themes-grid"></div>
        </section>

        <section class="section" aria-labelledby="feed-h">
            <div class="section-head">
                <h2 id="feed-h" class="section-title">Evidence</h2>
                <p>Individual feedback behind the analysis.</p>
            </div>
            <div class="feed-filters">
                <div class="search">
                    ${icon('search')}
                    <label class="visually-hidden" for="feed-q">Search feedback</label>
                    <input class="input" id="feed-q" type="search" placeholder="Search feedback…" value="${esc(state.feed.q)}" autocomplete="off">
                </div>
                <label class="visually-hidden" for="feed-source">Filter by source</label>
                <select class="select" id="feed-source" data-feed="source"></select>
                <label class="visually-hidden" for="feed-bucket">Filter by theme</label>
                <select class="select" id="feed-bucket" data-feed="bucket"></select>
                <label class="visually-hidden" for="feed-tone">Filter by sentiment</label>
                <select class="select" id="feed-tone" data-feed="tone">
                    <option value="">Any sentiment</option>
                    <option value="negative">Negative</option>
                    <option value="mixed">Neutral / mixed</option>
                    <option value="positive">Positive</option>
                </select>
            </div>
            <div class="card" id="feed"></div>
        </section>`;

    renderThemes();
    populateFeedFilters();
    renderFeed();
}

function renderThemes() {
    const themes = (state.dashboard.themes || []).filter(t => {
        if (state.themeScope === 'primary') return !t.parent_theme_id;
        if (state.themeScope === 'pattern') return Boolean(t.parent_theme_id);
        return true;
    });
    $('#theme-count').textContent = themes.length;
    const grid = $('#themes-grid');
    if (!themes.length) {
        grid.innerHTML = emptyState({ iconName: 'layers', title: 'No themes here', body: state.themeScope === 'pattern'
            ? 'Sub-patterns appear when several items share a specific phrase. Try "All".'
            : 'No themes have feedback in this time range. Try a wider range.', small: true });
        return;
    }
    grid.innerHTML = `<div class="grid grid-3">${themes.map(t => {
        const win = t.window_counts || {};
        return `
        <a class="card card-interactive theme-card" href="#/theme/${encodeURIComponent(t.theme_id)}">
            <div class="theme-top">
                <h3>${esc(t.label)}</h3>
                <div class="theme-count">${Number(t.count || 0).toLocaleString()}<small>mentions</small></div>
            </div>
            <div class="theme-tags">
                ${t.parent_theme_id ? '<span class="badge badge-outline">Sub-pattern</span>' : ''}
                ${riskBadge(t.risk_tag)}
                ${trendBadge(t.trend, t.trend_pct)}
            </div>
            <div class="theme-foot">
                <div style="display:grid;gap:6px">
                    ${sentimentMeter(t.avg_sentiment)}
                    <div class="theme-meta-row"><span>24h: ${win.mentions_24h || 0}</span><span>7d: ${win.mentions_7d || 0}</span><span>Urgency ${t.avg_urgency}/5</span></div>
                </div>
                ${sparkline(t.time_buckets, t.label)}
            </div>
        </a>`;
    }).join('')}</div>`;
}

function populateFeedFilters() {
    const items = state.dashboard.recent_items || [];
    const sources = [...new Set(items.map(i => i.source || 'unknown'))].sort();
    const buckets = [...new Set(items.map(i => i.core_bucket || 'Other'))].sort();
    if (!sources.includes(state.feed.source)) state.feed.source = '';
    if (!buckets.includes(state.feed.bucket)) state.feed.bucket = '';
    $('#feed-source').innerHTML = `<option value="">All sources</option>` +
        sources.map(s => `<option value="${esc(s)}" ${s === state.feed.source ? 'selected' : ''}>${esc(sourceLabel(s))}</option>`).join('');
    $('#feed-bucket').innerHTML = `<option value="">All themes</option>` +
        buckets.map(b => `<option value="${esc(b)}" ${b === state.feed.bucket ? 'selected' : ''}>${esc(b)}</option>`).join('');
    $('#feed-tone').value = state.feed.tone;
}

function highlight(text, q) {
    const safe = esc(text);
    if (!q) return safe;
    const pattern = new RegExp(`(${esc(q).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return safe.replace(pattern, '<mark>$1</mark>');
}

function urgencyMeter(level) {
    const n = Math.max(1, Math.min(5, Number(level) || 3));
    return `<span class="urgency" data-level="${n}" title="Urgency ${n} of 5" aria-label="Urgency ${n} of 5">${
        [1, 2, 3, 4, 5].map(i => `<i class="${i <= n ? 'on' : ''}"></i>`).join('')}</span>`;
}

function feedItem(item, q = '') {
    const tone = toneOf(item.sentiment);
    const toneBadge = tone === 'negative' ? '<span class="badge" style="background:var(--negative-bg);color:var(--negative)">Negative</span>'
        : tone === 'positive' ? '<span class="badge" style="background:var(--positive-bg);color:var(--positive)">Positive</span>' : '';
    return `
        <li class="feed-item">
            <p class="feed-text">${highlight(item.text || item.summary || '', q)}</p>
            <div class="feed-meta">
                <span class="badge badge-outline">${esc(item.core_bucket || 'Other')}</span>
                ${toneBadge}
                ${riskBadge(item.risk_tag)}
                ${urgencyMeter(item.urgency)}
                <span class="sep">·</span><span>${esc(sourceLabel(item.source))}</span>
                ${item.rating ? `<span class="sep">·</span><span aria-label="${item.rating} star rating">${Math.max(0, Math.min(5, item.rating))}★</span>` : ''}
                ${shortDate(item.date) ? `<span class="sep">·</span><span>${esc(shortDate(item.date))}</span>` : ''}
            </div>
        </li>`;
}

function renderFeed() {
    const all = state.dashboard.recent_items || [];
    const { q, source, bucket, tone } = state.feed;
    const needle = q.trim().toLowerCase();
    const rows = all.filter(i =>
        (!source || (i.source || 'unknown') === source) &&
        (!bucket || (i.core_bucket || 'Other') === bucket) &&
        (!tone || toneOf(i.sentiment) === tone) &&
        (!needle || `${i.text} ${i.summary}`.toLowerCase().includes(needle)));
    const feed = $('#feed');
    if (!all.length) {
        feed.innerHTML = emptyState({ iconName: 'file', title: 'No feedback in this range', body: 'Try a wider time range.', small: true });
        return;
    }
    feed.innerHTML = rows.length
        ? `<ul class="feed">${rows.slice(0, 60).map(i => feedItem(i, needle)).join('')}</ul>`
        : `<div class="card-pad">${emptyState({ iconName: 'search', title: 'No matches', body: 'No feedback matches these filters.', actions: '<button class="btn btn-sm" type="button" data-action="reset-feed">Reset filters</button>', small: true })}</div>`;
    feed.insertAdjacentHTML('beforeend', `<div class="feed-footer"><span>Showing ${Math.min(rows.length, 60)} of ${plural(all.length, 'item')}</span><span>Newest first</span></div>`);
}

async function exportComplaints(btn) {
    setButtonBusy(btn, true, 'Exporting…');
    try {
        const res = await fetch('/api/export/complaints.csv');
        if (!res.ok) {
            let msg = 'Export failed.';
            try { msg = (await res.json()).detail || msg; } catch (_) {}
            throw new Error(msg);
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'rivyu-complaints.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        toast('success', 'Export ready', 'Negative and urgent items saved as CSV.');
    } catch (err) {
        toast('error', 'Couldn\'t export', err.message);
    } finally {
        setButtonBusy(btn, false);
    }
}

// -------------------------------------------------------------
// Theme detail
// -------------------------------------------------------------

async function loadTheme(themeId) {
    const body = $('#theme-body');
    body.innerHTML = `<div class="skeleton sk-title" style="width:40%;height:28px"></div>${dashboardSkeleton()}`;
    try {
        const t = await api(`/api/theme/${encodeURIComponent(themeId)}`);
        renderTheme(t);
    } catch (err) {
        body.innerHTML = err.status === 404
            ? emptyState({ iconName: 'layers', title: 'Theme not found', body: 'It may belong to an older analysis. Open the dashboard to see current themes.',
                actions: '<a class="btn btn-primary" href="#/dashboard">Go to dashboard</a>' })
            : emptyState({ iconName: 'alert', title: 'Couldn\'t load this theme', body: err.message,
                actions: `<button class="btn" type="button" data-action="reload-theme">${icon('refresh')} Try again</button>` });
    }
}

function renderTheme(t) {
    document.title = `${t.label || 'Theme'} · Rivyu`;
    const items = [...(t.items || [])].sort((a, b) => (b.urgency || 0) - (a.urgency || 0));
    const sources = {};
    items.forEach(i => { const k = sourceLabel(i.source); sources[k] = (sources[k] || 0) + 1; });
    const weeks = Object.keys(t.time_buckets || {}).sort();
    const maxWeek = Math.max(...weeks.map(w => t.time_buckets[w]), 1);

    $('#theme-body').innerHTML = `
        <div class="page-header">
            <div>
                <p class="eyebrow">${esc(t.core_bucket || 'Theme')}</p>
                <h1 id="theme-title">${esc(t.label || t.theme_id)}</h1>
                <div class="brief-tags">${riskBadge(t.risk_tag)}${trendBadge(t.trend, t.trend_pct)}${t.parent_theme_id ? '<span class="badge badge-outline">Sub-pattern</span>' : ''}</div>
            </div>
            <div class="page-actions"><a class="btn btn-primary" href="#/ask">${icon('chat')} Ask about this</a></div>
        </div>

        <div class="metrics">
            <div class="card metric"><div class="metric-label">Mentions</div><div class="metric-value">${t.count || items.length}</div></div>
            <div class="card metric"><div class="metric-label">Avg sentiment</div><div class="metric-value" style="color:var(--${toneOf(t.avg_sentiment) === 'mixed' ? 'text' : toneOf(t.avg_sentiment)})">${fmtSentiment(t.avg_sentiment)}</div><div class="metric-sub">Scale −1 to +1</div></div>
            <div class="card metric"><div class="metric-label">Avg urgency</div><div class="metric-value">${t.avg_urgency}<span class="count">/5</span></div></div>
            <div class="card metric"><div class="metric-label">Sources</div><div class="metric-value">${Object.keys(sources).length}</div></div>
        </div>

        <div class="brief">
            <div class="card card-pad">
                <h2 style="font-size:var(--text-md)">Weekly mentions</h2>
                ${weeks.length ? `<div class="timeline" role="img" aria-label="Weekly mentions: ${weeks.map(w => `${w} ${t.time_buckets[w]}`).join(', ')}">
                    ${weeks.map(w => `<div class="timeline-col"><b>${t.time_buckets[w]}</b><div class="timeline-bar" style="height:${(t.time_buckets[w] / maxWeek) * 90}px"></div><span>${esc(w.split('-')[1] || w)}</span></div>`).join('')}
                </div>` : '<p class="rail-note">No dated items in this theme.</p>'}
            </div>
            <div class="card card-pad">
                <h2 style="font-size:var(--text-md)">By source</h2>
                ${barChart(Object.entries(sources).sort((a, b) => b[1] - a[1]), { colorVar: 'multi' })}
            </div>
        </div>

        <section class="section" aria-labelledby="theme-items-h">
            <div class="section-head">
                <h2 id="theme-items-h" class="section-title">Feedback <span class="count">${items.length}</span></h2>
                <p>Most urgent first.</p>
            </div>
            <div class="card"><ul class="feed">${items.map(i => feedItem(i)).join('')}</ul></div>
        </section>`;
}

// -------------------------------------------------------------
// Ask Rivyu
// -------------------------------------------------------------

function renderAsk() {
    const st = sessionState();
    const empty = $('#ask-empty');
    const chat = $('#chat');

    if (!state.status) {
        empty.innerHTML = `<div class="card card-pad"><div class="skeleton sk-title"></div><div class="skeleton sk-line"></div><div class="skeleton sk-line" style="width:70%"></div></div>`;
        chat.hidden = true;
        return;
    }
    if (st !== 'analyzed') {
        chat.hidden = true;
        empty.innerHTML = noAnalysisState('ask questions about it');
        empty.querySelector('[data-action="try-demo-here"]')?.setAttribute('data-after', '#/ask');
        empty.querySelector('[data-action="analyze-here"]')?.setAttribute('data-after', '#/ask');
        return;
    }

    empty.innerHTML = '';
    chat.hidden = false;
    if (!state.chatStarted) {
        state.chatStarted = true;
        const s = state.status;
        addMessage('bot', `I've analyzed **${plural(s.processed_count, 'feedback item')}** from ${plural(s.sources.length, 'source')}. Ask me about priorities, risks or what's changing. You can also pick a suggestion below.`);
    }
    setTimeout(() => $('#ask-input').focus(), 50);
}

function formatAnswer(text) {
    const lines = esc(text || '').split('\n');
    const html = [];
    let list = null;
    const inline = s => s
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
    const closeList = () => { if (list) { html.push(`</${list}>`); list = null; } };

    for (const raw of lines) {
        const line = raw.trim();
        let m;
        if (!line) { closeList(); continue; }
        if ((m = line.match(/^#{1,2}\s+(.*)$/))) { closeList(); html.push(`<h3>${inline(m[1])}</h3>`); continue; }
        if ((m = line.match(/^#{3,6}\s+(.*)$/))) { closeList(); html.push(`<h4>${inline(m[1])}</h4>`); continue; }
        if ((m = line.match(/^[-*•]\s+(.*)$/))) {
            if (list !== 'ul') { closeList(); html.push('<ul>'); list = 'ul'; }
            html.push(`<li>${inline(m[1])}</li>`); continue;
        }
        if ((m = line.match(/^\d+[.)]\s+(.*)$/))) {
            if (list !== 'ol') { closeList(); html.push('<ol>'); list = 'ol'; }
            html.push(`<li>${inline(m[1])}</li>`); continue;
        }
        closeList();
        html.push(`<p>${inline(line)}</p>`);
    }
    closeList();
    return html.join('') || '<p>No answer.</p>';
}

function addMessage(role, text, { error = false, retry = null, copy = false } = {}) {
    const log = $('#chat-log');
    const el = document.createElement('div');
    el.className = `msg msg-${role}`;
    const avatar = role === 'bot' ? icon('logo') : 'You';
    el.innerHTML = `
        <div class="msg-avatar" aria-hidden="true">${avatar}</div>
        <div style="min-width:0;display:flex;flex-direction:column;${role === 'user' ? 'align-items:flex-end' : ''}">
            <span class="visually-hidden">${role === 'bot' ? 'Rivyu said:' : 'You said:'}</span>
            <div class="bubble ${error ? 'is-error' : ''}">${role === 'bot' ? formatAnswer(text) : `<p>${esc(text)}</p>`}</div>
            ${copy || retry ? `<div class="msg-tools">
                ${copy ? `<button class="copy-btn" type="button" data-copy>${icon('copy')} Copy</button>` : ''}
                ${retry ? `<button class="copy-btn" type="button" data-retry>${icon('refresh')} Try again</button>` : ''}
            </div>` : ''}
        </div>`;
    if (copy) el.querySelector('[data-copy]').addEventListener('click', e => copyText(text, e.currentTarget));
    if (retry) el.querySelector('[data-retry]').addEventListener('click', () => { el.remove(); retry(); });
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
}

async function copyText(text, btn) {
    try {
        await navigator.clipboard.writeText(text);
    } catch (_) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (__) { /* ignore */ }
        ta.remove();
    }
    const original = btn.innerHTML;
    btn.innerHTML = `${icon('check')} Copied`;
    setTimeout(() => { btn.innerHTML = original; }, 1500);
}

function setAsking(busy) {
    state.asking = busy;
    $('#ask-send').disabled = busy;
    $$('#suggestions .chip').forEach(c => { c.disabled = busy; });
}

async function ask(question) {
    const q = question.trim();
    if (!q || state.asking) return;
    addMessage('user', q);
    const input = $('#ask-input');
    input.value = '';
    autosize(input);
    setAsking(true);

    const typing = document.createElement('div');
    typing.className = 'msg msg-bot';
    typing.innerHTML = `<div class="msg-avatar" aria-hidden="true">${icon('logo')}</div><div class="bubble"><span class="typing" aria-label="Rivyu is typing"><i></i><i></i><i></i></span></div>`;
    $('#chat-log').appendChild(typing);
    $('#chat-log').scrollTop = $('#chat-log').scrollHeight;

    try {
        const res = await api('/api/ask', { method: 'POST', body: { question: q }, timeout: 90000 });
        typing.remove();
        addMessage('bot', res.answer, { copy: true });
    } catch (err) {
        typing.remove();
        addMessage('bot', err.message, { error: true, retry: () => ask(q) });
    } finally {
        setAsking(false);
        input.focus();
    }
}

function autosize(ta) {
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 140)}px`;
}

// -------------------------------------------------------------
// Theme (light / dark / system)
// -------------------------------------------------------------

const THEME_CYCLE = ['system', 'light', 'dark'];

function currentThemePref() {
    return document.documentElement.dataset.theme || 'system';
}

function applyThemePref(pref) {
    if (pref === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = pref;
    try {
        if (pref === 'system') localStorage.removeItem('rivyu-theme');
        else localStorage.setItem('rivyu-theme', pref);
    } catch (_) { /* storage may be blocked */ }
    const btn = $('#theme-toggle');
    const iconName = pref === 'light' ? 'sun' : pref === 'dark' ? 'moon' : 'monitor';
    btn.innerHTML = icon(iconName);
    btn.setAttribute('aria-label', `Color theme: ${pref}. Click to change.`);
    btn.title = `Theme: ${pref}`;
}

// -------------------------------------------------------------
// Event wiring
// -------------------------------------------------------------

function wireEvents() {
    window.addEventListener('hashchange', route);

    document.addEventListener('click', e => {
        const el = e.target.closest('[data-action]');
        if (!el) return;
        const action = el.dataset.action;
        if (action === 'try-demo') tryDemo('#/dashboard');
        else if (action === 'try-demo-here') tryDemo(el.dataset.after || '#/dashboard');
        else if (action === 'analyze') runAnalysis({ after: '#/dashboard' });
        else if (action === 'analyze-here') runAnalysis({ after: el.dataset.after || '#/dashboard' });
        else if (action === 'clear') clearSession();
        else if (action === 'export') exportComplaints(el);
        else if (action === 'reload-dashboard') { state.dashboard = null; loadDashboard(); }
        else if (action === 'reload-theme') route();
        else if (action === 'reset-feed') {
            state.feed = { q: '', source: '', bucket: '', tone: '' };
            $('#feed-q').value = '';
            populateFeedFilters();
            renderFeed();
        }
    });

    // Source forms
    $$('form.source-card').forEach(form => {
        form.addEventListener('submit', e => { e.preventDefault(); submitSource(form); });
        form.addEventListener('input', e => {
            if (e.target.getAttribute('aria-invalid') === 'true') setFieldError(e.target, '');
        });
    });

    const csvInput = $('#csv-file');
    const drop = $('#csv-drop');
    csvInput.addEventListener('change', () => {
        $('#csv-file-name').textContent = csvInput.files[0] ? csvInput.files[0].name : 'Choose a file or drop it here';
        setFieldError(csvInput, '');
    });
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, () => drop.classList.add('dragover')));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, () => drop.classList.remove('dragover')));

    const helpToggle = $('#csv-help-toggle');
    helpToggle.addEventListener('click', () => {
        const panel = $('#csv-help');
        panel.hidden = !panel.hidden;
        helpToggle.setAttribute('aria-expanded', String(!panel.hidden));
        helpToggle.textContent = panel.hidden ? 'Expected format' : 'Hide format';
    });

    // Dashboard controls (delegated because the dashboard re-renders)
    $('#dash-body').addEventListener('click', e => {
        const btn = e.target.closest('.segmented button');
        if (!btn) return;
        const control = btn.closest('.segmented').dataset.control;
        if (control === 'time' && state.timeFilter !== btn.dataset.value) {
            state.timeFilter = btn.dataset.value;
            loadDashboard();
        } else if (control === 'scope' && state.themeScope !== btn.dataset.value) {
            state.themeScope = btn.dataset.value;
            $$('[data-control="scope"] button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
            renderThemes();
        }
    });
    let searchTimer;
    $('#dash-body').addEventListener('input', e => {
        if (e.target.id === 'feed-q') {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => { state.feed.q = e.target.value; renderFeed(); }, 120);
        }
    });
    $('#dash-body').addEventListener('change', e => {
        const key = e.target.dataset.feed;
        if (key) { state.feed[key] = e.target.value; renderFeed(); }
    });

    // Ask
    $('#ask-form').addEventListener('submit', e => { e.preventDefault(); ask($('#ask-input').value); });
    $('#ask-input').addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(e.target.value); }
    });
    $('#ask-input').addEventListener('input', e => autosize(e.target));
    $('#suggestions').addEventListener('click', e => {
        const chip = e.target.closest('.chip');
        if (chip) ask(chip.textContent);
    });

    // Theme toggle
    $('#theme-toggle').addEventListener('click', () => {
        const next = THEME_CYCLE[(THEME_CYCLE.indexOf(currentThemePref()) + 1) % THEME_CYCLE.length];
        applyThemePref(next);
    });
}

// -------------------------------------------------------------
// Boot
// -------------------------------------------------------------

async function boot() {
    applyThemePref(currentThemePref());
    wireEvents();
    renderSessionPill();
    route();

    // On a cold start the backend may answer with errors for a while;
    // keep retrying for ~90s with the wake banner visible.
    const started = Date.now();
    for (let attempt = 0; ; attempt++) {
        try {
            await refreshStatus();
            break;
        } catch (err) {
            const retryable = !err.status || err.status >= 502;
            if (!retryable || Date.now() - started > 90000) {
                showWake(false);
                toast('error', 'Can\'t reach the server', err.message, 0);
                break;
            }
            showWake(true);
            await new Promise(r => setTimeout(r, Math.min(2000 + attempt * 1000, 6000)));
        }
    }

    // Re-render whichever page is open now that we know the real state.
    const { name } = parseRoute();
    if (name === 'dashboard') loadDashboard();
    if (name === 'ask') renderAsk();
}

boot();
