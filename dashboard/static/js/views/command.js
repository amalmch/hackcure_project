/**
 * Vue « Centre de commande » : plan d'action IA avec cases horodatées, « Marquer résolu » soumis à vérification,
 * escalade, et commandes d'équipements par chambre (fenêtre, chauffage, clim, veilleuse).
 */
const CommandView = (() => {
    'use strict';
    const SEV_FR = { low: 'faible', medium: 'moyen', high: 'élevé', critical: 'critique' };
    const ST_FR = { open: 'ouvert', in_progress: 'en cours', resolved: 'résolu', escalated: 'escaladé' };
    const EQ = [['window', 'Fenêtre', 'open', 'close', '🪟'], ['heater', 'Chauffage', 'on', 'off', '🔥'], ['ac', 'Climatisation', 'on', 'off', '❄️'], ['light', 'Veilleuse', 'on', 'off', '💡']];
    let mounted = false, rows = [], selected = null, equipment = {};

    const canManage = () => Auth.can('manage_risks');
    const canControl = () => Auth.can('control_equipment');

    async function fetchAll() {
        rows = await Api.get('/api/risks?open_only=1&limit=100');
        try { equipment = await Api.get('/api/commands/equipment'); } catch (_) { equipment = {}; }
    }

    function listHtml() {
        if (!rows.length) return '<div class="empty">Aucun risque ouvert 🎉</div>';
        const byRoom = {};
        rows.forEach(r => (byRoom[r.room] = byRoom[r.room] || []).push(r));
        return Object.keys(byRoom).sort().map(room => `<div class="muted small" style="margin:8px 0 4px"><span class="room-pill">Chambre ${room}</span></div>` + byRoom[room].map(r => `
            <div class="agent-card ${selected === r.id ? 'selected' : ''}" data-id="${r.id}" style="cursor:pointer;margin-bottom:6px;${selected === r.id ? 'border-color:var(--border-active)' : ''}">
                <div class="agent-head"><span class="agent-name">#${r.id} ${Api.esc(r.type_label)}</span><span class="tag tag-${r.severity}">${SEV_FR[r.severity]}</span></div>
                <div class="muted small">${ST_FR[r.status]} · ${Api.fmtTime(r.detected_at)} · ${Api.esc(r.patient_name || '')}${r.plan ? ` · plan ${r.plan.done_count}/${r.plan.total}` : ''}</div>
            </div>`).join('')).join('');
    }

    function planHtml(r) {
        if (!r) return '<div class="empty">Sélectionnez un risque dans la liste</div>';
        const steps = r.plan ? r.plan.steps.map(s => `<label><input type="checkbox" data-step="${s.id}" ${s.done ? 'checked' : ''} ${canManage() && r.status !== 'resolved' ? '' : 'disabled'}>
            <span class="${s.done ? 'done' : ''}">${s.order}. ${Api.esc(s.text)} ${s.suggested_by_ai ? '<span class="muted small">(IA)</span>' : ''}${s.done ? `<br><span class="muted small">✔ ${s.done_by} · ${Api.fmtDateTime(s.done_at)}</span>` : ''}</span></label>`).join('') : '<div class="muted">Plan en cours de rédaction par le RiskAgent…</div>';
        const origin = r.handled_by === 'n8n' ? '<span class="tag tag-n8n" title="Plan, Telegram, attente d\'acquittement et escalade orchestrés par n8n">orchestré par n8n</span>' : '<span class="tag" title="Agents Python locaux">agents locaux</span>';
        const provider = r.plan ? r.plan.llm_provider : '';
        const fallbackTag = /secours/i.test(provider) ? '<span class="tag tag-fallback">réponse de secours (LLM indisponible)</span>' : '';
        return `${r.patient_id ? '<div id="cmd-profile"></div>' : ''}<h3>#${r.id} · ${Api.esc(r.title)} <span class="tag tag-${r.severity}">${SEV_FR[r.severity]}</span> <span class="tag tag-${r.status}">${ST_FR[r.status]}</span> ${origin} ${fallbackTag}</h3>
            <div class="ai-hint">🧠 ${Api.esc(r.explanation)}<br><span class="muted">Suggestion IA — à valider par un soignant.</span></div>
            <h3>Plan d'action ${r.plan ? `<span class="muted small">(${r.plan.done_count}/${r.plan.total} · ${r.plan.llm_provider})</span>` : ''}</h3>
            <div class="checklist">${steps}</div>
            ${canManage() && r.status !== 'resolved' ? `<div class="inline-form" style="margin-top:10px"><input id="cmd-new-step" placeholder="Ajouter une étape…" style="flex:1"><button class="btn btn-sm" id="cmd-add-step">+ Ajouter</button></div>
            <div class="inline-form" style="margin-top:12px">
                ${r.status !== 'in_progress' ? '<button class="btn btn-accent" id="cmd-ack">🙋 Je prends en charge</button>' : ''}
                <button class="btn btn-success" id="cmd-resolve">✅ Marquer résolu (vérification ${r.handled_by === 'n8n' ? 'n8n risk-verify' : 'FollowUpAgent'})</button>
                <button class="btn btn-warn" id="cmd-escalate">⬆️ Escalader au médecin</button>
            </div>` : ''}
            ${r.type === 'fever' ? '<div id="fever-panel-host"></div>' : ''}
            ${r.visits && r.visits.length ? `<h3>Visites</h3>${r.visits.map(v => `<div class="detail-row"><span class="detail-label">${Api.fmtTime(v.started_at)} → ${v.ended_at ? Api.fmtTime(v.ended_at) : 'en cours'}</span><span class="detail-value">${v.persons} pers.</span></div>`).join('')}` : ''}`;
    }

    function equipmentHtml() {
        return ['101', '102', '103', '104'].map(room => {
            const live = (window.RoomLive && RoomLive.get(room) && RoomLive.get(room).equipment) || {};
            const eq = equipment[room] || {};
            return `<div class="card" style="margin-bottom:8px"><h3><span class="room-pill">Chambre ${room}</span></h3>
                ${EQ.map(([k, label, onA, offA, icon]) => {
                    const state = live[k] || (eq[k] && eq[k].state) || 'off';
                    const isOn = state === 'on' || state === 'open';
                    return `<div class="detail-row"><span class="detail-label">${icon} ${label} <span class="tag ${isOn ? 'tag-low' : ''}">${state}</span></span>
                        <span><button class="btn btn-sm" data-cmd="${room}|${k}|${isOn ? offA : onA}" ${canControl() ? '' : 'disabled'}>${isOn ? (k === 'window' ? 'Fermer' : 'Éteindre') : (k === 'window' ? 'Ouvrir' : 'Allumer')}</button></span></div>`;
                }).join('')}</div>`;
        }).join('');
    }

    async function render(el) {
        el.innerHTML = `<div class="ai-hint">Centre de commande : plan d'action proposé par l'IA, coché étape par étape ; la résolution est vérifiée par le FollowUpAgent. ${canControl() ? '' : 'Commandes d\'équipements en lecture seule pour votre rôle.'}</div>
            <div class="grid-3" style="grid-template-columns: 0.9fr 1.5fr 0.9fr; align-items:start">
                <div class="card"><h3>Risques ouverts</h3><div id="cmd-list"></div></div>
                <div class="card" id="cmd-plan"></div>
                <div><div class="card" style="margin-bottom:8px"><h3>Équipements</h3><div class="muted small">Commandes transmises à l'edge (MQTT) ou au simulateur ; ack attendu.</div></div><div id="cmd-equipment"></div></div>
            </div>`;
        await refresh();
    }

    let refreshTimer = null;
    function refreshSoon() { if (refreshTimer) return; refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 800); }
    async function refresh() {
        if (!mounted) return;
        try { await fetchAll(); } catch (e) { Api.toast(e.message, 'critical'); return; }
        paint();
    }

    function paint() {
        const list = document.getElementById('cmd-list'); if (!list) return;
        list.innerHTML = listHtml();
        list.querySelectorAll('[data-id]').forEach(c => c.addEventListener('click', () => select(Number(c.dataset.id))));
        const plan = document.getElementById('cmd-plan');
        const r = rows.find(x => x.id === selected) || (selected ? window._cmdSelectedCache : null);
        plan.innerHTML = planHtml(r);
        const profHost = plan.querySelector('#cmd-profile');
        if (profHost && window.ClinicalProfile) ClinicalProfile.mount(profHost, r.patient_id);
        const feverHost = plan.querySelector('#fever-panel-host');
        if (feverHost && window.FeverPanel) FeverPanel.mount(feverHost, r.id); else if (window.FeverPanel) FeverPanel.unmount();
        plan.querySelectorAll('input[data-step]').forEach(cb => cb.addEventListener('change', async () => {
            try { const d = await Api.patch(`/api/risks/${r.id}/steps/${cb.dataset.step}`, { done: cb.checked }); merge(d); paint(); } catch (e) { Api.toast(e.message, 'critical'); }
        }));
        plan.querySelector('#cmd-add-step')?.addEventListener('click', async () => {
            const inp = plan.querySelector('#cmd-new-step'); if (!inp.value.trim()) return;
            try { const d = await Api.post(`/api/risks/${r.id}/steps`, { text: inp.value.trim() }); merge(d); paint(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        plan.querySelector('#cmd-ack')?.addEventListener('click', async () => {
            try { const d = await Api.post(`/api/risks/${r.id}/ack`); merge(d); paint(); Api.toast((d.n8n_resumed ? 'Prise en charge enregistrée — n8n informé (attente levée).' : 'Prise en charge enregistrée.') + (d.resolution ? ` ${d.resolution.role_label} en route (chambre ${d.room}, simulation).` : ''), 'success'); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        plan.querySelector('#cmd-resolve')?.addEventListener('click', async () => {
            try { const d = await Api.post(`/api/risks/${r.id}/resolve`); merge(d); paint(); Api.toast('Résolution demandée : le FollowUpAgent va re-vérifier la chambre.', 'success'); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        plan.querySelector('#cmd-escalate')?.addEventListener('click', async () => {
            try { const d = await Api.patch(`/api/risks/${r.id}`, { status: 'escalated', notes: 'escalade manuelle' }); merge(d); paint(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        const eqHost = document.getElementById('cmd-equipment');
        eqHost.innerHTML = equipmentHtml();
        eqHost.querySelectorAll('button[data-cmd]').forEach(b => b.addEventListener('click', async () => {
            const [room, equipment, action] = b.dataset.cmd.split('|');
            b.disabled = true;
            try {
                const res = await Api.post('/api/commands', { room, equipment, action, reason: 'commande manuelle depuis le centre de commande' });
                Api.toast(res.ok ? `✔ ${equipment} ${action} (chambre ${room}, ${res.transport})` : `Commande envoyée sans accusé (${res.transport})`, res.ok ? 'success' : 'warning');
            } catch (e) { Api.toast(e.message, 'critical'); }
            setTimeout(refresh, 400);
        }));
    }

    function merge(d) {
        const i = rows.findIndex(x => x.id === d.id);
        if (i >= 0) rows[i] = d; else rows.unshift(d);
        window._cmdSelectedCache = d;
    }

    async function select(id) {
        selected = id;
        if (!rows.find(x => x.id === id)) { try { window._cmdSelectedCache = await Api.get(`/api/risks/${id}`); } catch (_) { } }
        if (mounted) paint();
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (!mounted) return;
        if (m.type === 'risk') { if (m.risk) merge(m.risk); refreshSoon(); }
        else if (m.type === 'cmd_ack') refreshSoon();
    });
    Views.register('command', { title: 'Centre de commande', perm: 'view_command', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    return { select, refresh };
})();

window.CommandView = CommandView;
