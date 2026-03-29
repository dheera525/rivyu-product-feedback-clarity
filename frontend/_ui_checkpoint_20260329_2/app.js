// ============================
// Rivyu — Frontend Logic
// ============================

const API = '';  // same origin

let totalIngested = 0;
let connectedSources = [];
let currentTimeFilter = 'all';
let currentThemeScope = 'all';
const SAFE_MAX_PLAYSTORE = 300;
const SAFE_MAX_REDDIT = 300;

// --- Navigation ---

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => showPage(btn.dataset.page));
});

function showPage(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const page = document.getElementById(`page-${name}`);
    if (page) page.classList.add('active');

    const navBtn = document.querySelector(`.nav-btn[data-page="${name}"]`);
    if (navBtn) navBtn.classList.add('active');

    if (name === 'dashboard') refreshDashboard();
    if (name === 'ask') {
        setTimeout(() => {
            const askInput = document.getElementById('ask-input');
            if (askInput) askInput.focus();
        }, 120);
    }
}

// --- Ingestion ---

async function ingestPlayStore() {
    const appId = document.getElementById('gp-app-id').value.trim();
    const requestedCount = parseInt(document.getElementById('gp-count').value) || 50;
    const count = Math.max(10, Math.min(requestedCount, SAFE_MAX_PLAYSTORE));
    const status = document.getElementById('gp-status');

    if (!appId) { status.textContent = 'Enter an app ID'; status.className = 'source-status error'; return; }

    status.textContent = 'Fetching reviews...'; status.className = 'source-status loading';

    try {
        const res = await fetch(`${API}/api/ingest/playstore`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ app_id: appId, count })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');
        status.textContent = `Fetched ${data.count} reviews`; status.className = 'source-status success';
        onSourceAdded('google_play', appId, data.count);
    } catch (e) {
        status.textContent = `Error: ${e.message}`; status.className = 'source-status error';
    }
}

