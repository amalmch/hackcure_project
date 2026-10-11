/**
 * Vue « Psychologie » (V2, étape 7) : liste des patients avec score de bien-être et tendance, fiche détaillée
 * (courbe, niveaux de risque par trouble et facteurs, questionnaire d'admission, prescriptions psychothérapeutiques).
 * Psychiatre : écriture. Médecins : lecture complète. Infirmiers : lecture seule (état et consignes).
 * Ce n'est jamais un diagnostic.
 */
(() => {
    'use strict';
    let mounted = false, host = null, rows = [], selected = null, detail = null, chart = null;
    const LVL = { 'faible': 'tag-ok', 'modéré': 'tag-warn', 'élevé': 'tag-danger' };
    const TREND = { hausse: '↗', baisse: '↘', stable: '→' };
    const canWrite = () => Auth.can('write_psychology');
    const color = (w) => w == null ? '#64748b' : w < 45 ? '#ef4444' : w < 65 ? '#f59e0b' : '#22c55e';

    function listHtml() {
        return rows.map(r => `<div class="agent-card ${selected === r.patient_id ? 'selected' : ''}" data-id="${r.patient_id}" style="cursor:pointer;margin-bottom:6px;${selected === r.patient_id ? 'border-color:var(--border-active)' : ''}">
            <div class="agent-head"><span class="agent-name">${Api.esc(r.name)} <span class="room-pill">${r.room}</span></span>
                <span class="psy-score" style="color:${color(r.wellbeing)}">${r.wellbeing ?? '—'}<span class="muted small">/100 ${TREND[r.trend] || ''}</span></span></div>
            <div class="small">${r.q9_positive ? '<span class="tag tag-danger">alerte item 9</span> ' : ''}${Object.entries(r.levels || {}).map(([k, v]) => `<span class="tag ${LVL[v]}">${{ depression: 'dépression', anxiety: 'anxiété', insomnia: 'sommeil' }[k]} ${v}</span>`).join(' ')}
                <span class="muted">questionnaire ${{ completed: 'rempli', pending: 'en attente', absent: 'non proposé' }[r.questionnaire]}</span></div></div>`).join('') || '<div class="empty">Aucun patient hospitalisé</div>';
    }

    function disorder(key, d) {
        return `<div class="psy-disorder"><div class="small"><b>${Api.esc(detail.labels[key])}</b> <span class="tag ${LVL[d.level]}">risque ${d.level}</span> <span class="muted">${d.score}/100</span></div>
            <div class="psy-bar"><span style="width:${d.score}%;background:${d.score >= 60 ? '#ef4444' : d.score >= 35 ? '#f59e0b' : '#22c55e'}"></span></div>
            <div class="muted small">${d.factors.length ? d.factors.map(Api.esc).join(' · ') : 'aucun facteur relevé'}</div></div>`;
    }

    function questionnaireHtml(q) {
        if (!q) return '<div class="muted small">Le questionnaire sera proposé dès que le patient sera installé dans son lit.</div>';
        const link = `${location.origin}${q.url}`;
        if (q.status !== 'completed') return `<div class="small">En attente de réponse. Page tablette : <a href="${q.url}" target="_blank" rel="noopener">${Api.esc(link)}</a></div>`;
        const s = q.scores, line = (k, name) => `<span class="tag">${name} ${s[k].score}/${s[k].max} — ${s[k].level}</span>`;
        let answers = '';
        if (q.answers && detail.items) {
            answers = Object.keys(detail.items).map(k => `<details class="small"><summary>${{ phq9: 'PHQ-9 (humeur)', gad7: 'GAD-7 (inquiétudes)', sleep: 'Sommeil' }[k]} — réponses</summary><ol>${detail.items[k].map((it, i) =>
                `<li>${Api.esc(it)} : <b>${Api.esc(detail.scale[q.answers[k][i]])}</b></li>`).join('')}</ol></details>`).join('');
        }
        return `<div class="small">Rempli le ${Api.fmtDateTime(q.completed_at)} · ${line('phq9', 'PHQ-9')} ${line('gad7', 'GAD-7')} ${line('sleep', 'Sommeil')} ${q.q9_positive ? '<span class="tag tag-danger">item 9 positif</span>' : ''}</div>${answers}`;
    }

    function paintDetail() {
        const el = host.querySelector('#psy-detail'); if (!el) return;
        if (!detail) { el.innerHTML = '<div class="card empty">Sélectionnez un patient</div>'; return; }
        const l = detail.latest;
        const ai = l && l.ai ? `<div class="ai-hint">🧠 ${Api.esc(l.ai.explanation)}${l.ai.fallback ? ' <span class="tag tag-fallback">réponse de secours</span>' : ''}<br><span class="muted small">${Api.esc(l.ai.provider)} — ${Api.esc(detail.disclaimer)}</span></div>` : '';
        const conduct = l ? ((l.ai && l.ai.conduct.length ? l.ai.conduct : l.conduct) || []) : [];
        el.innerHTML = `<div id="psy-profile"></div>
            <div class="card"><h3>${Api.esc(detail.name)} <span class="room-pill">${detail.room || '—'}</span> ${l ? `<span class="psy-score" style="color:${color(l.wellbeing)}">${l.wellbeing}<span class="muted small">/100 bien-être</span></span>` : ''}
                ${l && l.q9_positive ? '<span class="tag tag-danger">ALERTE : idées de mort ou d\'automutilation déclarées</span>' : ''}</h3>
                <div class="muted small">${Api.esc(detail.disclaimer)}${detail.scope === 'consignes' ? ' Votre rôle voit l\'état du patient et les consignes.' : ''}</div>
                ${l ? `<div class="grid-3" style="margin-top:8px">${['depression', 'anxiety', 'insomnia'].map(k => disorder(k, l[k])).join('')}</div>${ai}
                    <h3>Conduite à tenir</h3><ul class="fever-list">${conduct.map(c => `<li>${Api.esc(c)}</li>`).join('')}</ul>` : '<div class="muted small" style="margin-top:8px">Score en cours de calcul…</div>'}
                <div style="height:150px;margin-top:8px"><canvas id="psy-chart"></canvas></div></div>
            <div class="card"><h3>Questionnaire d'admission</h3>${questionnaireHtml(detail.questionnaire)}</div>
            <div class="card"><h3>Prescriptions psychothérapeutiques et consignes à l'équipe</h3>
                ${detail.prescriptions.map(p => `<div class="detail-row" style="align-items:flex-start"><span><b>${Api.esc(p.type)}</b> <span class="muted small">${Api.esc(p.frequency)}</span>${p.active ? '' : ' <span class="tag">arrêtée</span>'}<br>
                    <span class="small">${p.goals ? 'Objectifs : ' + Api.esc(p.goals) + '<br>' : ''}${p.instructions ? 'Consignes : ' + Api.esc(p.instructions) : ''}</span></span><span class="muted small">${Api.esc(p.author_name || p.author)} · ${Api.fmtDate(p.created_at)}</span></div>`).join('') || '<div class="muted small">Aucune prescription.</div>'}
                ${canWrite() ? `<div class="form-grid" style="margin-top:8px"><label>Type de suivi<input id="rx-type" placeholder="ex. entretiens de soutien, TCC, relaxation"></label><label>Fréquence<input id="rx-freq" placeholder="ex. 2 fois par semaine"></label>
                    <label>Objectifs<input id="rx-goals"></label><label>Consignes à l'équipe<input id="rx-inst"></label></div><div class="inline-form" style="margin-top:8px"><button class="btn btn-accent btn-sm" id="rx-add">＋ Ajouter la prescription</button></div>` : ''}</div>`;
        ClinicalProfile.mount(el.querySelector('#psy-profile'), selected);
        el.querySelector('#rx-add')?.addEventListener('click', async () => {
            const type = el.querySelector('#rx-type').value.trim(); if (!type) { Api.toast('Type de suivi requis', 'warning'); return; }
            try { await Api.post(`/api/psych/${selected}/prescriptions`, { type, frequency: el.querySelector('#rx-freq').value, goals: el.querySelector('#rx-goals').value, instructions: el.querySelector('#rx-inst').value }); Api.toast('Prescription ajoutée', 'success'); load(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        const canvas = el.querySelector('#psy-chart');
        if (chart) { chart.destroy(); chart = null; }
        if (canvas && typeof Chart !== 'undefined' && detail.history.length) {
            chart = new Chart(canvas, { type: 'line', data: { labels: detail.history.map(h => new Date(h.ts).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })), datasets: [{ label: 'Bien-être (0–100)', data: detail.history.map(h => h.wellbeing), borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,.15)', fill: true, tension: .25, pointRadius: 2 }] },
                options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { labels: { color: '#94a3b8', boxWidth: 12 } } }, scales: { y: { min: 0, max: 100, ticks: { color: '#64748b' } }, x: { ticks: { color: '#64748b', maxTicksLimit: 8 } } } } });
        }
    }

    async function load() {
        if (!mounted) return;
        try { rows = await Api.get('/api/psych/patients'); } catch (e) { host.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        if (!selected && rows.length) selected = rows[0].patient_id;
        const list = host.querySelector('#psy-list'); if (!list) return;
        list.innerHTML = listHtml();
        list.querySelectorAll('[data-id]').forEach(c => c.addEventListener('click', () => { selected = c.dataset.id; load(); }));
        if (document.activeElement && host.querySelector('#psy-detail').contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return;   // saisie en cours
        try { detail = selected ? await Api.get(`/api/psych/${selected}`) : null; } catch (_) { detail = null; }
        paintDetail();
    }

    let soon = null;
    window.addEventListener('hackcure:ws', (e) => { if (mounted && e.detail.type === 'psych' && !soon) soon = setTimeout(() => { soon = null; load(); }, 800); });
    Views.register('psych', { title: 'Psychologie', perm: 'view_psychology',
        mount(el) { mounted = true; host = el; el.innerHTML = `<div class="ai-hint">Score de bien-être (0–100) et niveau de risque pour trois troubles, à partir du questionnaire d'admission, des expressions du visage, des levers nocturnes, du sommeil, des constantes et des antécédents. Estimation de prototype : jamais un diagnostic.</div>
            <div class="grid-2" style="grid-template-columns:0.8fr 1.9fr;align-items:start"><div class="card"><h3>Patients</h3><div id="psy-list"></div></div><div id="psy-detail"></div></div>`; load(); },
        unmount() { mounted = false; if (chart) { chart.destroy(); chart = null; } } });
})();
