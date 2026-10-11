/**
 * Vue « Patients » : liste, fiche, création / modification (selon le rôle), admission et sortie.
 */
const PatientsView = (() => {
    'use strict';
    let rows = [], selected = null, mounted = false, host = null;
    const FALL = { low: ['faible', 'tag-low'], medium: ['moyen', 'tag-medium'], high: ['élevé', 'tag-high'] };

    // SpO2 en direct (oxymètre de pouls de la chambre)
    function spo2Cell(room) {
        const v = room && window.SensorPanel && SensorPanel.rooms[room] && (SensorPanel.rooms[room].vitals || {}).spo2;
        if (v == null) return '<span class="muted">—</span>';
        return `<span class="tag ${v < 90 ? 'tag-danger' : v < 94 ? 'tag-warn' : 'tag-ok'}" title="Saturation en oxygène (oxymètre de pouls)">${Math.round(v)} %</span>`;
    }

    function listHtml() {
        return `<table class="data"><thead><tr><th>Code</th><th>Identifiant</th><th>Nom</th><th>Âge</th><th>Chambre</th><th>SpO2</th><th>Risque chute</th><th>État</th></tr></thead><tbody>
            ${rows.map(p => `<tr data-id="${p.patient_id}" class="${selected === p.patient_id ? 'selected' : ''}"><td>${p.code}</td><td class="muted">${p.patient_id}</td><td>${Api.esc(p.full_name)} <span class="muted small">(${Api.esc(p.display_name)})</span></td><td>${p.age}</td>
            <td>${p.room ? `<span class="room-pill">${p.room}</span>` : '<span class="muted">sorti</span>'}</td><td>${spo2Cell(p.room)}</td><td><span class="tag ${FALL[p.fall_risk][1]}">${FALL[p.fall_risk][0]}</span></td><td class="small">${p.legacy_state || '—'}</td></tr>`).join('')}
        </tbody></table>`;
    }

    function formHtml(p) {
        const v = (k, d = '') => Api.esc((p && p[k]) ?? d);
        return `<div class="form-grid">
            <label>Prénom<input name="first_name" value="${v('first_name')}"></label><label>Nom<input name="last_name" value="${v('last_name')}"></label>
            <label>Date de naissance<input type="date" name="birth_date" value="${v('birth_date')}"></label>
            <label>Sexe<select name="sex"><option value="M" ${p && p.sex === 'M' ? 'selected' : ''}>M</option><option value="F" ${p && p.sex === 'F' ? 'selected' : ''}>F</option></select></label>
            <label>Groupe sanguin<input name="blood_group" value="${v('blood_group', 'O+')}"></label>
            <label>Risque de chute<select name="fall_risk">${['low', 'medium', 'high'].map(k => `<option value="${k}" ${p && p.fall_risk === k ? 'selected' : ''}>${FALL[k][0]}</option>`).join('')}</select></label>
            <label class="full">Allergies (séparées par des virgules)<input name="allergies" value="${v('allergies')}" placeholder="ex. pénicilline, AINS"></label>
            <label class="full">Antécédents<textarea name="history">${v('history')}</textarea></label>
            <label>Étiquette 3D<input name="display_name" value="${v('display_name')}" placeholder="Patient E"></label>
            ${!p ? `<label>Chambre (admission)<select name="room"><option value="">— pas d'admission —</option>${['101', '102', '103', '104'].map(r => `<option value="${r}">${r}</option>`).join('')}</select></label><label class="full">Motif<input name="reason"></label>` : ''}
        </div>`;
    }

    function readForm(el) {
        const d = {};
        el.querySelectorAll('[name]').forEach(i => { d[i.name] = i.value; });
        if (!d.room) delete d.room;
        return d;
    }

    function detailHtml(p) {
        if (!p) return `<div class="empty">Sélectionnez un patient${Auth.can('create_patients') ? ' ou créez-en un' : ''}</div>`;
        const canEdit = Auth.can('edit_patients');
        const risks = (p.open_risks || []).map(r => `<span class="tag tag-${r.severity}">${Api.esc(r.type_label)}</span>`).join(' ') || '<span class="muted">aucun</span>';
        const tr = (p.treatments || []).map(t => `<li>${Api.esc(t.dci)} (${Api.esc(t.brand)}) ${Api.esc(t.posology)} ${t.route}</li>`).join('') || '<li class="muted">aucun</li>';
        return `<h3>${Api.esc(p.full_name)} · ${p.code}</h3>
            <div class="detail-row"><span class="detail-label">Identifiant 3D</span><span class="detail-value">${p.patient_id} (${Api.esc(p.display_name)})</span></div>
            <div class="detail-row"><span class="detail-label">Âge / sexe</span><span class="detail-value">${p.age} ans · ${p.sex}</span></div>
            <div class="detail-row"><span class="detail-label">Groupe</span><span class="detail-value">${p.blood_group}</span></div>
            <div class="detail-row"><span class="detail-label">Allergies</span><span class="detail-value">${p.allergies ? `<span class="tag tag-danger">${Api.esc(p.allergies)}</span>` : 'aucune connue'}</span></div>
            <div class="detail-row"><span class="detail-label">Risque de chute</span><span class="detail-value"><span class="tag ${FALL[p.fall_risk][1]}">${FALL[p.fall_risk][0]}</span></span></div>
            <div class="detail-row"><span class="detail-label">Chambre</span><span class="detail-value">${p.room ? `${p.room} — admis le ${Api.fmtDate(p.admission.admitted_at)} (${Api.esc(p.admission.reason)})` : 'non hospitalisé'}</span></div>
            <p class="small" style="margin:8px 0"><b>Antécédents :</b> ${Api.esc(p.history || '—')}</p>
            <p class="small"><b>Risques ouverts :</b> ${risks}</p>
            <p class="small"><b>Traitements :</b></p><ul class="small">${tr}</ul>
            <div class="inline-form" style="margin-top:10px">
                ${canEdit ? `<button class="btn btn-sm" id="pat-edit">✏️ Modifier</button>` : ''}
                ${canEdit && !p.room ? `<select id="pat-room">${['101', '102', '103', '104'].map(r => `<option value="${r}">${r}</option>`).join('')}</select><button class="btn btn-sm btn-success" id="pat-admit">🛏️ Admettre</button>` : ''}
                ${canEdit && p.room ? `<button class="btn btn-sm btn-warn" id="pat-discharge">🚪 Sortie</button>` : ''}
                ${Auth.can('view_history') ? `<button class="btn btn-sm" id="pat-history">🗂️ Historique</button>` : ''}
                ${Auth.can('view_medical_docs') ? `<button class="btn btn-sm" id="pat-report">📝 Rapport</button><button class="btn btn-sm" id="pat-presc">℞ Ordonnance</button>` : ''}
            </div>
            <div id="pat-editor"></div>`;
    }

    async function render(el) {
        host = el;
        el.innerHTML = `<div class="view-toolbar"><input id="pat-q" placeholder="Rechercher (nom, code, chambre)…"><label class="small"><input type="checkbox" id="pat-active"> hospitalisés seulement</label><span class="spacer"></span>${Auth.can('create_patients') ? '<button class="btn btn-accent" id="pat-new">＋ Nouveau patient</button>' : ''}</div>
            <div class="grid-2" style="grid-template-columns: 1.2fr 1fr; align-items:start"><div class="card" id="pat-list"></div><div class="card" id="pat-detail"></div></div>`;
        el.querySelector('#pat-q').addEventListener('input', refresh);
        el.querySelector('#pat-active').addEventListener('change', refresh);
        el.querySelector('#pat-new')?.addEventListener('click', () => {
            const d = document.getElementById('pat-detail');
            d.innerHTML = `<h3>Nouveau patient</h3>${formHtml(null)}<div class="inline-form" style="margin-top:10px"><button class="btn btn-success" id="pat-save-new">Créer</button></div>`;
            d.querySelector('#pat-save-new').addEventListener('click', async () => {
                try { const p = await Api.post('/api/records', readForm(d)); selected = p.patient_id; Api.toast('Patient créé', 'success'); refresh(); } catch (e) { Api.toast(e.message, 'critical'); }
            });
        });
        await refresh();
    }

    async function refresh() {
        if (!mounted) return;
        const q = document.getElementById('pat-q')?.value || '', active = document.getElementById('pat-active')?.checked;
        try { rows = await Api.get(`/api/records?q=${encodeURIComponent(q)}${active ? '&active_only=1' : ''}`); } catch (e) { Api.toast(e.message, 'critical'); return; }
        const list = document.getElementById('pat-list'); if (!list) return;
        list.innerHTML = listHtml();
        list.querySelectorAll('tr[data-id]').forEach(tr => tr.addEventListener('click', () => select(tr.dataset.id)));
        if (selected) paintDetail();
    }

    async function paintDetail() {
        const d = document.getElementById('pat-detail'); if (!d) return;
        let p = null;
        try { p = await Api.get(`/api/records/${selected}`); } catch (_) { }
        d.innerHTML = detailHtml(p);
        if (!p) return;
        d.querySelector('#pat-edit')?.addEventListener('click', () => {
            const ed = d.querySelector('#pat-editor');
            ed.innerHTML = `${formHtml(p)}<div class="inline-form" style="margin-top:8px"><button class="btn btn-success" id="pat-save">Enregistrer</button></div>`;
            ed.querySelector('#pat-save').addEventListener('click', async () => {
                try { await Api.patch(`/api/records/${p.patient_id}`, readForm(ed)); Api.toast('Patient mis à jour', 'success'); refresh(); } catch (e) { Api.toast(e.message, 'critical'); }
            });
        });
        d.querySelector('#pat-admit')?.addEventListener('click', async () => {
            try { await Api.post(`/api/records/${p.patient_id}/admit`, { room: d.querySelector('#pat-room').value, reason: 'admission' }); Api.toast('Patient admis', 'success'); refresh(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        d.querySelector('#pat-discharge')?.addEventListener('click', async () => {
            try { await Api.post(`/api/records/${p.patient_id}/discharge`); Api.toast('Sortie enregistrée', 'success'); refresh(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        d.querySelector('#pat-history')?.addEventListener('click', () => { Views.show('history'); HistoryView.select(p.patient_id); });
        d.querySelector('#pat-report')?.addEventListener('click', () => { Views.show('report'); ReportView.selectAdmission(p.admission ? p.admission.id : null); });
        d.querySelector('#pat-presc')?.addEventListener('click', () => { Views.show('prescription'); PrescriptionView.selectAdmission(p.admission ? p.admission.id : null); });
    }

    function select(id) { selected = id; refresh(); }
    Views.register('patients', { title: 'Patients', perm: 'view_patients', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    return { select };
})();

window.PatientsView = PatientsView;