async function ingestReddit() {
    const sub = document.getElementById('reddit-sub').value.trim();
    const query = document.getElementById('reddit-query').value.trim();
    const requestedCount = parseInt(document.getElementById('reddit-count').value) || 50;
    const count = Math.max(10, Math.min(requestedCount, SAFE_MAX_REDDIT));
    const status = document.getElementById('reddit-status');

    if (!sub) { status.textContent = 'Enter a subreddit'; status.className = 'source-status error'; return; }

    status.textContent = 'Fetching posts...'; status.className = 'source-status loading';

    try {
        const res = await fetch(`${API}/api/ingest/reddit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subreddit: sub, query, count })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');
        status.textContent = `Fetched ${data.count} posts`; status.className = 'source-status success';
        onSourceAdded('reddit', `r/${sub}`, data.count);
    } catch (e) {
        status.textContent = `Error: ${e.message}`; status.className = 'source-status error';
    }
}

async function ingestCSV() {
    const fileInput = document.getElementById('csv-file');
    const status = document.getElementById('csv-status');
    if (!fileInput.files.length) { status.textContent = 'Select a file'; status.className = 'source-status error'; return; }

    status.textContent = 'Uploading...'; status.className = 'source-status loading';

    const form = new FormData();
    form.append('file', fileInput.files[0]);

    try {
        const res = await fetch(`${API}/api/ingest/csv`, { method: 'POST', body: form });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');
        status.textContent = `Parsed ${data.count} items`; status.className = 'source-status success';
        onSourceAdded('csv', fileInput.files[0].name, data.count);
    } catch (e) {
        status.textContent = `Error: ${e.message}`; status.className = 'source-status error';
    }
}

async function loadDemo() {
    const status = document.getElementById('demo-status');
    status.textContent = 'Loading demo data...'; status.className = 'source-status loading';

    try {
        const res = await fetch(`${API}/api/ingest/demo`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');
        status.textContent = `Loaded ${data.count} demo items`; status.className = 'source-status success';
        onSourceAdded('demo', 'demo_dataset', data.count);
    } catch (e) {
        status.textContent = `Error: ${e.message}`; status.className = 'source-status error';
    }
}

function onSourceAdded(type, id, count) {
    // Demo load is a full reset dataset; other sources stack together.
    if (type === 'demo') {
        totalIngested = count;
        connectedSources = [{ type, id, count }];
    } else {
        const existing = connectedSources.find(s => s.type === type && s.id === id);
        if (existing) {
            existing.count += count;
        } else {
            connectedSources.push({ type, id, count });
        }
        totalIngested = connectedSources.reduce((sum, s) => sum + (s.count || 0), 0);
    }
    updateSourcesSummary();
    clearDashboardView();
}

function updateSourcesSummary() {
    const summary = document.getElementById('sources-summary');
    const list = document.getElementById('sources-list');
    const total = document.getElementById('total-count');
    const analyzeBtn = document.getElementById('analyze-btn');

    summary.classList.remove('hidden');
    list.innerHTML = connectedSources.map(s =>
        `<span class="source-tag">${s.type === 'google_play' ? '📱' : s.type === 'reddit' ? '🔍' : s.type === 'csv' ? '📄' : '🎯'} ${s.id} (${s.count})</span>`
    ).join('');
    total.textContent = totalIngested;
    analyzeBtn.disabled = totalIngested === 0;
}

function clearDashboardView() {
    document.getElementById('stats-bar').innerHTML = '<div class="no-data">A new source is loaded. Run analysis to view updated results.</div>';
    document.getElementById('alerts-grid').innerHTML = '<div class="no-data">Run analysis to generate priority alerts.</div>';
    document.getElementById('themes-grid').innerHTML = '<div class="no-data">Run analysis to map core themes.</div>';
    document.getElementById('evidence-list').innerHTML = '<div class="no-data">Run analysis to surface source-linked evidence.</div>';
}

async function resetSession() {
    try {
        await fetch(`${API}/api/reset`, { method: 'POST' });
    } catch (e) {
        // Continue clearing local state even if backend reset fails.
    }

    totalIngested = 0;
    connectedSources = [];
    document.getElementById('sources-summary').classList.add('hidden');
    document.getElementById('total-count').textContent = '0';
    document.getElementById('analyze-btn').disabled = true;
    ['gp-status', 'reddit-status', 'csv-status', 'demo-status'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = '';
            el.className = 'source-status';
        }
    });
    clearDashboardView();
    showPage('sources');
}

// --- Analysis ---

async function runAnalysis() {
    showPage('loading');

    const steps = ['ingest', 'classify', 'themes', 'trends', 'alerts'];
    const stageText = {
        ingest: 'Stage 1/5: Preparing data',
        classify: 'Stage 2/5: Classifying signals',
        themes: 'Stage 3/5: Grouping themes',
        trends: 'Stage 4/5: Computing trends',
        alerts: 'Stage 5/5: Finalizing alerts'
    };
    const stageCaption = {
        ingest: 'Normalizing source data for a consistent run.',
        classify: 'Scoring sentiment, urgency, and category signals.',
        themes: 'Grouping repeated feedback into clear themes.',
        trends: 'Calculating movement across 24h and 7d windows.',
        alerts: 'Compiling high-priority issues for review.'
    };
    let currentStep = 0;

    function advanceStep() {
        if (currentStep > 0) {
            const prev = document.getElementById(`step-${steps[currentStep - 1]}`);
            prev.classList.remove('active');
            prev.classList.add('done');
            prev.querySelector('.step-icon').textContent = '✅';
        }
        if (currentStep < steps.length) {
            const curr = document.getElementById(`step-${steps[currentStep]}`);
            curr.classList.add('active');
            curr.querySelector('.step-icon').textContent = '🔄';
            document.getElementById('loading-title').textContent = stageText[steps[currentStep]];
            const fill = document.getElementById('loading-progress-fill');
            const caption = document.getElementById('loading-stage-caption');
            if (fill) fill.style.width = `${Math.round(((currentStep + 1) / steps.length) * 100)}%`;
            if (caption) caption.textContent = stageCaption[steps[currentStep]];
            currentStep++;
        }
    }

    // Simulate step progress
    advanceStep();
    const stepInterval = setInterval(() => {
        if (currentStep < steps.length) advanceStep();
    }, 1200);

    try {
        const useDemoIfEmpty = totalIngested === 0;
        const res = await fetch(`${API}/api/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ use_demo: useDemoIfEmpty })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Analysis failed');

        clearInterval(stepInterval);

        // Complete all remaining steps
        for (let i = currentStep - 1; i < steps.length; i++) {
            const el = document.getElementById(`step-${steps[i]}`);
            el.classList.remove('active');
            el.classList.add('done');
            el.querySelector('.step-icon').textContent = '✅';
        }

        document.getElementById('loading-title').textContent = `Analysis complete (${data.analyzed_count || data.stats?.total_items || 0} items)`;
        const caption = document.getElementById('loading-stage-caption');
        const fill = document.getElementById('loading-progress-fill');
        if (fill) fill.style.width = '100%';
        if (caption) caption.textContent = 'Finalizing dashboard output...';

        setTimeout(() => {
            // Reset loading state for next run
            steps.forEach(s => {
                const el = document.getElementById(`step-${s}`);
                el.classList.remove('active', 'done');
                el.querySelector('.step-icon').textContent = '⏳';
            });
            document.getElementById('loading-title').textContent = 'Analyzing feedback...';
            const resetCaption = document.getElementById('loading-stage-caption');
            const resetFill = document.getElementById('loading-progress-fill');
            if (resetFill) resetFill.style.width = '0%';
            if (resetCaption) resetCaption.textContent = 'Preparing analysis context...';
            showPage('dashboard');
        }, 1200);
    } catch (e) {
        clearInterval(stepInterval);
        document.getElementById('loading-title').textContent = `Error: ${e.message}`;
        const caption = document.getElementById('loading-stage-caption');
        if (caption) caption.textContent = 'Returning to source selection...';
        setTimeout(() => showPage('sources'), 3000);
    }
}

