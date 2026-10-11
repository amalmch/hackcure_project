/**
 * Vue « Historique patients » : admissions passées et en cours, rapports, ordonnances, risques, traitements, humeur.
 */
const HistoryView = (() => {
    'use strict';
    let selected = null, mounted = false, host = null;
    const MOOD = { calm: 'calme', anxious: 'anxieux', pain: 'douloureux', sad: 'triste', agitated: 'agité', neutral: 'neutre', happy: 'serein', surprised: 'surpris' };

    async function render(el) {
        host = el;
        let patients = [];
        try { patients = await Api.get('/api/records'); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        if (!selected && patients.length) selected = patients[0].patient_id;
        el.innerHTML = `<div class="view-toolbar"><label class="small">Patient <select id="hist-sel">${patients.map(p => `<option value="${p.patient_id}" ${p.patient_id === selected ? 'selected' : ''}>${Api.esc(p.full_name)} (${p.code})</option>`).join('')}</select></label></div><div id="hist-body"></div>`;
        el.querySelector('#hist-sel').addEventListener('change', e => { selected = e.target.value; paint(); });
        await paint();
    }

    async function paint() {
        const b = document.getElementById('hist-body'); if (!b || !selected) return;
        let h;
        try { h = await Api.get(`/api/records/${selected}/history`); } catch (e) { b.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        const p = h.patient;
        b.innerHTML = `<div id="hist-profile"></div><div class="card"><h3>${Api.esc(p.full_name)} · ${p.code} · ${p.age} ans · groupe ${p.blood_group}</h3><div class="small">Allergies : ${p.allergies ? `<span class="tag tag-danger">${Api.esc(p.allergies)}</span>` : 'aucune connue'} · Risque de chute : ${p.fall_risk} · Antécédents : ${Api.esc(p.history || '—')}</div></div>`
            + h.admissions.map(a => `<div class="card">
                <h3>${a.active ? '🛏️ Séjour en cours' : '📁 Séjour'} — chambre ${a.room} · du ${Api.fmtDate(a.admitted_at)} ${a.discharged_at ? 'au ' + Api.fmtDate(a.discharged_at) : ''} · ${Api.esc(a.reason)} <span class="muted small">(${Api.esc(a.referring_doctor)})</span></h3>
                <div class="grid-2">
                    <div><b class="small">Rapports médecin</b><ul class="small">${a.reports.map(r => `<li>${Api.esc(r.title)} — ${r.status === 'signed' ? '✅ signé' : '📝 brouillon' + (r.ai_draft ? ' IA' : '')} par ${Api.esc(r.author)} le ${Api.fmtDate(r.created_at)} ${Auth.can('view_medical_docs') ? `<a href="/print/report/${r.id}" target="_blank" style="color:#93c5fd">imprimer</a>` : ''}</li>`).join('') || '<li class="muted">aucun</li>'}</ul>
                    <b class="small">Ordonnances</b><ul class="small">${a.prescriptions.map(pr => `<li>${pr.lines} ligne(s) — ${pr.status === 'signed' ? '✅ signée' : '📝 brouillon'} par ${Api.esc(pr.prescriber)} le ${Api.fmtDate(pr.created_at)} ${Auth.can('view_medical_docs') ? `<a href="/print/prescription/${pr.id}" target="_blank" style="color:#93c5fd">imprimer</a>` : ''}</li>`).join('') || '<li class="muted">aucune</li>'}</ul></div>
                    <div><b class="small">Risques (${a.risks.length})</b><ul class="small">${a.risks.slice(0, 12).map(r => `<li>${Api.fmtDateTime(r.detected_at)} — ${Api.esc(r.title)} <span class="tag tag-${r.severity}">${r.severity}</span> <span class="tag tag-${r.status}">${r.status}</span></li>`).join('') || '<li class="muted">aucun</li>'}</ul>
                    <b class="small">Traitements</b><ul class="small">${a.treatments.map(t => `<li>${Api.esc(t.dci)} (${Api.esc(t.brand)}) ${Api.esc(t.posology)} ${t.route}${t.end ? ' — arrêté' : ''}</li>`).join('') || '<li class="muted">aucun</li>'}</ul>
                    <b class="small">Humeur observée</b> <span class="small">${Object.keys(a.moods).length ? Object.entries(a.moods).map(([m, n]) => `${MOOD[m] || m} ×${n}`).join(', ') : 'non évaluée'} · ${a.snapshots} observations de posture</span></div>
                </div></div>`).join('');
        if (window.ClinicalProfile) ClinicalProfile.mount(document.getElementById('hist-profile'), selected);
    }

    function select(pid) { selected = pid; if (mounted && host) render(host); }
    Views.register('history', { title: 'Historique patients', perm: 'view_history', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    return { select };
})();

window.HistoryView = HistoryView;
