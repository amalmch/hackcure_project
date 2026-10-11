/**
 * HackCure — panneau Agents (onglet du panneau droit) : carte par agent avec statut animé,
 * fil « 📥 Entrée → 🧠 Raisonnement → ✅ Sortie », lien vers le risque, filtres agent / chambre.
 */
const AgentsPanel = (() => {
    'use strict';
    const ICONS = { VisionAgent: '👁️', VitalsAgent: '💓', EnvironmentAgent: '🌡️', RiskAgent: '🛡️', FollowUpAgent: '🔁', ReportAgent: '📝', 'n8n:risk-triage': '🔗', 'n8n:risk-verify': '🔗', 'n8n:shift-report': '🔗', 'n8n:pharmacy-alerts': '🔗' };
    const N8N_WORKFLOWS = [
        { name: 'n8n:risk-triage', description: 'Webhook risk-created → Claude (explication + plan) → plan sur la plateforme → Telegram infirmier → attente d\'acquittement → escalade.' },
        { name: 'n8n:risk-verify', description: 'Webhook staff-left → attente 2 min → état réel de la chambre → Claude → résolu ou persistant → Telegram.' },
        { name: 'n8n:shift-report', description: 'Cron 07:45 / 19:45 + bouton → événements, risques, humeurs → Claude → rapport de garde → Telegram.' },
        { name: 'n8n:pharmacy-alerts', description: 'Cron quotidien + bouton → stock sous seuil, péremption < 30 j → Telegram pharmacien.' },
    ];
    const STATUS_FR = { idle: 'en veille', thinking: 'analyse…', acting: 'action…', offline: 'n8n hors ligne' };
    const MAX_FEED = 60;
    let agents = [];
    let feed = [];
    const filters = { agent: '', room: '' };

    function cardHtml(a) {
        return `<div class="agent-card compact" id="agent-card-${a.name}" title="${Api.esc(a.description)}">
            <div class="agent-head">
                <span class="agent-name">${ICONS[a.name] || '🤖'} ${a.name}</span>
                <span class="agent-status ${a.status}" data-status>${STATUS_FR[a.status] || a.status}</span>
            </div>
            <div class="agent-log"><div class="meta"><span>dernière exécution : <span data-last>${a.last_run ? Api.fmtTime(a.last_run) : '—'}</span></span><span><span data-runs>${a.runs}</span> exécutions${a.errors ? ` · <span style="color:#fca5a5">${a.errors} err.</span>` : ''}</span></div></div>
        </div>`;
    }

    function renderCards() {
        const host = document.getElementById('agent-cards'); if (!host) return;
        const list = filters.agent ? agents.filter(a => a.name === filters.agent) : agents;
        host.innerHTML = list.map(cardHtml).join('') || '<div class="empty">Agents désactivés</div>';
    }

    function itemHtml(l) {
        const riskLink = l.risk_id ? ` · <a data-risk="${l.risk_id}">Risque #${l.risk_id}</a>` : '';
        return `<div class="agent-feed-item ${l.agent} ${l.status === 'error' ? 'error' : ''}">
            <div class="who"><span>${ICONS[l.agent] || '🤖'} ${l.agent}${l.room ? ` <span class="room-pill">${l.room}</span>` : ''}</span><span class="muted small">${Api.fmtTime(l.ts)}${l.duration_ms ? ' · ' + l.duration_ms + ' ms' : ''}</span></div>
            <div class="step">📥 <b>Entrée</b> ${Api.esc(l.input)}</div>
            <div class="step">🧠 <b>Raisonnement</b> ${Api.esc(l.reasoning)}</div>
            <div class="step">${l.status === 'error' ? '❌' : '✅'} <b>Sortie</b> ${Api.esc(l.output)}${riskLink}</div>
        </div>`;
    }

    function renderFeed() {
        const host = document.getElementById('agent-feed'); if (!host) return;
        const list = feed.filter(l => (!filters.agent || l.agent === filters.agent) && (!filters.room || l.room === filters.room));
        host.innerHTML = list.slice(0, MAX_FEED).map(itemHtml).join('') || '<div class="empty">Aucune activité pour ce filtre</div>';
        host.querySelectorAll('a[data-risk]').forEach(a => a.addEventListener('click', () => openRisk(Number(a.dataset.risk))));
    }

    function openRisk(id) {
        if (Auth.can('view_command')) { Views.show('command'); if (window.CommandView) CommandView.select(id); }
        else if (Auth.can('view_clinical')) { Views.show('detection'); if (window.DetectionView) DetectionView.select(id); }
    }

    function onStatus(m) {
        const a = agents.find(x => x.name === m.agent); if (a) Object.assign(a, { status: m.status, last_run: m.last_run, runs: m.runs, errors: m.errors });
        const card = document.getElementById(`agent-card-${m.agent}`); if (!card) return;
        const st = card.querySelector('[data-status]'); st.className = `agent-status ${m.status}`; st.textContent = STATUS_FR[m.status] || m.status;
        if (m.last_run) card.querySelector('[data-last]').textContent = Api.fmtTime(m.last_run);
        if (m.runs != null) card.querySelector('[data-runs]').textContent = m.runs;
    }

    function onLog(m) {
        feed.unshift(m); if (feed.length > 200) feed.length = 200;
        let a = agents.find(x => x.name === m.agent);
        if (!a && m.agent && m.agent.startsWith('n8n:')) { a = { name: m.agent, description: 'Workflow n8n', status: 'idle', last_run: null, runs: 0, errors: 0 }; agents.push(a); renderCards(); }
        if (a) { a.last_run = m.ts; a.runs = (a.runs || 0) + 1; }
        const card = document.getElementById(`agent-card-${m.agent}`);
        if (card) { card.querySelector('[data-last]').textContent = Api.fmtTime(m.ts); if (a) card.querySelector('[data-runs]').textContent = a.runs; }
        if ((!filters.agent || m.agent === filters.agent) && (!filters.room || m.room === filters.room)) {
            const host = document.getElementById('agent-feed'); if (!host) return;
            const empty = host.querySelector('.empty'); if (empty) empty.remove();
            host.insertAdjacentHTML('afterbegin', itemHtml(m));
            host.firstElementChild.querySelectorAll('a[data-risk]').forEach(x => x.addEventListener('click', () => openRisk(Number(x.dataset.risk))));
            while (host.children.length > MAX_FEED) host.removeChild(host.lastChild);
        }
    }

    async function load() {
        try {
            const info = await Api.get('/api/agents', { noRedirect: true });
            agents = info.agents || [];
            if (info.n8n && info.n8n.enabled) {
                const seen = info.n8n.workflows || {};
                N8N_WORKFLOWS.forEach(w => agents.push({ name: w.name, description: w.description, status: info.n8n.status === 'online' ? 'idle' : 'offline', last_run: (seen[w.name] || {}).last_run || null, runs: (seen[w.name] || {}).runs || 0, errors: 0 }));
            }
            const sel = document.getElementById('agent-filter-agent');
            if (sel) { sel.innerHTML = '<option value="">Tous les agents</option>' + agents.map(a => `<option value="${a.name}">${a.name}</option>`).join(''); }
            const rsel = document.getElementById('agent-filter-room');
            if (rsel && rsel.options.length <= 1) ['101', '102', '103', '104'].forEach(r => rsel.insertAdjacentHTML('beforeend', `<option value="${r}">Chambre ${r}</option>`));
            feed = await Api.get('/api/agents/logs?limit=60', { noRedirect: true });
            renderCards(); renderFeed();
        } catch (e) { console.warn('[AgentsPanel]', e.message); }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('agent-filter-agent')?.addEventListener('change', (e) => { filters.agent = e.target.value; renderCards(); renderFeed(); });
        document.getElementById('agent-filter-room')?.addEventListener('change', (e) => { filters.room = e.target.value; renderFeed(); });
        Auth.onReady(load);
    });
    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'agent_status') onStatus(m);
        else if (m.type === 'agent_log') onLog(m);
    });
    return { load, openRisk };
})();

window.AgentsPanel = AgentsPanel;
