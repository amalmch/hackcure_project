/**
 * Vue « Centre de détection » : risques (filtres statut / sévérité / chambre), détail, lien vers le centre de commande.
 */
const DetectionView = (() => {
    'use strict';
    const SEV_FR = { low: 'faible', medium: 'moyen', high: 'élevé', critical: 'critique' };
    const ST_FR = { open: 'ouvert', in_progress: 'en cours', resolved: 'résolu', escalated: 'escaladé' };
    let mounted = false, rows = [], selected = null;
    const filters = { status: 'open,in_progress,escalated', severity: '', room: '', q: '' };

    async function fetchRows() {
        const p = new URLSearchParams();
        if (filters.status) p.set('status', filters.status);
        if (filters.severity) p.set('severity', filters.severity);
        if (filters.room) p.set('room', filters.room);
        p.set('limit', '200');
        rows = await Api.get('/api/risks?' + p.toString());
    }

    function tableHtml() {
        const q = filters.q.toLowerCase();
        const list = rows.filter(r => !q || `${r.title} ${r.patient_name} ${r.type} ${r.explanation}`.toLowerCase().includes(q));
        if (!list.length) return '<div class="empty">Aucun risque pour ces filtres</div>';
        return `<table class="data"><thead><tr><th>#</th><th>Détecté</th><th>Chambre</th><th>Patient</th><th>Risque</th><th>Sévérité</th><th>Statut</th><th>Source</th><th>Plan</th></tr></thead><tbody>
            ${list.map(r => `<tr data-id="${r.id}" class="${selected === r.id ? 'selected' : ''}">
                <td>${r.id}</td><td>${Api.fmtTime(r.detected_at)}</td><td><span class="room-pill">${r.room}</span></td><td>${Api.esc(r.patient_name || '—')}</td>
                <td>${Api.esc(r.type_label)}${r.news2 != null ? ` <span class="muted small">NEWS2 ${r.news2}</span>` : ''}</td>
                <td><span class="tag tag-${r.severity}">${SEV_FR[r.severity]}</span></td><td><span class="tag tag-${r.status}">${ST_FR[r.status]}</span></td>
                <td class="muted small">${r.source_agent}</td><td>${r.plan ? `${r.plan.done_count}/${r.plan.total}` : '—'}</td></tr>`).join('')}
        </tbody></table>`;
    }

    function detailHtml(r) {
        if (!r) return '<div class="empty">Sélectionnez un risque</div>';
        const plan = r.plan ? `<ul class="checklist">${r.plan.steps.map(s => `<label><input type="checkbox" disabled ${s.done ? 'checked' : ''}><span class="${s.done ? 'done' : ''}">${s.order}. ${Api.esc(s.text)}${s.done ? ` <span class="muted small">— ${s.done_by} ${Api.fmtTime(s.done_at)}</span>` : ''}</span></label>`).join('')}</ul>` : '<div class="muted">Plan en cours de rédaction…</div>';
        const timeline = [['Détecté', r.detected_at], ['Pris en charge', r.acknowledged_at], ['Escaladé', r.escalated_at], ['Résolu', r.resolved_at], ['Vérifié', r.verified_at]].filter(x => x[1]).map(x => `<div class="detail-row"><span class="detail-label">${x[0]}</span><span class="detail-value">${Api.fmtDateTime(x[1])}</span></div>`).join('');
        return `<h3>#${r.id} · ${Api.esc(r.title)}</h3>
            <p><span class="tag tag-${r.severity}">${SEV_FR[r.severity]}</span> <span class="tag tag-${r.status}">${ST_FR[r.status]}</span> ${r.handled_by === 'n8n' ? '<span class="tag tag-n8n">n8n</span>' : ''} ${r.plan && /secours/i.test(r.plan.llm_provider) ? '<span class="tag tag-fallback">réponse de secours (LLM indisponible)</span>' : ''} <span class="muted small">par ${r.source_agent}</span></p>
            <div class="ai-hint">Explication IA (aide à la décision) :<br>${Api.esc(r.explanation)}</div>
            <h3>Plan d'action ${r.plan ? `<span class="muted small">(${r.plan.llm_provider})</span>` : ''}</h3>${plan}
            <h3>Chronologie</h3>${timeline}${r.resolved_by ? `<div class="detail-row"><span class="detail-label">Clôturé par</span><span class="detail-value">${Api.esc(r.resolved_by)}</span></div>` : ''}
            ${r.notes ? `<h3>Notes</h3><pre class="md-preview small">${Api.esc(r.notes)}</pre>` : ''}
            ${Auth.can('view_command') ? `<button class="btn btn-accent" id="det-open-cmd">🎛️ Ouvrir dans le centre de commande</button>` : ''}`;
    }

    async function render(el) {
        el.innerHTML = `<div class="view-toolbar">
            <select id="det-status"><option value="open,in_progress,escalated" ${filters.status.includes('open') && filters.status.includes('in_progress') ? 'selected' : ''}>Ouverts (tous)</option><option value="open">Ouvert</option><option value="in_progress">En cours</option><option value="escalated">Escaladé</option><option value="resolved">Résolu</option><option value="">Tous</option></select>
            <select id="det-sev"><option value="">Toutes sévérités</option><option value="critical">Critique</option><option value="high">Élevé</option><option value="medium">Moyen</option><option value="low">Faible</option></select>
            <select id="det-room"><option value="">Toutes chambres</option>${['101', '102', '103', '104'].map(r => `<option value="${r}">Chambre ${r}</option>`).join('')}</select>
            <input id="det-q" placeholder="Rechercher…" value="${Api.esc(filters.q)}"><span class="spacer"></span><span class="muted small" id="det-count"></span></div>
            <div class="grid-2" style="grid-template-columns: 1.4fr 1fr; align-items:start"><div class="card" id="det-table"></div><div class="card" id="det-detail"></div></div>`;
        el.querySelector('#det-status').value = filters.status; el.querySelector('#det-sev').value = filters.severity; el.querySelector('#det-room').value = filters.room;
        el.querySelector('#det-status').addEventListener('change', e => { filters.status = e.target.value; refresh(); });
        el.querySelector('#det-sev').addEventListener('change', e => { filters.severity = e.target.value; refresh(); });
        el.querySelector('#det-room').addEventListener('change', e => { filters.room = e.target.value; refresh(); });
        el.querySelector('#det-q').addEventListener('input', e => { filters.q = e.target.value; paint(); });
        await refresh();
    }

    let refreshTimer = null;
    function refreshSoon() { if (refreshTimer) return; refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 800); }
    async function refresh() {
        if (!mounted) return;
        try { await fetchRows(); } catch (e) { Api.toast(e.message, 'critical'); return; }
        paint();
    }

    function paint() {
        const t = document.getElementById('det-table'); if (!t) return;
        t.innerHTML = tableHtml();
        document.getElementById('det-count').textContent = `${rows.length} risque(s)`;
        t.querySelectorAll('tr[data-id]').forEach(tr => tr.addEventListener('click', () => select(Number(tr.dataset.id))));
        const d = document.getElementById('det-detail');
        const r = rows.find(x => x.id === selected);
        d.innerHTML = detailHtml(r);
        d.querySelector('#det-open-cmd')?.addEventListener('click', () => { Views.show('command'); CommandView.select(selected); });
    }

    async function select(id) {
        selected = id;
        if (!rows.find(x => x.id === id)) { try { rows.unshift(await Api.get(`/api/risks/${id}`)); } catch (_) { } }
        paint();
    }

    window.addEventListener('hackcure:ws', (e) => { if (mounted && e.detail.type === 'risk') refreshSoon(); });
    Views.register('detection', { title: 'Centre de détection', perm: 'view_clinical', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    return { select, refresh };
})();

window.DetectionView = DetectionView;
