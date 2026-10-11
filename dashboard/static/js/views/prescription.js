/**
 * Vue « Ordonnance » : lignes depuis l'inventaire, alerte allergie en direct, signature, impression.
 */
const PrescriptionView = (() => {
    'use strict';
    let mounted = false, host = null, prescriptions = [], patients = [], meds = [], current = null, admissionId = null, draftLines = [];

    async function load() {
        prescriptions = await Api.get('/api/prescriptions');
        patients = await Api.get('/api/records?active_only=1');
        meds = await Api.get('/api/pharmacy/medications');
    }

    function patientFor(adm) { return patients.find(p => p.admission && p.admission.id === adm); }

    function linesTable(lines, editable) {
        return `<table class="data"><thead><tr><th>Médicament</th><th>Dosage</th><th>Fréquence</th><th>Durée</th><th>Voie</th><th>Allergie</th>${editable ? '<th></th>' : ''}</tr></thead><tbody>
            ${lines.map((l, i) => { const m = l.medication || meds.find(x => x.id === l.medication_id) || {}; return `<tr class="${l.allergy_warning ? 'selected' : ''}"><td>${Api.esc(m.dci || '')} <span class="muted">(${Api.esc(m.brand || '')})</span></td><td>${Api.esc(l.dosage)}</td><td>${Api.esc(l.frequency)}</td><td>${l.duration_days} j</td><td>${l.route}</td>
                <td>${l.allergy_warning ? `<span class="tag tag-danger">⚠ ${(l.conflicts || []).join(', ')}</span>` : '<span class="tag tag-low">ok</span>'}</td>${editable ? `<td><button class="btn btn-sm btn-danger" data-rm="${i}">✕</button></td>` : ''}</tr>`; }).join('') || `<tr><td colspan="7" class="muted">aucune ligne</td></tr>`}</tbody></table>`;
    }

    function editorHtml() {
        const canWrite = Auth.can('write_medical_docs');
        const pr = prescriptions.find(x => x.id === current);
        if (pr) {
            const locked = pr.status === 'signed' || !canWrite;
            return `<h3>Ordonnance #${pr.id} — ${Api.esc(pr.patient)} <span class="tag tag-${pr.status}">${pr.status === 'signed' ? 'signée' : 'brouillon'}</span></h3>
                <div class="small muted">Chambre ${pr.room} · ${pr.patient_age} ans · allergies : ${pr.patient_allergies ? `<span class="tag tag-danger">${Api.esc(pr.patient_allergies)}</span>` : 'aucune connue'} · prescripteur ${Api.esc(pr.prescriber)} · ${Api.fmtDateTime(pr.created_at)}</div>
                ${pr.has_allergy_warning ? '<div class="allergy-alert">⚠ ALERTE ALLERGIE : une ligne est contre-indiquée par les allergies du patient. Corrigez avant signature.</div>' : ''}
                ${linesTable(pr.lines, false)}
                ${pr.notes ? `<p class="small"><b>Remarques :</b> ${Api.esc(pr.notes)}</p>` : ''}
                <div class="inline-form" style="margin-top:10px">
                    ${!locked ? `<button class="btn btn-accent" id="pr-sign" ${pr.has_allergy_warning ? 'disabled title="Corriger l\'alerte allergie"' : ''}>✍️ Signer</button><button class="btn btn-danger" id="pr-del">🗑 Supprimer le brouillon</button>` : ''}
                    <a class="btn" href="/print/prescription/${pr.id}" target="_blank">🖨️ Imprimer / PDF</a>
                </div>`;
        }
        if (!canWrite) return '<div class="empty">Sélectionnez une ordonnance (lecture seule pour votre rôle)</div>';
        const p = patientFor(admissionId);
        return `<h3>Nouvelle ordonnance ${p ? `— ${Api.esc(p.full_name)} (chambre ${p.room})` : ''}</h3>
            ${p && p.allergies ? `<div class="small">Allergies connues : <span class="tag tag-danger">${Api.esc(p.allergies)}</span></div>` : ''}
            <div id="pr-alert"></div>
            ${linesTable(draftLines, true)}
            <div class="inline-form" style="margin-top:10px"><select id="pr-med" style="min-width:220px">${meds.map(m => `<option value="${m.id}">${Api.esc(m.dci)} (${Api.esc(m.brand)}) ${Api.esc(m.dosage)}</option>`).join('')}</select>
                <input id="pr-dose" placeholder="dosage" style="width:90px"><input id="pr-freq" placeholder="fréquence" style="width:110px"><input id="pr-days" type="number" value="5" style="width:60px"><select id="pr-route"><option>PO</option><option>IV</option><option>SC</option><option>IM</option><option>INH</option></select><button class="btn btn-sm" id="pr-add">＋ Ligne</button></div>
            <textarea id="pr-notes" class="doc-editor" style="min-height:60px;margin-top:8px" placeholder="Remarques"></textarea>
            <div class="inline-form" style="margin-top:8px"><button class="btn btn-success" id="pr-create" ${draftLines.length ? '' : 'disabled'}>💾 Créer le brouillon</button></div>`;
    }

    async function render(el) {
        host = el;
        try { await load(); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        if (!admissionId && patients.length) admissionId = patients[0].admission.id;
        el.innerHTML = `<div class="view-toolbar">${Auth.can('write_medical_docs') ? `<label class="small">Patient hospitalisé <select id="pr-adm">${patients.map(p => `<option value="${p.admission.id}" ${p.admission.id === admissionId ? 'selected' : ''}>${p.room} — ${Api.esc(p.full_name)}</option>`).join('')}</select></label><button class="btn btn-accent" id="pr-new">＋ Nouvelle ordonnance</button>` : ''}</div>
            <div class="grid-2" style="grid-template-columns: 0.8fr 1.6fr; align-items:start"><div class="card"><h3>Ordonnances (${prescriptions.length})</h3><div id="pr-list"></div></div><div class="card" id="pr-editor"></div></div>`;
        el.querySelector('#pr-adm')?.addEventListener('change', e => { admissionId = Number(e.target.value); draftLines = []; current = null; paint(); });
        el.querySelector('#pr-new')?.addEventListener('click', () => { current = null; draftLines = []; paint(); });
        paint();
    }

    function paint() {
        const list = document.getElementById('pr-list'); if (!list) return;
        list.innerHTML = prescriptions.map(pr => `<div class="agent-card" data-id="${pr.id}" style="cursor:pointer;margin-bottom:6px;${current === pr.id ? 'border-color:var(--border-active)' : ''}"><div class="agent-head"><span class="agent-name">#${pr.id} ${Api.esc(pr.patient)}</span><span class="tag tag-${pr.status}">${pr.status === 'signed' ? 'signée' : 'brouillon'}</span></div><div class="muted small">${pr.lines.length} ligne(s) · ${Api.fmtDate(pr.created_at)} ${pr.has_allergy_warning ? '· <span class="tag tag-danger">allergie</span>' : ''}</div></div>`).join('') || '<div class="empty">Aucune ordonnance</div>';
        list.querySelectorAll('[data-id]').forEach(c => c.addEventListener('click', () => { current = Number(c.dataset.id); paint(); }));
        const ed = document.getElementById('pr-editor'); ed.innerHTML = editorHtml();
        ed.querySelector('#pr-add')?.addEventListener('click', async () => {
            const medId = Number(ed.querySelector('#pr-med').value);
            let conflicts = [];
            try { const c = await Api.post('/api/prescriptions/check', { admission_id: admissionId, medication_id: medId }); conflicts = c.conflicts; if (c.warning) { Api.toast(c.warning, 'critical'); ed.querySelector('#pr-alert').innerHTML = `<div class="allergy-alert">${Api.esc(c.warning)}</div>`; } } catch (_) { }
            draftLines.push({ medication_id: medId, dosage: ed.querySelector('#pr-dose').value, frequency: ed.querySelector('#pr-freq').value, duration_days: Number(ed.querySelector('#pr-days').value) || 5, route: ed.querySelector('#pr-route').value, allergy_warning: conflicts.length > 0, conflicts });
            paint();
        });
        ed.querySelectorAll('[data-rm]').forEach(b => b.addEventListener('click', () => { draftLines.splice(Number(b.dataset.rm), 1); paint(); }));
        ed.querySelector('#pr-create')?.addEventListener('click', async () => {
            try { const r = await Api.post('/api/prescriptions', { admission_id: admissionId, notes: ed.querySelector('#pr-notes').value, lines: draftLines.map(l => ({ medication_id: l.medication_id, dosage: l.dosage, frequency: l.frequency, duration_days: l.duration_days, route: l.route })) }); draftLines = []; current = r.id; await load(); paint(); Api.toast(r.has_allergy_warning ? 'Brouillon créé avec ALERTE ALLERGIE' : 'Brouillon créé', r.has_allergy_warning ? 'critical' : 'success'); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        ed.querySelector('#pr-sign')?.addEventListener('click', async () => {
            try { await Api.post(`/api/prescriptions/${current}/sign`); await load(); paint(); Api.toast('Ordonnance signée', 'success'); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        ed.querySelector('#pr-del')?.addEventListener('click', async () => {
            try { await Api.del(`/api/prescriptions/${current}`); current = null; await load(); paint(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }

    function selectAdmission(id) { admissionId = id; current = null; draftLines = []; if (mounted && host) render(host); }
    Views.register('prescription', { title: 'Ordonnance', perm: 'view_medical_docs', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    return { selectAdmission };
})();

window.PrescriptionView = PrescriptionView;
