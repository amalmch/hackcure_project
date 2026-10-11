/**
 * Vue « Prédictions » (V2, étape 8) : pour chaque patient, risque et fenêtre de temps estimée avant une crise
 * (épilepsie, sepsis, événement cardiaque, détérioration générale, complications du diabète).
 * Jauge par condition, « crise estimée dans ~X–Y », niveau de confiance, facteurs contributifs, historique.
 * Estimation de prototype, non validée cliniquement.
 */
(() => {
    'use strict';
    let mounted = false, host = null, data = null, selected = null, detail = null, chart = null, timer = null;
    const ICON = { seizure: '⚡', sepsis: '🦠', cardiac: '❤️', deterioration: '📉', diabetes: '🩸' };
    const COLOR = { faible: '#22c55e', 'modéré': '#f59e0b', 'élevé': '#ef4444', critique: '#a855f7' };
    const LINE = { seizure: '#facc15', sepsis: '#f87171', cardiac: '#fb7185', deterioration: '#38bdf8', diabetes: '#a78bfa' };

    function gauge(p) {
        const c = COLOR[p.level];
        return `<div class="pred-cell" title="${Api.esc(p.factors.join(' · '))}"><div class="small"><b>${ICON[p.key]} ${Api.esc(p.label)}</b></div>
            <div class="pred-gauge"><span style="width:${p.risk}%;background:${c}"></span></div>
            <div class="small"><b style="color:${c}">${p.risk}/100 · ${p.level}</b>${p.window ? ` — crise estimée dans <b>${Api.esc(p.window.text)}</b>` : ''}</div>
            <div class="muted small">confiance ${p.confidence}</div></div>`;
    }
    function patientHtml(r) {
        return `<div class="card pred-patient ${selected === r.patient_id ? 'selected' : ''}" data-id="${r.patient_id}"><h3>${Api.esc(r.name)} <span class="room-pill">${r.room}</span>
            <span class="muted small">risque maximal ${r.max_risk}/100</span></h3><div class="pred-grid">${r.predictions.map(gauge).join('')}</div></div>`;
    }
    function detailHtml() {
        if (!detail) return '';
        const top = [...detail.predictions].sort((a, b) => b.risk - a.risk).filter(p => p.risk >= 30);
        return `<div class="card"><h3>${Api.esc(detail.name)} — facteurs contributifs et historique</h3><div id="pred-profile"></div>
            ${top.map(p => `<div class="pred-detail"><b style="color:${COLOR[p.level]}">${ICON[p.key]} ${Api.esc(p.label)} — ${p.risk}/100 (${p.level})</b>${p.window ? ` · crise estimée dans <b>${Api.esc(p.window.text)}</b>` : ''} · confiance ${p.confidence}
                <ul class="fever-list">${p.factors.map(f => `<li>${Api.esc(f)}</li>`).join('')}</ul>
                ${p.ai ? `<div class="ai-hint">🧠 ${Api.esc(p.ai.explanation)}${p.ai.fallback ? ' <span class="tag tag-fallback">réponse de secours</span>' : ''}<ul class="fever-list">${p.ai.conduct.map(c => `<li>${Api.esc(c)}</li>`).join('')}</ul><span class="muted small">${Api.esc(p.ai.provider)}</span></div>` : ''}</div>`).join('')
                || '<div class="muted small">Aucun risque au-dessus de 30/100 pour ce patient.</div>'}
            <div style="height:190px;margin-top:8px"><canvas id="pred-chart"></canvas></div></div>`;
    }
    function paint() {
        const b = host.querySelector('#pred-body'); if (!b || !data) return;
        b.innerHTML = data.patients.map(patientHtml).join('') + `<div id="pred-detail">${detailHtml()}</div>`;
        b.querySelectorAll('.pred-patient').forEach(c => c.addEventListener('click', () => { selected = c.dataset.id; loadDetail(); }));
        if (detail) ClinicalProfile.mount(b.querySelector('#pred-profile'), detail.patient_id);
        const canvas = b.querySelector('#pred-chart');
        if (chart) { chart.destroy(); chart = null; }
        if (canvas && detail && typeof Chart !== 'undefined') {
            const sets = Object.keys(detail.history).filter(k => detail.history[k].length).map(k => ({ label: detail.predictions.find(p => p.key === k).label, data: detail.history[k].map(h => ({ x: new Date(h.ts).getTime(), y: h.risk })), borderColor: LINE[k], pointRadius: 2, tension: .2, stepped: true }));
            chart = new Chart(canvas, { type: 'line', data: { datasets: sets }, options: { responsive: true, maintainAspectRatio: false, animation: false, parsing: false, plugins: { legend: { labels: { color: '#94a3b8', boxWidth: 12 } } },
                scales: { x: { type: 'linear', ticks: { color: '#64748b', maxTicksLimit: 7, callback: v => new Date(v).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) } }, y: { min: 0, max: 100, ticks: { color: '#64748b' } } } } });
        }
    }
    async function loadDetail() { try { detail = selected ? await Api.get(`/api/predictions/${selected}`) : null; } catch (_) { detail = null; } paint(); }
    async function load() {
        if (!mounted) return;
        try { data = await Api.get('/api/predictions'); } catch (e) { host.querySelector('#pred-body').innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        if (!selected && data.patients.length) selected = [...data.patients].sort((a, b) => b.max_risk - a.max_risk)[0].patient_id;
        await loadDetail();
    }
    let soon = null;
    window.addEventListener('hackcure:ws', (e) => { if (mounted && e.detail.type === 'predictions' && !soon) soon = setTimeout(() => { soon = null; load(); }, 1200); });
    Views.register('predictions', { title: 'Prédictions', perm: 'view_predictions',
        mount(el) { mounted = true; host = el; el.innerHTML = `<div class="ai-hint pred-warning">⚠ <b>Estimation de prototype, non validée cliniquement.</b> Scores déterministes (règles cliniques connues et extrapolation des tendances avec intervalle d'incertitude) ; l'explication et la conduite à tenir sont rédigées par l'IA. Aide à la décision — validation médicale requise.</div><div id="pred-body"></div>`; load(); timer = setInterval(load, 20000); },
        unmount() { mounted = false; clearInterval(timer); if (chart) { chart.destroy(); chart = null; } } });
})();
