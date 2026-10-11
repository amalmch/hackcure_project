/**
 * Vue « Pharmacie » : médicaments (CRUD pharmacien / médecins), alertes stock & péremption, traitements en cours.
 */
(function () {
    'use strict';
    let mounted = false, host = null, meds = [], treatments = [], editing = null;

    function medRow(m) {
        const flags = [m.expired ? '<span class="tag tag-danger">périmé</span>' : (m.expiring ? '<span class="tag tag-warn">péremption &lt; 60 j</span>' : ''), m.low_stock ? '<span class="tag tag-danger">stock bas</span>' : ''].join(' ');
        return `<tr data-id="${m.id}"><td>${Api.esc(m.dci)}</td><td class="muted">${Api.esc(m.brand)}</td><td>${Api.esc(m.form)} ${Api.esc(m.dosage)}</td><td><b>${m.stock}</b> <span class="muted small">/ seuil ${m.threshold}</span></td><td>${Api.fmtDate(m.expiry)}</td><td class="small muted">${Api.esc(m.allergen_tags)}</td><td>${flags}</td>
            <td>${Auth.can('edit_pharmacy') ? `<button class="btn btn-sm" data-edit="${m.id}">✏️</button> <button class="btn btn-sm btn-danger" data-del="${m.id}">🗑</button>` : ''}</td></tr>`;
    }

    function formHtml(m) {
        const v = (k, d = '') => Api.esc((m && m[k]) ?? d);
        return `<div class="card"><h3>${m ? 'Modifier' : 'Nouveau médicament'}</h3><div class="form-grid">
            <label>DCI<input name="dci" value="${v('dci')}"></label><label>Marque<input name="brand" value="${v('brand')}"></label>
            <label>Forme<input name="form" value="${v('form', 'comprimé')}"></label><label>Dosage<input name="dosage" value="${v('dosage')}"></label>
            <label>Stock<input type="number" name="stock" value="${v('stock', 0)}"></label><label>Seuil<input type="number" name="threshold" value="${v('threshold', 5)}"></label>
            <label>Péremption<input type="date" name="expiry" value="${v('expiry')}"></label><label>Tags allergènes<input name="allergen_tags" value="${v('allergen_tags')}" placeholder="pénicilline, AINS…"></label>
        </div><div class="inline-form" style="margin-top:8px"><button class="btn btn-success" id="med-save">Enregistrer</button><button class="btn" id="med-cancel">Annuler</button></div></div>`;
    }

    async function render(el) {
        host = el;
        try { meds = await Api.get('/api/pharmacy/medications'); treatments = await Api.get('/api/pharmacy/treatments'); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        const low = meds.filter(m => m.low_stock), exp = meds.filter(m => m.expiring);
        const q = (el.querySelector('#med-q') || {}).value || '';
        const list = meds.filter(m => !q || `${m.dci} ${m.brand} ${m.form}`.toLowerCase().includes(q.toLowerCase()));
        el.innerHTML = `<div class="grid-2">
            <div class="card"><h3>⚠️ Stock bas (${low.length})</h3>${low.map(m => `<div class="detail-row"><span>${Api.esc(m.dci)} (${Api.esc(m.brand)})</span><span class="tag tag-danger">${m.stock} / ${m.threshold}</span></div>`).join('') || '<span class="muted">aucun</span>'}</div>
            <div class="card"><h3>⏳ Péremption &lt; 60 jours (${exp.length})</h3>${exp.map(m => `<div class="detail-row"><span>${Api.esc(m.dci)} (${Api.esc(m.brand)})</span><span class="tag tag-warn">${Api.fmtDate(m.expiry)}</span></div>`).join('') || '<span class="muted">aucun</span>'}</div></div>
            <div class="view-toolbar"><input id="med-q" placeholder="Rechercher un médicament…" value="${Api.esc(q)}"><span class="spacer"></span><button class="btn" id="med-n8n" title="Workflow n8n pharmacy-alerts → Telegram du pharmacien">📣 Envoyer les alertes (n8n)</button>${Auth.can('edit_pharmacy') ? '<button class="btn btn-accent" id="med-new">＋ Médicament</button>' : ''}</div>
            <div id="med-form"></div>
            <div class="card"><h3>Inventaire (${meds.length})</h3><table class="data"><thead><tr><th>DCI</th><th>Marque</th><th>Forme</th><th>Stock</th><th>Péremption</th><th>Allergènes</th><th>Alertes</th><th></th></tr></thead><tbody>${list.map(medRow).join('')}</tbody></table></div>
            <div class="card"><h3>Traitements en cours (${treatments.length})</h3><table class="data"><thead><tr><th>Chambre</th><th>Patient</th><th>Médicament</th><th>Posologie</th><th>Voie</th><th>Prescripteur</th><th>Allergie</th><th></th></tr></thead><tbody>
            ${treatments.map(t => `<tr><td><span class="room-pill">${t.room}</span></td><td>${Api.esc(t.patient)}</td><td>${Api.esc(t.medication.dci)} <span class="muted">(${Api.esc(t.medication.brand)})</span></td><td>${Api.esc(t.posology)}</td><td>${t.route}</td><td class="muted small">${Api.esc(t.prescriber)}</td>
                <td>${t.allergy_conflicts.length ? `<span class="tag tag-danger">⚠ ${t.allergy_conflicts.join(', ')}</span>` : ''}</td><td>${Auth.can('edit_pharmacy') ? `<button class="btn btn-sm btn-danger" data-stop="${t.id}">Arrêter</button>` : ''}</td></tr>`).join('')}</tbody></table>
            ${Auth.can('edit_pharmacy') ? `<div class="inline-form" style="margin-top:10px"><select id="tr-adm">${[...new Map(treatments.map(t => [t.admission_id, t])).values()].map(t => `<option value="${t.admission_id}">${t.room} — ${Api.esc(t.patient)}</option>`).join('')}</select>
                <select id="tr-med">${meds.map(m => `<option value="${m.id}">${Api.esc(m.dci)} (${Api.esc(m.brand)})</option>`).join('')}</select><input id="tr-poso" placeholder="posologie" style="width:140px"><select id="tr-route"><option>PO</option><option>IV</option><option>SC</option><option>IM</option><option>INH</option></select><button class="btn btn-sm btn-success" id="tr-add">＋ Traitement</button></div>` : ''}</div>`;
        el.querySelector('#med-q').addEventListener('input', () => render(el));
        el.querySelector('#med-new')?.addEventListener('click', () => openForm(null));
        el.querySelector('#med-n8n')?.addEventListener('click', async () => { try { await Api.post('/api/n8n/trigger/pharmacy-alerts'); Api.toast('Alertes pharmacie envoyées à n8n (Telegram)', 'success'); } catch (e) { Api.toast(e.message, 'warning'); } });
        el.querySelectorAll('[data-edit]').forEach(b => b.addEventListener('click', () => openForm(meds.find(m => m.id === Number(b.dataset.edit)))));
        el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => { if (!confirm('Supprimer ce médicament ?')) return; try { await Api.del(`/api/pharmacy/medications/${b.dataset.del}`); render(el); } catch (e) { Api.toast(e.message, 'critical'); } }));
        el.querySelectorAll('[data-stop]').forEach(b => b.addEventListener('click', async () => { try { await Api.del(`/api/pharmacy/treatments/${b.dataset.stop}`); render(el); } catch (e) { Api.toast(e.message, 'critical'); } }));
        el.querySelector('#tr-add')?.addEventListener('click', async () => {
            try {
                const r = await Api.post('/api/pharmacy/treatments', { admission_id: Number(el.querySelector('#tr-adm').value), medication_id: Number(el.querySelector('#tr-med').value), posology: el.querySelector('#tr-poso').value, route: el.querySelector('#tr-route').value });
                if (r.warning) Api.toast(r.warning, 'critical'); else Api.toast('Traitement ajouté', 'success');
                render(el);
            } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }

    function openForm(m) {
        const f = host.querySelector('#med-form'); f.innerHTML = formHtml(m);
        f.querySelector('#med-cancel').addEventListener('click', () => { f.innerHTML = ''; });
        f.querySelector('#med-save').addEventListener('click', async () => {
            const d = {}; f.querySelectorAll('[name]').forEach(i => { d[i.name] = i.type === 'number' ? Number(i.value) : i.value; });
            if (!d.expiry) delete d.expiry;
            try { if (m) await Api.patch(`/api/pharmacy/medications/${m.id}`, d); else await Api.post('/api/pharmacy/medications', d); Api.toast('Enregistré', 'success'); render(host); } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }

    Views.register('pharmacy', { title: 'Pharmacie', perm: 'view_pharmacy', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; } });
})();
