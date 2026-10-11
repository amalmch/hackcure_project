/**
 * Vues « soins » de la V2 (étape 4) :
 *  - Diagnostics live : hypothèses diagnostiques en temps réel + fil de communication médecin ↔ infirmier ;
 *  - Ordonnance de traitement (hospitalière) : médicament, dose, voie, horaires, durée, condition, alertes ;
 *  - Plan de soins : à faire maintenant / en retard / à venir / administré, comptes rendus d'intervention à signer.
 */
(() => {
    'use strict';
    const PROB = { 'faible': 'tag-low', 'modérée': 'tag-medium', 'élevée': 'tag-high' };
    const ROLE = { nurse: 'Infirmier', duty_doctor: 'Médecin de garde', general_doctor: 'Médecin', owner: 'Propriétaire', psychiatrist: 'Psychiatre', pharmacist: 'Pharmacien', ai: 'IA' };
    let patients = [];
    async function loadPatients() { if (!patients.length) patients = (await Api.get('/api/records')).filter(p => p.room); return patients; }
    const patientSelect = (id, sel) => `<label class="small">Patient <select id="${id}">${patients.map(p => `<option value="${p.patient_id}" ${p.patient_id === sel ? 'selected' : ''}>${Api.esc(p.full_name)} · ch. ${p.room}</option>`).join('')}</select></label>`;

    // ═══ Diagnostics live ═══════════════════════════════════════════════════
    (() => {
        let mounted = false, host = null, selected = null, data = null;
        const canDecide = () => Auth.can('decide_diagnostics'), canPost = () => Auth.can('post_care_message');

        function hypHtml(h) {
            const li = (xs, cls) => xs.length ? `<ul class="fever-list ${cls}">${xs.map(x => `<li>${Api.esc(x)}</li>`).join('')}</ul>` : '<span class="muted small">—</span>';
            const state = h.status === 'confirmed' ? '<span class="tag tag-ok">confirmée</span>' : h.status === 'rejected' ? '<span class="tag">rejetée</span>' : '';
            return `<div class="card diag-card ${h.status}"><h3>${Api.esc(h.label)} <span class="tag ${PROB[h.probability]}">probabilité ${h.probability}</span> ${state}</h3>
                <div class="grid-3"><div><b class="small">Éléments pour</b>${li(h.pros, 'pros')}</div><div><b class="small">Éléments contre</b>${li(h.cons, 'cons')}</div><div><b class="small">Examens utiles</b>${li(h.exams, '')}</div></div>
                ${h.decided_by ? `<div class="muted small">${h.status === 'confirmed' ? 'Confirmée' : h.status === 'rejected' ? 'Rejetée' : 'Rouverte'} par ${Api.esc(h.decided_by)} · ${Api.fmtDateTime(h.decided_at)}${h.note ? ' — ' + Api.esc(h.note) : ''}</div>` : ''}
                ${canDecide() ? `<div class="inline-form" style="margin-top:6px"><input data-note="${h.id}" placeholder="Annotation (facultative)" style="flex:1">
                    <button class="btn btn-sm btn-success" data-decide="${h.id}|confirmed">Confirmer</button><button class="btn btn-sm btn-warn" data-decide="${h.id}|rejected">Rejeter</button>
                    ${h.status !== 'active' ? `<button class="btn btn-sm" data-decide="${h.id}|active">Rouvrir</button>` : ''}</div>` : ''}</div>`;
        }
        function msgHtml(m) {
            const who = m.kind === 'ai' ? '🧠 Synthèse IA' : `${Api.esc(m.author_name || m.author)} <span class="muted small">(${ROLE[m.role] || m.role})</span>`;
            return `<div class="care-msg ${m.kind}"><div class="small"><b>${who}</b> <span class="muted">${Api.fmtDateTime(m.created_at)}</span></div><div class="care-body">${Api.esc(m.body)}</div></div>`;
        }
        function paint() {
            const b = host.querySelector('#diag-body'); if (!b || !data) return;
            const v = data.vitals || {};
            b.innerHTML = `<div id="diag-profile"></div>
                <div class="ai-hint">Scores : NEWS2 ${data.scores.news2 ?? '—'} · qSOFA ${data.scores.qsofa ?? '—'} · FC ${v.hr ?? '—'} · PA ${v.sys ?? '—'}/${v.dia ?? '—'} · SpO2 ${v.spo2 ?? '—'} % · T° ${v.tempC ?? '—'} °C. ${Api.esc(data.disclaimer)}</div>
                <div class="grid-2" style="grid-template-columns:1.5fr 1fr;align-items:start"><div><h3>Hypothèses diagnostiques (mise à jour en temps réel)</h3>
                    ${data.hypotheses.map(hypHtml).join('') || '<div class="card empty">Aucune hypothèse au-dessus du seuil : constantes et bilan rassurants.</div>'}</div>
                <div class="card"><h3>Fil médecin ↔ infirmier</h3><div id="diag-thread" class="care-thread">${data.messages.map(msgHtml).join('') || '<div class="muted small">Aucun message.</div>'}</div>
                    ${canPost() ? '<div class="inline-form" style="margin-top:8px"><input id="diag-msg" placeholder="Message… (@medecin_garde, @infirmier, @psychiatre)" style="flex:1"><button class="btn btn-accent btn-sm" id="diag-send">Envoyer</button></div>' : ''}</div></div>`;
            ClinicalProfile.mount(b.querySelector('#diag-profile'), selected);
            const th = b.querySelector('#diag-thread'); th.scrollTop = th.scrollHeight;
            b.querySelectorAll('[data-decide]').forEach(btn => btn.addEventListener('click', async () => {
                const [id, status] = btn.dataset.decide.split('|');
                try { await Api.post(`/api/diagnostics/hypotheses/${id}/decision`, { status, note: b.querySelector(`[data-note="${id}"]`).value }); await load(); } catch (e) { Api.toast(e.message, 'critical'); }
            }));
            const send = async () => { const i = b.querySelector('#diag-msg'); if (!i.value.trim()) return; try { await Api.post(`/api/diagnostics/${selected}/messages`, { body: i.value }); i.value = ''; } catch (e) { Api.toast(e.message, 'critical'); } };
            b.querySelector('#diag-send')?.addEventListener('click', send);
            b.querySelector('#diag-msg')?.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
        }
        async function load() { try { data = await Api.get(`/api/diagnostics/${selected}`); paint(); } catch (e) { host.querySelector('#diag-body').innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; } }
        async function render(el) {
            host = el;
            try { await loadPatients(); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
            if (!selected && patients.length) selected = patients[0].patient_id;
            el.innerHTML = `<div class="view-toolbar">${patientSelect('diag-patient', selected)}<span class="muted small">Hypothèses calculées par des règles transparentes à partir des constantes, de la vision, de la biologie, des scores et du dossier.</span></div><div id="diag-body"></div>`;
            el.querySelector('#diag-patient').addEventListener('change', e => { selected = e.target.value; load(); });
            await load();
        }
        window.addEventListener('hackcure:ws', (e) => {
            const m = e.detail; if (!mounted || !host || !data) return;
            if (m.type === 'diagnostics' && m.patient_id === selected) { if (m.hypotheses) { data.hypotheses = m.hypotheses; paint(); } else load(); }
            else if (m.type === 'care_message' && m.patient_id === selected) { data.messages.push(m.message); const editing = document.activeElement && document.activeElement.id === 'diag-msg';
                if (editing) { const th = host.querySelector('#diag-thread'); th.insertAdjacentHTML('beforeend', msgHtml(m.message)); th.scrollTop = th.scrollHeight; } else paint(); }
        });
        Views.register('diagnostics', { title: 'Diagnostics live', perm: 'view_diagnostics', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    })();

    // ═══ Ordonnance de traitement ═══════════════════════════════════════════
    (() => {
        let mounted = false, host = null, selected = null, meds = [], orders = [], draft = [];
        const canWrite = () => Auth.can('write_treatment_orders');
        const METRICS = { tempC: 'température (°C)', pain: 'douleur EVA (/10)', sys: 'PAS (mmHg)', spo2: 'SpO2 (%)', glucose: 'glycémie (g/L)' };

        function orderHtml(o) {
            const st = { draft: ['brouillon', 'tag-medium'], active: ['active', 'tag-ok'], stopped: ['arrêtée', ''] }[o.status];
            return `<div class="card"><h3>Ordonnance de traitement #${o.id} <span class="tag ${st[1]}">${st[0]}</span> <span class="muted small">${Api.esc(o.prescriber_name || o.prescriber)} · ${Api.fmtDateTime(o.signed_at || o.created_at)}${o.indication ? ' · ' + Api.esc(o.indication) : ''}</span></h3>
                <table class="data"><thead><tr><th>Médicament</th><th>Dose</th><th>Voie</th><th>Horaires / condition</th><th>Durée</th><th>Alertes</th></tr></thead><tbody>${o.lines.map(l => `<tr><td>${Api.esc(l.dci)} <span class="muted small">(${Api.esc(l.brand)})</span></td><td>${Api.esc(l.dose)}</td><td>${l.route}</td>
                    <td>${l.prn ? `<span class="tag tag-warn">${Api.esc(l.condition)}</span> <span class="muted small">min. ${l.min_interval_h} h entre deux prises</span>` : l.times.join(' · ')}</td><td>${l.duration_days} j</td>
                    <td>${l.allergy_alert ? `<span class="tag tag-danger">${Api.esc(l.allergy_alert)}</span>` : ''} ${l.interaction_alert ? `<span class="tag tag-warn" title="${Api.esc(l.interaction_alert)}">interaction</span><div class="muted small">${Api.esc(l.interaction_alert)}</div>` : ''}</td></tr>`).join('')}</tbody></table>
                <div class="muted small">Plan d'administration : ${o.doses.total} prise(s), ${o.doses.given} administrée(s), ${o.doses.scheduled} à venir.</div>
                ${canWrite() && o.status === 'draft' ? `<div class="inline-form" style="margin-top:8px"><button class="btn btn-success btn-sm" data-sign="${o.id}">✍️ Signer et générer le plan d'administration</button><button class="btn btn-sm" data-sign-demo="${o.id}" title="Démo : première prise dans 30 secondes">▶ Signer (1ʳᵉ prise dans 30 s)</button></div>` : ''}
                ${canWrite() && o.status === 'active' ? `<div class="inline-form" style="margin-top:8px"><button class="btn btn-warn btn-sm" data-stop="${o.id}">Arrêter l'ordonnance</button></div>` : ''}</div>`;
        }
        function formHtml() {
            const rows = draft.map((l, i) => `<tr><td>${Api.esc(l.label)}</td><td>${Api.esc(l.dose)}</td><td>${l.route}</td><td>${l.prn ? `si ${METRICS[l.condition_metric] || ''} ${l.condition_op} ${l.condition_value}` : l.times.join(' · ')}</td><td>${l.duration_days} j</td>
                <td>${l.allergy_alert ? `<span class="tag tag-danger">${Api.esc(l.allergy_alert)}</span>` : ''}${l.interaction_alert ? `<span class="tag tag-warn">${Api.esc(l.interaction_alert)}</span>` : ''}</td><td><button class="btn btn-sm" data-rm="${i}">✕</button></td></tr>`).join('');
            return `<div class="card"><h3>Nouvelle ordonnance de traitement <span class="muted small">(hospitalière — distincte de l'ordonnance de sortie)</span></h3>
                <label class="small">Indication<input id="to-indication" style="width:100%" placeholder="ex. pneumopathie, antalgie post-opératoire"></label>
                <div class="inline-form" style="margin-top:8px;flex-wrap:wrap">
                    <select id="to-med">${meds.map(m => `<option value="${m.id}">${Api.esc(m.dci)} (${Api.esc(m.brand)}) — stock ${m.stock}</option>`).join('')}</select>
                    <input id="to-dose" placeholder="dose (ex. 1 g)" style="width:110px"><select id="to-route"><option>PO</option><option>IV</option><option>SC</option><option>IM</option><option>INH</option></select>
                    <input id="to-times" placeholder="horaires : 08:00, 14:00, 20:00" style="width:210px"><input id="to-days" type="number" min="1" max="30" value="3" style="width:64px" title="durée (jours)">
                    <label class="small"><input type="checkbox" id="to-prn"> si</label><select id="to-metric">${Object.keys(METRICS).map(k => `<option value="${k}">${METRICS[k]}</option>`).join('')}</select>
                    <select id="to-op"><option>&gt;</option><option>&gt;=</option><option>&lt;</option></select><input id="to-value" type="number" step="0.1" placeholder="38.5" style="width:74px">
                    <button class="btn btn-sm btn-accent" id="to-add">＋ Ajouter la ligne</button></div>
                ${draft.length ? `<table class="data" style="margin-top:8px"><thead><tr><th>Médicament</th><th>Dose</th><th>Voie</th><th>Horaires / condition</th><th>Durée</th><th>Alertes</th><th></th></tr></thead><tbody>${rows}</tbody></table>
                    <div class="inline-form" style="margin-top:8px"><button class="btn btn-success btn-sm" id="to-save">Enregistrer le brouillon</button></div>` : '<div class="muted small" style="margin-top:6px">Ajoutez au moins une ligne. Les allergies et les interactions sont vérifiées à chaque ajout.</div>'}</div>`;
        }
        function paint() {
            const b = host.querySelector('#to-body'); if (!b) return;
            const indication = b.querySelector('#to-indication')?.value || '';
            b.innerHTML = `<div id="to-profile"></div>${canWrite() ? formHtml() : '<div class="ai-hint">Lecture seule pour votre rôle : seuls les médecins prescrivent.</div>'}${orders.map(orderHtml).join('') || '<div class="card empty">Aucune ordonnance de traitement pour ce séjour</div>'}`;
            ClinicalProfile.mount(b.querySelector('#to-profile'), selected);
            if (b.querySelector('#to-indication')) b.querySelector('#to-indication').value = indication;
            b.querySelector('#to-add')?.addEventListener('click', async () => {
                const m = meds.find(x => x.id === Number(b.querySelector('#to-med').value)), prn = b.querySelector('#to-prn').checked;
                const line = { medication_id: m.id, label: `${m.dci} (${m.brand})`, dose: b.querySelector('#to-dose').value || m.dosage, route: b.querySelector('#to-route').value, times: prn ? [] : b.querySelector('#to-times').value.split(',').map(x => x.trim()).filter(Boolean),
                    duration_days: Number(b.querySelector('#to-days').value) || 3, prn, condition_metric: prn ? b.querySelector('#to-metric').value : '', condition_op: b.querySelector('#to-op').value, condition_value: prn ? Number(b.querySelector('#to-value').value) : null };
                if (!prn && !line.times.length) { Api.toast('Horaires requis (HH:MM), ou cocher « si » pour une prise conditionnelle', 'warning'); return; }
                if (prn && !b.querySelector('#to-value').value) { Api.toast('Valeur de la condition requise', 'warning'); return; }
                try { const chk = await Api.post('/api/treatment-orders/check', { patient_id: selected, lines: [...draft, line].map(l => ({ medication_id: l.medication_id })) });
                    const c = chk[chk.length - 1]; line.allergy_alert = c.allergy_alert; line.interaction_alert = c.interaction_alert;
                    if (c.allergy_alert) Api.toast(`⚠ ${c.allergy_alert}`, 'critical'); else if (c.interaction_alert) Api.toast(`⚠ ${c.interaction_alert}`, 'warning');
                } catch (e) { Api.toast(e.message, 'critical'); return; }
                draft.push(line); paint();
            });
            b.querySelectorAll('[data-rm]').forEach(x => x.addEventListener('click', () => { draft.splice(Number(x.dataset.rm), 1); paint(); }));
            b.querySelector('#to-save')?.addEventListener('click', async () => {
                try { await Api.post('/api/treatment-orders', { patient_id: selected, indication: b.querySelector('#to-indication').value, lines: draft }); draft = []; Api.toast('Ordonnance enregistrée (brouillon)', 'success'); await load(); } catch (e) { Api.toast(e.message, 'critical'); }
            });
            const sign = async (id, body) => { try { await Api.post(`/api/treatment-orders/${id}/sign`, body); Api.toast('Ordonnance signée : plan d\'administration généré', 'success'); await load(); }
                catch (e) { if (e.status === 409 && confirm(e.message + '\n\nSigner quand même ? (décision tracée)')) { try { await Api.post(`/api/treatment-orders/${id}/sign`, { ...body, force: true }); await load(); } catch (e2) { Api.toast(e2.message, 'critical'); } } else Api.toast(e.message, 'critical'); } };
            b.querySelectorAll('[data-sign]').forEach(x => x.addEventListener('click', () => sign(x.dataset.sign, {})));
            b.querySelectorAll('[data-sign-demo]').forEach(x => x.addEventListener('click', () => sign(x.dataset.signDemo, { first_dose_in_s: 30 })));
            b.querySelectorAll('[data-stop]').forEach(x => x.addEventListener('click', async () => { try { await Api.post(`/api/treatment-orders/${x.dataset.stop}/stop`); await load(); } catch (e) { Api.toast(e.message, 'critical'); } }));
        }
        async function load() { try { orders = await Api.get(`/api/treatment-orders?patient_id=${selected}`); paint(); } catch (e) { Api.toast(e.message, 'critical'); } }
        async function render(el) {
            host = el;
            try { await loadPatients(); meds = await Api.get('/api/pharmacy/medications'); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
            if (!selected && patients.length) selected = patients[0].patient_id;
            el.innerHTML = `<div class="view-toolbar">${patientSelect('to-patient', selected)}<span class="muted small">Chaque ordonnance signée devient un plan d'administration horodaté (vue « Plan de soins »).</span></div><div id="to-body"></div>`;
            el.querySelector('#to-patient').addEventListener('change', e => { selected = e.target.value; draft = []; load(); });
            await load();
        }
        window.addEventListener('hackcure:ws', (e) => { if (mounted && host && e.detail.type === 'care_plan' && !draft.length) load(); });
        Views.register('treatment', { title: 'Ordonnance de traitement', perm: 'view_treatment_orders', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
    })();

    // ═══ Plan de soins ══════════════════════════════════════════════════════
    (() => {
        let mounted = false, host = null, plan = null, reports = [], timer = null;
        const canGive = () => Auth.can('administer_medication');
        const time = (iso) => new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });

        function doseHtml(d) {
            const actions = canGive() && d.status === 'scheduled' ? `<span class="inline-form"><input data-note="${d.id}" placeholder="remarque" style="width:120px"><button class="btn btn-sm btn-success" data-give="${d.id}">✔ Administré</button><button class="btn btn-sm btn-warn" data-skip="${d.id}">Non administré</button></span>` : '';
            const done = d.status === 'given' ? `<span class="muted small">✔ ${Api.esc(d.given_by)} · ${time(d.given_at)}${d.note ? ' — ' + Api.esc(d.note) : ''}</span>` : d.status === 'not_given' ? `<span class="muted small">✕ ${Api.esc(d.given_by || '')} — ${Api.esc(d.reason)}</span>` : '';
            return `<div class="dose-row dose-${d.state}"><span class="dose-time">${time(d.due_at)}</span><span class="room-pill">${d.room}</span>
                <span class="dose-main"><b>${Api.esc(d.label)}</b> <span class="muted small">${Api.esc(d.patient_name)}</span>${d.conditional ? ` <span class="tag tag-warn">${Api.esc(d.condition || 'si besoin')}</span>` : ''}
                ${d.allergy_alert ? ` <span class="tag tag-danger">${Api.esc(d.allergy_alert)}</span>` : ''}${d.state === 'late' ? ` <span class="tag tag-danger">retard ${d.minutes_late} min${d.escalated_at ? ' · médecin prévenu' : d.relaunched_at ? ' · relancé' : ''}</span>` : ''}</span>${actions}${done}</div>`;
        }
        const group = (title, rows, empty) => `<div class="card"><h3>${title} <span class="muted small">(${rows.length})</span></h3>${rows.map(doseHtml).join('') || `<div class="muted small">${empty}</div>`}</div>`;
        function paint() {
            const b = host.querySelector('#cp-body'); if (!b || !plan) return;
            if (b.contains(document.activeElement) && document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;   // ne pas effacer une saisie en cours
            const drafts = reports.filter(r => r.status === 'draft');
            b.innerHTML = `${group('⏰ En retard', plan.late, 'Aucune prise en retard.')}${group('💊 À faire maintenant', plan.due, 'Rien à administrer pour l\'instant.')}
                <div class="grid-2">${group('🕒 À venir (24 h)', plan.upcoming, 'Aucune prise planifiée.')}${group('✔ Administré / non administré', [...plan.given, ...plan.not_given].reverse(), 'Aucune administration enregistrée.')}</div>
                <div class="card"><h3>📋 Comptes rendus d'intervention à valider <span class="muted small">(${drafts.length})</span></h3>${drafts.map(r => `<div class="report-draft"><b>${Api.esc(r.title)}</b> <span class="muted small">${Api.esc(r.patient_name)} · ch. ${r.room || '—'} · ${Api.fmtDateTime(r.date)}</span>
                    <textarea data-report="${r.id}" rows="7" style="width:100%;margin-top:4px">${Api.esc(r.content)}</textarea>
                    ${canGive() ? `<div class="inline-form"><button class="btn btn-sm btn-success" data-sign-report="${r.id}" ${r.content ? '' : 'disabled'}>✍️ Valider et signer</button><span class="muted small">Brouillon rédigé par l'IA à partir du journal — à relire avant signature.</span></div>` : ''}</div>`).join('') || '<div class="muted small">Aucun brouillon en attente.</div>'}</div>`;
            b.querySelectorAll('[data-give]').forEach(x => x.addEventListener('click', async () => { try { const r = await Api.post(`/api/care-plan/doses/${x.dataset.give}/give`, { note: b.querySelector(`[data-note="${x.dataset.give}"]`).value }); Api.toast(`Administration enregistrée (stock restant : ${r.stock_after})`, 'success'); document.activeElement.blur(); load(); } catch (e) { Api.toast(e.message, 'critical'); } }));
            b.querySelectorAll('[data-skip]').forEach(x => x.addEventListener('click', async () => { const reason = prompt('Motif de non-administration :'); if (!reason) return; try { await Api.post(`/api/care-plan/doses/${x.dataset.skip}/skip`, { reason }); load(); } catch (e) { Api.toast(e.message, 'critical'); } }));
            b.querySelectorAll('[data-sign-report]').forEach(x => x.addEventListener('click', async () => { try { await Api.post(`/api/interventions/${x.dataset.signReport}/sign`, { content: b.querySelector(`[data-report="${x.dataset.signReport}"]`).value }); Api.toast('Compte rendu signé et rangé dans le dossier médical', 'success'); document.activeElement.blur(); load(); } catch (e) { Api.toast(e.message, 'critical'); } }));
        }
        async function load() {
            if (!mounted) return;
            try { plan = await Api.get('/api/care-plan'); reports = Auth.can('view_medical_record') ? await Api.get('/api/interventions') : []; paint(); } catch (e) { host.querySelector('#cp-body').innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; }
        }
        Views.register('careplan', { title: 'Plan de soins', perm: 'view_care_plan',
            mount(el) { mounted = true; host = el; el.innerHTML = '<div class="ai-hint">Plan d\'administration généré à partir des ordonnances de traitement. Rappel à l\'heure de la prise ; retard &gt; 30 min ⇒ relance ; &gt; 60 min ⇒ médecin prévenu. Chaque administration décrémente le stock de la pharmacie.</div><div id="cp-body"></div>'; load(); timer = setInterval(load, 20000); },
            unmount() { mounted = false; clearInterval(timer); } });
        window.addEventListener('hackcure:ws', (e) => { if (mounted && (e.detail.type === 'care_plan' || e.detail.type === 'intervention_report')) load(); });
    })();
})();
