/**
 * Vue « Rapport médecin » : liste, éditeur, brouillon IA (ReportAgent), signature, impression.
 */
const ReportView = (() => {
    'use strict';
    let mounted = false, host = null, reports = [], patients = [], current = null, admissionId = null;

    async function load() {
        reports = await Api.get('/api/reports');
        patients = (await Api.get('/api/records?active_only=1'));
    }

    function editorHtml(r) {
        const canWrite = Auth.can('write_medical_docs');
        if (!r) return `<div class="empty">Sélectionnez un rapport${canWrite ? ' ou créez-en un' : ''}</div>`;
        const locked = r.status === 'signed' || !canWrite;
        return `<h3>${Api.esc(r.title)} — ${Api.esc(r.patient)} <span class="tag tag-${r.status}">${r.status === 'signed' ? 'signé' : 'brouillon'}</span> ${r.ai_draft ? '<span class="tag">brouillon IA</span>' : ''}</h3>
            <div class="small muted">Chambre ${r.room} · auteur ${Api.esc(r.author)} · créé le ${Api.fmtDateTime(r.created_at)}${r.signed_at ? ' · signé le ' + Api.fmtDateTime(r.signed_at) : ''}</div>
            ${r.ai_draft && r.status !== 'signed' ? '<div class="ai-hint">Brouillon rédigé par le ReportAgent à partir du dossier (valeurs mesurées uniquement). À relire, compléter et signer.</div>' : ''}
            <input id="rep-title" value="${Api.esc(r.title)}" ${locked ? 'disabled' : ''} style="width:100%;margin:8px 0;padding:7px 10px;border-radius:6px;border:1px solid var(--border-subtle);background:rgba(2,6,23,.6);color:var(--text-primary)">
            <textarea id="rep-content" class="doc-editor" ${locked ? 'disabled' : ''}>${Api.esc(r.content)}</textarea>
            <div class="inline-form" style="margin-top:10px">
                ${!locked ? '<button class="btn btn-success" id="rep-save">💾 Enregistrer</button><button class="btn btn-accent" id="rep-sign">✍️ Signer</button>' : ''}
                <a class="btn" href="/print/report/${r.id}" target="_blank">🖨️ Imprimer / PDF</a>
            </div>`;
    }

    async function render(el) {
        host = el;
        try { await load(); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        const canWrite = Auth.can('write_medical_docs');
        el.innerHTML = `<div class="view-toolbar">
            ${canWrite ? `<label class="small">Patient hospitalisé <select id="rep-adm">${patients.map(p => `<option value="${p.admission.id}" ${p.admission.id === admissionId ? 'selected' : ''}>${p.room} — ${Api.esc(p.full_name)}</option>`).join('')}</select></label>
            <button class="btn btn-accent" id="rep-draft">🤖 Brouillon IA</button><button class="btn" id="rep-new">＋ Rapport vide</button>` : '<span class="muted small">Lecture seule pour votre rôle.</span>'}</div>
            <div class="grid-2" style="grid-template-columns: 0.8fr 1.6fr; align-items:start"><div class="card"><h3>Rapports (${reports.length})</h3><div id="rep-list"></div></div><div class="card" id="rep-editor"></div></div>`;
        el.querySelector('#rep-adm')?.addEventListener('change', e => { admissionId = Number(e.target.value); });
        el.querySelector('#rep-draft')?.addEventListener('click', async () => {
            const adm = Number(el.querySelector('#rep-adm').value); const b = el.querySelector('#rep-draft'); b.disabled = true; b.textContent = '🤖 Rédaction…';
            try { const r = await Api.post('/api/reports/draft', { admission_id: adm }); Api.toast('Brouillon IA généré', 'success'); current = r.id; render(el); } catch (e) { Api.toast(e.message, 'critical'); b.disabled = false; b.textContent = '🤖 Brouillon IA'; }
        });
        el.querySelector('#rep-new')?.addEventListener('click', async () => {
            try { const r = await Api.post('/api/reports', { admission_id: Number(el.querySelector('#rep-adm').value), title: 'Compte rendu médical', content: '' }); current = r.id; render(el); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        paint();
    }

    function paint() {
        const list = document.getElementById('rep-list'); if (!list) return;
        list.innerHTML = reports.map(r => `<div class="agent-card" data-id="${r.id}" style="cursor:pointer;margin-bottom:6px;${current === r.id ? 'border-color:var(--border-active)' : ''}"><div class="agent-head"><span class="agent-name">${Api.esc(r.patient)}</span><span class="tag tag-${r.status}">${r.status === 'signed' ? 'signé' : 'brouillon'}</span></div><div class="muted small">${Api.esc(r.title)} · ${Api.fmtDate(r.created_at)} · ${Api.esc(r.author)}</div></div>`).join('') || '<div class="empty">Aucun rapport</div>';
        list.querySelectorAll('[data-id]').forEach(c => c.addEventListener('click', () => { current = Number(c.dataset.id); paint(); }));
        const r = reports.find(x => x.id === current);
        const ed = document.getElementById('rep-editor'); ed.innerHTML = editorHtml(r);
        ed.querySelector('#rep-save')?.addEventListener('click', async () => {
            try { const d = await Api.patch(`/api/reports/${r.id}`, { title: ed.querySelector('#rep-title').value, content: ed.querySelector('#rep-content').value }); Object.assign(r, d); Api.toast('Rapport enregistré', 'success'); paint(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        ed.querySelector('#rep-sign')?.addEventListener('click', async () => {
            try { await Api.patch(`/api/reports/${r.id}`, { title: ed.querySelector('#rep-title').value, content: ed.querySelector('#rep-content').value }); const d = await Api.post(`/api/reports/${r.id}/sign`); Object.assign(r, d); Api.toast('Rapport signé', 'success'); paint(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }

    function selectAdmission(id) { admissionId = id; if (mounted && host) render(host); }
    Views.register('report', { title: 'Rapport médecin', perm: 'view_medical_docs', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    return { selectAdmission };
})();

window.ReportView = ReportView;
