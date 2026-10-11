/**
 * Vue « Rapport de garde » : génération par le ReportAgent, relecture / édition, validation, impression.
 */
(function () {
    'use strict';
    let mounted = false, host = null, reports = [], current = null;

    function mdToHtml(md) {
        const esc = Api.esc;
        let html = '', inList = false;
        md.split('\n').forEach(line => {
            let s = esc(line).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/_(.+?)_/g, '<i>$1</i>');
            if (s.startsWith('- ')) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${s.slice(2)}</li>`; return; }
            if (inList) { html += '</ul>'; inList = false; }
            if (s.startsWith('## ')) html += `<h3>${s.slice(3)}</h3>`; else if (s.startsWith('# ')) html += `<h2>${s.slice(2)}</h2>`; else if (s.trim()) html += `<p>${s}</p>`;
        });
        if (inList) html += '</ul>';
        return html;
    }

    async function render(el) {
        host = el;
        try { reports = await Api.get('/api/shift-reports'); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        const canEdit = Auth.can('edit_shift_report');
        el.innerHTML = `<div class="view-toolbar">${canEdit ? `<label class="small">Période <select id="sh-hours"><option value="8">8 h</option><option value="12" selected>12 h</option><option value="24">24 h</option></select></label><button class="btn btn-accent" id="sh-gen">🤖 Générer le rapport de garde</button>` : '<span class="muted small">Lecture seule pour votre rôle.</span>'}</div>
            <div class="grid-2" style="grid-template-columns: 0.7fr 1.8fr; align-items:start"><div class="card"><h3>Rapports (${reports.length})</h3><div id="sh-list"></div></div><div class="card" id="sh-editor"></div></div>`;
        el.querySelector('#sh-gen')?.addEventListener('click', async () => {
            const b = el.querySelector('#sh-gen'); b.disabled = true; b.textContent = '🤖 Rédaction…';
            try {
                const r = await Api.post('/api/shift-reports/generate', { hours: Number(el.querySelector('#sh-hours').value) });
                if (r && r.status === 'n8n') { Api.toast('n8n rédige le rapport de garde (workflow shift-report)… il apparaîtra dans la liste.', 'info'); b.textContent = '⏳ n8n rédige…'; return; }
                current = r.id; Api.toast('Rapport de garde généré (brouillon)', 'success'); render(el);
            } catch (e) { Api.toast(e.message, 'critical'); b.disabled = false; b.textContent = '🤖 Générer le rapport de garde'; }
        });
        if (!current && reports.length) current = reports[0].id;
        paint();
    }

    function paint() {
        const list = document.getElementById('sh-list'); if (!list) return;
        list.innerHTML = reports.map(r => `<div class="agent-card" data-id="${r.id}" style="cursor:pointer;margin-bottom:6px;${current === r.id ? 'border-color:var(--border-active)' : ''}"><div class="agent-head"><span class="agent-name">#${r.id}</span><span class="tag tag-${r.status}">${r.status === 'validated' ? 'validé' : 'brouillon'}</span></div><div class="muted small">${Api.fmtDateTime(r.shift_start)} → ${Api.fmtDateTime(r.shift_end)}</div></div>`).join('') || '<div class="empty">Aucun rapport</div>';
        list.querySelectorAll('[data-id]').forEach(c => c.addEventListener('click', () => { current = Number(c.dataset.id); paint(); }));
        const r = reports.find(x => x.id === current);
        const ed = document.getElementById('sh-editor');
        if (!r) { ed.innerHTML = '<div class="empty">Générez ou sélectionnez un rapport</div>'; return; }
        const locked = r.status === 'validated' || !Auth.can('edit_shift_report');
        ed.innerHTML = `<h3>Rapport de garde #${r.id} <span class="tag tag-${r.status}">${r.status === 'validated' ? 'validé' : 'brouillon'}</span></h3>
            <div class="small muted">${Api.fmtDateTime(r.shift_start)} → ${Api.fmtDateTime(r.shift_end)} · ${Api.esc(r.author)}${r.validated_by ? ' · validé par ' + Api.esc(r.validated_by) : ''}</div>
            <div class="ai-hint">Généré par le ReportAgent à partir des événements, risques, actions, états et humeurs enregistrés. Relire avant validation.</div>
            <div class="grid-2"><textarea id="sh-content" class="doc-editor" ${locked ? 'disabled' : ''} style="min-height:420px">${Api.esc(r.content)}</textarea><div class="md-preview card" id="sh-preview" style="max-height:440px;overflow:auto">${mdToHtml(r.content)}</div></div>
            <div class="inline-form" style="margin-top:10px">${!locked ? '<button class="btn btn-success" id="sh-save">💾 Enregistrer</button><button class="btn btn-accent" id="sh-validate">✅ Valider</button>' : ''}<a class="btn" href="/print/shift/${r.id}" target="_blank">🖨️ Imprimer / PDF</a></div>`;
        ed.querySelector('#sh-content')?.addEventListener('input', e => { ed.querySelector('#sh-preview').innerHTML = mdToHtml(e.target.value); });
        ed.querySelector('#sh-save')?.addEventListener('click', async () => { try { const d = await Api.patch(`/api/shift-reports/${r.id}`, { content: ed.querySelector('#sh-content').value }); Object.assign(r, d); Api.toast('Enregistré', 'success'); } catch (e) { Api.toast(e.message, 'critical'); } });
        ed.querySelector('#sh-validate')?.addEventListener('click', async () => { try { await Api.patch(`/api/shift-reports/${r.id}`, { content: ed.querySelector('#sh-content').value }); const d = await Api.post(`/api/shift-reports/${r.id}/validate`); Object.assign(r, d); Api.toast('Rapport validé', 'success'); paint(); } catch (e) { Api.toast(e.message, 'critical'); } });
    }

    window.addEventListener('hackcure:ws', (e) => { if (mounted && host && e.detail.type === 'shift_report') { current = e.detail.id; Api.toast('Rapport de garde reçu de n8n', 'success'); render(host); } });
    Views.register('shift', { title: 'Rapport de garde', perm: 'view_shift_report', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
})();
