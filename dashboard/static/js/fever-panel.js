/**
 * HackCure — panneau « Parcours fièvre » (V2) affiché dans le Centre de commande pour un risque « Fièvre ».
 * 1. bilan clinique (checklist, médecin de garde) → 2. bilan biologique proposé, justifié, validé par le médecin
 * → 3. confort de la chambre (ensuite seulement) → 4. traitement, revérification, fin du risque.
 */
const FeverPanel = (() => {
    'use strict';
    let host = null, riskId = null, pathway = null;
    const STEPS = [['clinical_exam', '1. Bilan clinique'], ['lab_proposed', '2. Bilan biologique'], ['lab_ordered', '3. Confort'], ['lab_results', '4. Traitement et surveillance']];
    const ORDER = ['clinical_exam', 'lab_proposed', 'lab_ordered', 'lab_results', 'resolved'];
    const isDoctor = () => Auth.can('write_medical_docs');
    const canAct = () => Auth.can('manage_risks');

    function stepper(p) {
        const cur = ORDER.indexOf(p.stage);
        return `<div class="fever-steps">${STEPS.map(([k, l], i) => `<span class="fever-step ${i < cur ? 'done' : i === cur ? 'current' : ''}">${i < cur ? '✔ ' : ''}${l}</span>`).join('')}</div>`;
    }

    function aiBlock(a, title) {
        if (!a || !a.summary) return '';
        return `<div class="ai-hint">🧠 <b>${title}</b>${a.fallback ? ' <span class="tag tag-fallback">réponse de secours (LLM indisponible)</span>' : ''}<br>${Api.esc(a.summary)}
            ${a.exam_focus && a.exam_focus.length ? '<ul class="fever-list">' + a.exam_focus.map(x => `<li>${Api.esc(x)}</li>`).join('') + '</ul>' : ''}
            ${a.interpretation ? `<div style="margin-top:4px">${Api.esc(a.interpretation)}</div>` : ''}
            ${a.watch && a.watch.length ? '<div class="muted small" style="margin-top:4px">Surveillance : ' + a.watch.map(Api.esc).join(' · ') + '</div>' : ''}
            <span class="muted small">${Api.esc(a.provider || '')} — ${Api.esc(pathway.disclaimer)}</span></div>`;
    }

    function html(p) {
        const examOpen = p.stage === 'clinical_exam', labsOpen = p.stage === 'lab_proposed';
        const done = p.checklist.filter(c => c.done).length;
        const checklist = p.checklist.map(c => `<label><input type="checkbox" data-check="${c.key}" ${c.done ? 'checked' : ''} ${canAct() && examOpen ? '' : 'disabled'}>
            <span class="${c.done ? 'done' : ''}">${Api.esc(c.label)}${c.note ? `<br><span class="muted small">${Api.esc(c.note)}</span>` : ''}${c.done ? `<br><span class="muted small">✔ ${Api.esc(c.by)} · ${Api.fmtTime(c.at)}</span>` : ''}</span></label>`).join('');
        const labs = p.labs.map(x => `<tr><td><input type="checkbox" data-lab="${x.code}" ${x.selected ? 'checked' : ''} ${isDoctor() && labsOpen ? '' : 'disabled'}></td><td><b>${Api.esc(x.label)}</b>${x.source !== 'règle' ? ` <span class="tag tag-n8n">${Api.esc(x.source)}</span>` : ''}</td>
            <td class="small">${Api.esc(x.justification || x.motif || '')}</td></tr>`).join('');
        const results = p.results.length ? `<h3>Résultats ${p.record_entry_id ? `<span class="muted small">(versés au dossier médical, document #${p.record_entry_id})</span>` : ''}</h3>
            <table class="data"><thead><tr><th>Examen</th><th>Valeur</th><th>Normes</th></tr></thead><tbody>${p.results.map(r => `<tr><td>${Api.esc(r.label)}</td>
            <td><span class="${r.abnormal ? 'tag tag-danger' : ''}">${r.value != null ? r.value + ' ' + Api.esc(r.unit) : Api.esc(r.text)}</span></td><td class="muted small">${r.ref_low != null ? r.ref_low + ' – ' + r.ref_high + ' ' + Api.esc(r.unit) : '—'}</td></tr>`).join('')}</tbody></table>${aiBlock(p.ai.resultats, 'Interprétation')}` : '';
        return `<div class="fever-panel">
            <h3>🌡️ Parcours fièvre <span class="tag tag-high">fièvre vraie</span> <span class="muted small">${Api.esc(p.stage_label)}</span></h3>
            <div class="muted small">Critère déterministe : ${Api.esc(p.criterion)} · qSOFA ${p.qsofa}/3${p.news2 != null ? ' · NEWS2 ' + p.news2 : ''}. La température cutanée seule ne déclare jamais une fièvre.</div>
            ${stepper(p)}
            ${aiBlock(p.ai.bilan, 'Synthèse')}
            <h3>1. Bilan clinique — médecin de garde demandé <span class="muted small">(${done}/${p.checklist.length})</span></h3>
            <div class="checklist">${checklist}</div>
            ${examOpen && isDoctor() ? '<button class="btn btn-accent btn-sm" id="fever-exam-done">✔ Bilan clinique terminé</button>' : ''}
            ${p.exam_done_by ? `<div class="muted small">Bilan clinique conclu par ${Api.esc(p.exam_done_by)} · ${Api.fmtTime(p.exam_done_at)}</div>` : ''}
            <h3>2. Bilan biologique proposé à partir du dossier</h3>
            <table class="data"><thead><tr><th></th><th>Examen</th><th>Justification</th></tr></thead><tbody>${labs}</tbody></table>
            ${labsOpen && isDoctor() ? '<button class="btn btn-success btn-sm" id="fever-labs-validate">🧪 Valider le bilan biologique</button>' : ''}
            ${examOpen ? '<div class="muted small">Le bilan biologique se valide après le bilan clinique.</div>' : ''}
            ${labsOpen && !isDoctor() ? '<div class="muted small">En attente de la validation du médecin.</div>' : ''}
            ${p.labs_validated_by ? `<div class="muted small">Validé par ${Api.esc(p.labs_validated_by)} · ${Api.fmtTime(p.labs_validated_at)}${p.stage === 'lab_ordered' ? ' — résultats en attente…' : ''}</div>` : ''}
            <h3>3. Confort de la chambre <span class="muted small">(après le bilan — ce n'est pas un traitement)</span></h3>
            <div class="small">${p.comfort_note ? Api.esc(p.comfort_note) : '<span class="muted">L\'EnvironmentAgent attend la validation du bilan biologique.</span>'}</div>
            ${results}
            <h3>4. Traitement et fin du risque</h3>
            <div class="muted small">Antipyrétique selon l'ordonnance de traitement, puis revérification de la température centrale après le passage du soignant (« Je prends en charge »).</div>
        </div>`;
    }

    function paint() {
        if (!host) return;
        if (!pathway) { host.innerHTML = '<div class="muted small">Parcours fièvre en cours d\'ouverture…</div>'; return; }
        host.innerHTML = html(pathway);
        host.querySelectorAll('[data-check]').forEach(cb => cb.addEventListener('change', async () => {
            try { pathway = await Api.post(`/api/fever/${pathway.id}/checklist`, { key: cb.dataset.check, done: cb.checked }); paint(); } catch (e) { Api.toast(e.message, 'critical'); }
        }));
        host.querySelector('#fever-exam-done')?.addEventListener('click', async () => {
            try { pathway = await Api.post(`/api/fever/${pathway.id}/exam-done`); paint(); Api.toast('Bilan clinique terminé : le bilan biologique peut être validé.', 'success'); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        host.querySelector('#fever-labs-validate')?.addEventListener('click', async () => {
            const codes = [...host.querySelectorAll('[data-lab]')].filter(x => x.checked).map(x => x.dataset.lab);
            try { pathway = await Api.post(`/api/fever/${pathway.id}/labs/validate`, { codes }); paint(); Api.toast('Bilan biologique validé. Réglage de confort de la chambre lancé.', 'success'); } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }

    async function mount(el, id) {
        host = el; riskId = id;
        if (!pathway || pathway.risk_id !== id) pathway = null;
        paint();
        try { const rows = await Api.get(`/api/fever?risk_id=${id}`); if (riskId === id) { pathway = rows[0] || null; paint(); } } catch (_) { }
    }
    function unmount() { host = null; riskId = null; }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'fever' && m.pathway && host && m.pathway.risk_id === riskId) {
            // ne pas écraser les cases que le médecin est en train de cocher
            const editing = pathway && pathway.stage === 'lab_proposed' && m.pathway.stage === 'lab_proposed' && host.contains(document.activeElement);
            if (!editing) { pathway = m.pathway; paint(); }
        }
    });
    return { mount, unmount };
})();
window.FeverPanel = FeverPanel;