// --- Time Filter ---

function setTimeFilter(filter) {
    currentTimeFilter = filter;
    document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.time-btn[data-filter="${filter}"]`).classList.add('active');
    refreshDashboard();
}

function setThemeScope(scope) {
    currentThemeScope = scope;
    document.querySelectorAll('.theme-scope-btn').forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector(`.theme-scope-btn[data-theme-scope="${scope}"]`);
    if (activeBtn) activeBtn.classList.add('active');
    refreshDashboard();
}

// --- Dashboard ---

async function refreshDashboard() {
    try {
        document.getElementById('stats-bar').innerHTML = '<div class="no-data">Loading session dashboard...</div>';
        const res = await fetch(`${API}/api/dashboard?time_filter=${currentTimeFilter}`);
        if (!res.ok) {
            const err = await res.json();
            if (res.status === 404) {
                document.getElementById('stats-bar').innerHTML = '<div class="no-data">No analysis results yet. Go to Sources and run analysis.</div>';
                return;
            }
            throw new Error(err.detail);
        }
        const data = await res.json();
        renderDashboard(data);
    } catch (e) {
        document.getElementById('stats-bar').innerHTML = `<div class="no-data">Error loading dashboard: ${e.message}</div>`;
    }
}

function renderDashboard(data) {
    const stats = data.stats || {};
    const windows = stats.window_counts || {};
    const sources = data.sources_connected || [];
    const sourceLabel = sources.length ? sources.map(s => `${s.type}: ${s.id}`).join(' | ') : 'No source';
    const runMeta = data.run_meta || {};
    const sourceBreakdown = data.source_breakdown || {};
    const sourceCount = Object.keys(sourceBreakdown).length;
    const priorityAlerts = (data.alerts || []).length;

    document.getElementById('stats-bar').innerHTML = `
        <div class="stat-card tone-blue">
            <div class="stat-kicker">Coverage</div>
            <div class="stat-value">${windows.mentions_total || stats.total_items || 0}</div>
            <div class="stat-label">Total Mentions</div>
        </div>
        <div class="stat-card tone-indigo">
            <div class="stat-kicker">Momentum</div>
            <div class="stat-value">${windows.mentions_7d || 0}</div>
            <div class="stat-label">Last 7 Days</div>
        </div>
        <div class="stat-card tone-cyan">
            <div class="stat-kicker">Fresh Signals</div>
            <div class="stat-value">${windows.mentions_24h || 0}</div>
            <div class="stat-label">Last 24h</div>
        </div>
        <div class="stat-card tone-amber">
            <div class="stat-kicker">Complaints</div>
            <div class="stat-value">${stats.complaint_count || 0}</div>
            <div class="stat-label">Negative / Urgent</div>
        </div>
        <div class="stat-card tone-rose">
            <div class="stat-kicker">Priority</div>
            <div class="stat-value">${priorityAlerts}</div>
            <div class="stat-label">High/Critical Alerts</div>
        </div>
        <div class="stat-card tone-teal">
            <div class="stat-kicker">Scope</div>
            <div class="stat-value">${sourceCount}</div>
            <div class="stat-label">Active Sources</div>
        </div>
        <div class="stat-card stat-card-wide">
            <div class="stat-kicker">Run Context</div>
            <div class="stat-subvalue">${escHtml(sourceLabel)}</div>
            <div class="stat-note">Run: ${escHtml(runMeta.analysis_id || 'n/a')} ${runMeta.analyzed_at ? `| ${escHtml(runMeta.analyzed_at)}` : ''}</div>
        </div>
    `;

    // Alerts
    const alerts = data.alerts || [];
    if (alerts.length === 0) {
        document.getElementById('alerts-grid').innerHTML = '<div class="no-data">No active alerts from current run.</div>';
    } else {
        document.getElementById('alerts-grid').innerHTML = alerts.map(a => `
            <div class="alert-card ${a.severity} ${a.theme_id ? 'clickable' : ''}" ${a.theme_id ? `onclick="openTheme('${escAttr(a.theme_id)}')"` : ''}>
                <div class="alert-head">
                    <div class="alert-severity">${a.severity}</div>
                    <div class="alert-meta">
                        <span class="meta-chip">risk ${a.risk_score || 0}</span>
                        <span class="meta-chip">${(a.window_counts || {}).mentions_7d || 0} in 7d</span>
                    </div>
                </div>
                <div class="alert-title">${escHtml(a.title)}</div>
                <div class="alert-desc">${escHtml(a.description)}</div>
                <div class="alert-action">${escHtml(a.suggested_action)}</div>
                <div class="alert-foot">24h: ${(a.window_counts || {}).mentions_24h || 0} | 7d: ${(a.window_counts || {}).mentions_7d || 0} | total: ${(a.window_counts || {}).mentions_total || 0} | urgent: ${a.high_urgency_count || 0}</div>
                ${a.theme_id ? '<div class="alert-open-hint">Click to view full evidence</div>' : ''}
            </div>
        `).join('');
    }

    // Themes
    const themes = data.themes || [];
    const scopedThemes = themes.filter(t => {
        const isPattern = Boolean(t.parent_theme_id);
        if (currentThemeScope === 'primary') return !isPattern;
        if (currentThemeScope === 'pattern') return isPattern;
        return true;
    });

    if (scopedThemes.length === 0) {
        document.getElementById('themes-grid').innerHTML = '<div class="no-data">No themes found</div>';
    } else {
        const maxThemeCount = Math.max(...scopedThemes.map(t => t.count || 0), 1);
        document.getElementById('themes-grid').innerHTML = scopedThemes.map((t, idx) => {
            const win = t.window_counts || {};
            const share = Math.max(4, Math.round(((t.count || 0) / maxThemeCount) * 100));
            const topTags = (t.top_entities || []).slice(0, 3);
            const isPatternTheme = Boolean(t.parent_theme_id);
            return `
                <div class="theme-card" onclick="openTheme('${escAttr(t.theme_id)}')">
                    <div class="theme-head">
                        <div class="theme-label"><span class="theme-rank">#${idx + 1}</span>${escHtml(t.label)}</div>
                        <span class="meta-chip">${t.count} mentions</span>
                    </div>
                    <div class="theme-meta">
                        <span class="meta-chip">${escHtml(t.category)}</span>
                        ${isPatternTheme ? '<span class="meta-chip">pattern</span>' : '<span class="meta-chip">primary</span>'}
                        <span class="trend-badge ${t.trend}">${t.trend} ${t.trend_pct > 0 ? '+' : ''}${t.trend_pct}%</span>
                    </div>
                    <div class="theme-share-bar"><div class="theme-share-fill" style="width:${share}%"></div></div>
                    <div class="theme-window-row">
                        <span>24h: ${win.mentions_24h || 0}</span>
                        <span>7d: ${win.mentions_7d || 0}</span>
                        <span>Total: ${win.mentions_total || t.count}</span>
                    </div>
                    <div class="theme-tags">
                        ${topTags.length ? topTags.map(tag => `<span class="meta-chip">#${escHtml(tag)}</span>`).join('') : '<span class="meta-chip">No clear keywords yet</span>'}
                    </div>
                    <div class="theme-insight-row">Urgency ${t.avg_urgency}/5 | Sentiment ${t.avg_sentiment}</div>
                </div>
            `;
        }).join('');
    }

    // Recent evidence
    const items = data.recent_items || [];
    if (items.length === 0) {
        document.getElementById('evidence-list').innerHTML = '<div class="no-data">No feedback items</div>';
    } else {
        document.getElementById('evidence-list').innerHTML = items.slice(0, 15).map(item => `
            <div class="evidence-item">
                <div class="evidence-text">${escHtml(item.text || item.summary || '')}</div>
                <div class="evidence-badges">
                    <span class="meta-chip">${item.source || 'unknown'}</span>
                    ${item.metadata && item.metadata.app_id ? `<span class="meta-chip">${escHtml(item.metadata.app_id)}</span>` : ''}
                    ${item.author ? `<span class="meta-chip">${escHtml(item.author)}</span>` : ''}
                    ${item.date ? `<span class="meta-chip">${escHtml(item.date.slice(0, 10))}</span>` : ''}
                    ${item.rating ? `<span class="meta-chip">★${item.rating}</span>` : ''}
                    <span class="meta-chip">urgency ${item.urgency || '?'}</span>
                </div>
            </div>
        `).join('');
    }
}

// --- Theme Detail ---

async function openTheme(themeId) {
    showPage('theme');
    const content = document.getElementById('theme-detail-content');
    content.innerHTML = '<div class="no-data">Loading...</div>';

    try {
        const res = await fetch(`${API}/api/theme/${encodeURIComponent(themeId)}`);
        if (!res.ok) throw new Error('Theme not found');
        const theme = await res.json();
        renderThemeDetail(theme);
    } catch (e) {
        content.innerHTML = `<div class="no-data">Error: ${e.message}</div>`;
    }
}

function renderThemeDetail(theme) {
    const items = theme.items || [];
    const sources = {};
    items.forEach(i => { sources[i.source || 'unknown'] = (sources[i.source || 'unknown'] || 0) + 1; });

    const sentColor = theme.avg_sentiment < -0.3 ? 'var(--red)' : theme.avg_sentiment > 0.3 ? 'var(--green)' : 'var(--yellow)';

    document.getElementById('theme-detail-content').innerHTML = `
        <div class="detail-header">
            <h1>${escHtml(theme.label || theme.theme_id)}</h1>
            <div class="theme-meta">
                <span class="meta-chip">${theme.category}</span>
                <span class="trend-badge ${theme.trend}">${theme.trend} ${theme.trend_pct > 0 ? '+' : ''}${theme.trend_pct}%</span>
            </div>
            <p class="detail-sub">This page shows all evidence behind this theme from the current run.</p>
        </div>

        <div class="detail-stats">
            <div class="stat-card"><div class="stat-value">${theme.count}</div><div class="stat-label">Feedback Items</div></div>
            <div class="stat-card"><div class="stat-value" style="color:${sentColor}">${theme.avg_sentiment}</div><div class="stat-label">Avg Sentiment</div></div>
            <div class="stat-card"><div class="stat-value">${theme.avg_urgency}</div><div class="stat-label">Avg Urgency</div></div>
            <div class="stat-card"><div class="stat-value">${Object.keys(sources).length}</div><div class="stat-label">Sources</div></div>
        </div>

        <div class="section">
            <div class="section-head">
                <h2>Source Distribution</h2>
                <p class="section-note">Where this theme appears most.</p>
            </div>
            <div class="detail-distribution">
                ${Object.entries(sources).map(([k,v]) => `<span class="source-tag">${k}: ${v}</span>`).join('')}
            </div>
        </div>

        ${Object.keys(theme.time_buckets || {}).length > 0 ? `
        <div class="section">
            <div class="section-head">
                <h2>Timeline</h2>
                <p class="section-note">Simple historical movement for this theme.</p>
            </div>
            <div class="timeline-bars">
                ${Object.entries(theme.time_buckets).map(([week, count]) => {
                    const max = Math.max(...Object.values(theme.time_buckets));
                    const h = Math.max(8, (count / max) * 70);
                    return `<div class="timeline-bar-wrap">
                        <div class="timeline-bar" style="height:${h}px"></div>
                        <span class="timeline-label">${week}</span>
                    </div>`;
                }).join('')}
            </div>
        </div>` : ''}

        <div class="detail-items section">
            <div class="section-head">
                <h2>Feedback Items (${items.length})</h2>
                <p class="section-note">Direct evidence driving this theme score.</p>
            </div>
            <div class="evidence-list">
                ${items.map(item => `
                    <div class="evidence-item">
                        <div class="evidence-text">
                            <div>${escHtml(item.text || item.summary || '')}</div>
                            <div class="evidence-mini-meta">${item.date || ''} &middot; ${item.source || ''} ${item.rating ? '&middot; ' + '★'.repeat(item.rating) : ''}</div>
                        </div>
                        <div class="evidence-badges">
                            <span class="meta-chip">urgency ${item.urgency}</span>
                            <span class="meta-chip">${item.sentiment > 0 ? '+' : ''}${item.sentiment}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

// --- Ask Rivyu ---

async function askQuestion() {
    const input = document.getElementById('ask-input');
    const question = input.value.trim();
    if (!question) return;

    const messages = document.getElementById('chat-messages');

    // User message
    messages.innerHTML += `<div class="chat-msg user"><strong>You</strong><p>${escHtml(question)}</p></div>`;
    input.value = '';
    messages.scrollTop = messages.scrollHeight;

    // Loading
    const loadingId = 'msg-' + Date.now();
    messages.innerHTML += `<div class="chat-msg bot" id="${loadingId}"><strong>Rivyu</strong><p>Thinking...</p></div>`;
    messages.scrollTop = messages.scrollHeight;

    try {
        const res = await fetch(`${API}/api/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed');

        document.getElementById(loadingId).querySelector('p').textContent = data.answer;
    } catch (e) {
        document.getElementById(loadingId).querySelector('p').textContent = `Error: ${e.message}`;
    }
    messages.scrollTop = messages.scrollHeight;
}

function downloadComplaintsCSV() {
    window.open(`${API}/api/export/complaints.csv`, '_blank');
}

// --- Helpers ---

function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escAttr(str) {
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// --- Restore state from backend on page load ---
async function restoreState() {
    try {
        const res = await fetch(`${API}/api/status`);
        if (!res.ok) return;
        const data = await res.json();

        if (data.raw_count > 0) {
            totalIngested = data.raw_count;
            connectedSources = (data.sources || []).map(s => ({
                type: s.type, id: s.id, count: s.count
            }));
            updateSourcesSummary();
        }
        // Keep reload behavior predictable for demos: always open Sources first.
        showPage('sources');
    } catch (e) {
        // Silently fail — first visit
    }
}

restoreState();
