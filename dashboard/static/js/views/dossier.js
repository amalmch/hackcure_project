/**
 * Vue « Dossier médical » (V2) : frise chronologique sur des années, filtres (type, service, période),
 * recherche plein texte, défilement par pages (fluide avec des centaines de documents), détail d'un document,
 * courbes des résultats biologiques (Chart.js), synthèse IA en cache et régénérable, impression.
 * Le serveur restreint le contenu selon le rôle (`scope` : full | identity | pharmacy).
 */
const DossierView = (() => {
    'use strict';
    const PAGE = 40;
    const ICON = { consultation: '🩺', hospitalisation: '🏥', operation: '🔪', biologie: '🧪', imagerie: '🩻', vaccination: '💉', allergie: '⚠️', chronique: '♾️', familial: '👪', traitement: '💊', ordonnance: '℞', psychologie: '🧠', intervention: '📋' };
    let mounted = false, host = null, patients = [], types = {}, scope = 'full';
    let selected = null, filters = { types: new Set(), service: '', q: '', from: '', to: '' };
    let items = [], total = 0, loading = false, facets = { types: {}, services: {} }, bounds = {}, current = null, chart = null, observer = null, searchTimer = null;

    const full = () => scope === 'full';
    const canWrite = () => Auth.can('write_medical_record');

    async function render(el) {
        host = el;
        try { const d = await Api.get('/api/dossier/patients'); patients = d.patients; types = d.types; scope = d.scope; }
        catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        if (!selected && patients.length) selected = patients[0].patient_id;
        const note = { identity: 'Votre rôle voit l\'identité et les admissions uniquement.', pharmacy: 'Votre rôle voit les allergies et les traitements uniquement.' }[scope] || '';
        el.innerHTML = `<div class="view-toolbar">
                <label class="small">Patient <select id="dos-patient">${patients.map(p => `<option value="${p.patient_id}" ${p.patient_id === selected ? 'selected' : ''}>${Api.esc(p.name)} · ${p.code}${p.room ? ' · ch. ' + p.room : ''}${p.documents != null ? ' · ' + p.documents + ' docs' : ''}</option>`).join('')}</select></label>
                <input id="dos-q" placeholder="Rechercher dans le dossier…" style="flex:1;min-width:160px" ${scope === 'identity' ? 'disabled' : ''}>
                <label class="small">du <input type="date" id="dos-from"></label><label class="small">au <input type="date" id="dos-to"></label>
                <select id="dos-service"><option value="">Tous les services</option></select>
                ${canWrite() ? '<button class="btn btn-accent btn-sm" id="dos-new">＋ Document</button>' : ''}
            </div>
            ${note ? `<div class="ai-hint">🔒 ${note} Chaque accès au dossier est tracé.</div>` : ''}
            <div id="dos-profile"></div>
            <div id="dos-chips" class="dos-chips"></div>
            <div class="grid-2" style="grid-template-columns: 1fr 1.25fr; align-items:start">
                <div class="card"><h3>Frise chronologique <span class="muted small" id="dos-count"></span></h3><div id="dos-timeline" class="dos-timeline"></div><div id="dos-sentinel" class="muted small" style="padding:8px;text-align:center"></div></div>
                <div><div class="card" id="dos-detail"><div class="empty">Sélectionnez un document dans la frise</div></div>
                    ${full() ? '<div class="card" id="dos-labs"></div><div class="card" id="dos-summary"></div>' : ''}</div>
            </div>`;
        el.querySelector('#dos-patient').addEventListener('change', e => { selected = e.target.value; current = null; filters = { types: new Set(), service: '', q: '', from: '', to: '' }; render(el); });
        el.querySelector('#dos-q').addEventListener('input', e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { filters.q = e.target.value.trim(); reload(); }, 300); });
        el.querySelector('#dos-from').addEventListener('change', e => { filters.from = e.target.value; reload(); });
        el.querySelector('#dos-to').addEventListener('change', e => { filters.to = e.target.value; reload(); });
        el.querySelector('#dos-service').addEventListener('change', e => { filters.service = e.target.value; reload(); });
        el.querySelector('#dos-new')?.addEventListener('click', openForm);
        if (observer) observer.disconnect();
        observer = new IntersectionObserver((es) => { if (es.some(x => x.isIntersecting)) loadMore(); }, { root: document.getElementById('view-body'), rootMargin: '300px' });
        observer.observe(el.querySelector('#dos-sentinel'));
        loadProfile();
        await reload();
        if (full()) { loadLabs(); loadSummary(); }
    }

    function query(offset) {
        const p = new URLSearchParams({ limit: PAGE, offset });
        if (filters.types.size) p.set('type', [...filters.types].join(','));
        if (filters.service) p.set('service', filters.service);
        if (filters.q) p.set('q', filters.q);
        if (filters.from) p.set('date_from', filters.from);
        if (filters.to) p.set('date_to', filters.to);
        return `/api/dossier/${selected}/entries?${p}`;
    }

    async function reload() { items = []; total = 0; await loadMore(true); }

    async function loadMore(reset) {
        if (loading || (!reset && items.length >= total && total > 0) || !selected) return;
        loading = true;
        try {
            const d = await Api.get(query(items.length));
            total = d.total; facets = d.facets; bounds = { first: d.first_date, last: d.last_date };
            items = items.concat(d.items);
            paintTimeline(reset); paintChips(); paintServices();
        } catch (e) { Api.toast(e.message, 'critical'); }
        loading = false;
    }

    function paintChips() {
        const el = host.querySelector('#dos-chips'); if (!el) return;
        el.innerHTML = Object.keys(facets.types).sort((a, b) => facets.types[b] - facets.types[a]).map(t =>
            `<button class="dos-chip ${filters.types.has(t) ? 'on' : ''}" data-type="${t}">${ICON[t] || '📄'} ${Api.esc(types[t] || t)} <span class="muted">${facets.types[t]}</span></button>`).join('')
            + (filters.types.size || filters.q || filters.service || filters.from || filters.to ? '<button class="dos-chip" data-clear="1">✕ Effacer les filtres</button>' : '');
        el.querySelectorAll('[data-type]').forEach(b => b.addEventListener('click', () => { const t = b.dataset.type; filters.types.has(t) ? filters.types.delete(t) : filters.types.add(t); reload(); }));
        el.querySelector('[data-clear]')?.addEventListener('click', () => { filters = { types: new Set(), service: '', q: '', from: '', to: '' }; host.querySelector('#dos-q').value = ''; host.querySelector('#dos-from').value = ''; host.querySelector('#dos-to').value = ''; reload(); });
    }

    function paintServices() {
        const sel = host.querySelector('#dos-service'); if (!sel || sel.options.length > 1) return;
        Object.keys(facets.services || {}).sort().forEach(s => sel.insertAdjacentHTML('beforeend', `<option value="${Api.esc(s)}">${Api.esc(s)} (${facets.services[s]})</option>`));
    }

    function paintTimeline(reset) {
        const el = host.querySelector('#dos-timeline'); if (!el) return;
        let html = '', year = null;
        items.forEach(i => {
            const y = i.date.slice(0, 4);
            if (y !== year) { year = y; html += `<div class="dos-year">${y}</div>`; }
            html += `<div class="dos-item ${current && current.id === i.id ? 'selected' : ''}" data-id="${i.id}"><span class="dos-dot dos-${i.type}">${ICON[i.type] || '📄'}</span>
                <div class="dos-body"><div class="dos-title">${Api.esc(i.title)}</div>
                <div class="muted small">${Api.fmtDate(i.date)} · ${Api.esc(i.type_label)}${i.service ? ' · ' + Api.esc(i.service) : ''}${i.author ? ' · ' + Api.esc(i.author) : ''}${i.source === 'plateforme' ? ' · <span class="tag tag-n8n">séjour en cours</span>' : ''}</div>
                ${i.summary ? `<div class="small dos-sum">${Api.esc(i.summary)}</div>` : ''}</div></div>`;
        });
        el.innerHTML = html || '<div class="empty">Aucun document ne correspond aux filtres</div>';
        if (reset) el.scrollTop = 0;
        el.querySelectorAll('.dos-item').forEach(n => n.addEventListener('click', () => open(Number(n.dataset.id))));
        host.querySelector('#dos-count').textContent = `${items.length} / ${total} document(s)${bounds.first ? ' · du ' + Api.fmtDate(bounds.first) + ' au ' + Api.fmtDate(bounds.last) : ''}`;
        host.querySelector('#dos-sentinel').textContent = items.length < total ? 'Chargement de la suite…' : (total ? '— début du dossier —' : '');
    }

    async function open(id) {
        const el = host.querySelector('#dos-detail');
        try { current = await Api.get(`/api/dossier/entries/${id}`); } catch (e) { Api.toast(e.message, 'warning'); return; }
        host.querySelectorAll('.dos-item').forEach(n => n.classList.toggle('selected', Number(n.dataset.id) === id));
        const labs = current.labs ? `<table class="data"><thead><tr><th>Examen</th><th>Valeur</th><th>Normes</th></tr></thead><tbody>${current.labs.map(r => `<tr><td>${r.value != null ? `<a href="#" data-code="${r.code}">${Api.esc(r.label)}</a>` : Api.esc(r.label)}</td>
            <td><span class="${r.abnormal ? 'tag tag-danger' : ''}">${r.value != null ? r.value + ' ' + Api.esc(r.unit) : Api.esc(r.text)}</span></td><td class="muted small">${r.ref_low != null ? r.ref_low + ' – ' + r.ref_high + ' ' + Api.esc(r.unit) : '—'}</td></tr>`).join('')}</tbody></table>` : '';
        el.innerHTML = `<h3>${ICON[current.type] || '📄'} ${Api.esc(current.title)}</h3>
            <div class="muted small">${Api.fmtDateTime(current.date)} · ${Api.esc(current.type_label)}${current.service ? ' · ' + Api.esc(current.service) : ''}${current.facility ? ' · ' + Api.esc(current.facility) : ''}${current.author ? ' · ' + Api.esc(current.author) : ''}</div>
            ${labs || (current.content != null ? `<div class="dos-content">${Api.esc(current.content)}</div>` : '<div class="muted small" style="margin-top:8px">Contenu clinique non accessible à votre rôle.</div>')}
            ${full() ? `<div class="inline-form" style="margin-top:10px"><a class="btn btn-sm" href="/print/dossier/entry/${current.id}" target="_blank" rel="noopener">🖨️ Imprimer</a></div>` : ''}`;
        el.querySelectorAll('[data-code]').forEach(a => a.addEventListener('click', (ev) => { ev.preventDefault(); showSeries(a.dataset.code); }));
    }

    async function loadProfile() {
        const el = host.querySelector('#dos-profile'); if (!el) return;
        try { const p = await Api.get(`/api/dossier/${selected}/profile`); el.innerHTML = window.ClinicalProfile ? ClinicalProfile.html(p) : ''; } catch (_) { el.innerHTML = ''; }
    }

    async function loadLabs() {
        const el = host.querySelector('#dos-labs'); if (!el) return;
        let codes = [];
        try { codes = await Api.get(`/api/dossier/${selected}/labs`); } catch (_) { el.innerHTML = ''; return; }
        el.innerHTML = `<h3>Résultats biologiques dans le temps</h3><div class="inline-form"><select id="dos-lab-code">${codes.map(c => `<option value="${c.code}">${Api.esc(c.label)} (${c.count})</option>`).join('')}</select>
            <span class="muted small" id="dos-lab-last"></span></div><div style="height:200px"><canvas id="dos-lab-chart"></canvas></div>`;
        el.querySelector('#dos-lab-code').addEventListener('change', e => showSeries(e.target.value));
        if (codes.length) showSeries(codes[0].code);
    }

    async function showSeries(code) {
        const canvas = host.querySelector('#dos-lab-chart'); if (!canvas || typeof Chart === 'undefined') return;
        let s; try { s = await Api.get(`/api/dossier/${selected}/labs?code=${code}`); } catch (e) { Api.toast(e.message, 'warning'); return; }
        const sel = host.querySelector('#dos-lab-code'); if (sel) sel.value = code;
        const last = s.points[s.points.length - 1];
        host.querySelector('#dos-lab-last').textContent = last ? `Dernière valeur : ${last.value} ${s.unit} le ${Api.fmtDate(last.date)} · normes ${s.ref_low ?? '—'} – ${s.ref_high ?? '—'}` : '';
        const band = (v) => s.points.map(() => v);
        if (chart) chart.destroy();
        chart = new Chart(canvas, { type: 'line', data: { labels: s.points.map(p => p.date.slice(0, 10)), datasets: [
            { label: `${s.label} (${s.unit})`, data: s.points.map(p => p.value), borderColor: '#38bdf8', backgroundColor: 'rgba(56,189,248,.15)', tension: .25, pointRadius: 3, pointBackgroundColor: s.points.map(p => p.abnormal ? '#ef4444' : '#38bdf8') },
            ...(s.ref_high != null ? [{ label: 'Norme haute', data: band(s.ref_high), borderColor: 'rgba(148,163,184,.5)', borderDash: [4, 4], pointRadius: 0 }] : []),
            ...(s.ref_low != null && s.ref_low > 0 ? [{ label: 'Norme basse', data: band(s.ref_low), borderColor: 'rgba(148,163,184,.5)', borderDash: [4, 4], pointRadius: 0 }] : []),
        ] }, options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { labels: { color: '#94a3b8', boxWidth: 12 } } }, scales: { x: { ticks: { color: '#64748b', maxTicksLimit: 8 } }, y: { ticks: { color: '#64748b' } } } } });
    }

    function summaryHtml(s) {
        const list = (title, xs) => xs && xs.length ? `<div class="small"><b>${title}</b><ul class="fever-list">${xs.map(x => `<li>${Api.esc(x)}</li>`).join('')}</ul></div>` : '';
        const actions = `<div class="inline-form" style="margin-top:8px"><button class="btn btn-sm" id="dos-sum-gen">🤖 ${s.status === 'ready' ? 'Régénérer' : 'Générer la synthèse'}</button>${s.status === 'ready' ? `<a class="btn btn-sm" href="/print/dossier/summary/${selected}" target="_blank" rel="noopener">🖨️ Imprimer</a>` : ''}</div>`;
        if (s.status !== 'ready') return `<h3>Synthèse IA du dossier</h3><div class="muted small">${s.status === 'pending' ? 'Rédaction en cours…' : 'Aucune synthèse en cache.'}</div>${actions}`;
        return `<h3>Synthèse IA du dossier ${s.fallback ? '<span class="tag tag-fallback">réponse de secours (LLM indisponible)</span>' : ''}</h3>
            <div class="ai-hint">🧠 ${Api.esc(s.summary)}<br><span class="muted small">${Api.esc(s.provider || '')} · en cache depuis ${Api.fmtDateTime(s.generated_at)} — ${Api.esc(s.disclaimer)}</span></div>
            <div class="grid-2">${list('Allergies', s.allergies)}${list('Maladies chroniques', s.chronic)}${list('Antécédents', s.history)}${list('Traitements actifs', s.active_treatments)}</div>
            ${list('Points d\'attention', s.attention)}${actions}`;
    }

    async function loadSummary(s) {
        const el = host.querySelector('#dos-summary'); if (!el) return;
        if (!s) { try { s = await Api.get(`/api/dossier/${selected}/summary`); } catch (_) { return; } }
        el.innerHTML = summaryHtml(s);
        el.querySelector('#dos-sum-gen')?.addEventListener('click', async () => {
            try { await Api.post(`/api/dossier/${selected}/summary`); el.innerHTML = summaryHtml({ status: 'pending' }); } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }

    function openForm() {
        const el = host.querySelector('#dos-detail');
        const opts = Object.keys(types).filter(t => t !== 'synthese').map(t => `<option value="${t}">${Api.esc(types[t])}</option>`).join('');
        el.innerHTML = `<h3>Nouveau document</h3><div class="form-grid"><label>Type <select id="dn-type">${opts}</select></label><label>Service <input id="dn-service" placeholder="ex. Cardiologie"></label></div>
            <label class="small">Titre<input id="dn-title" style="width:100%"></label><label class="small">Contenu<textarea id="dn-content" rows="8" style="width:100%"></textarea></label>
            <div class="inline-form" style="margin-top:8px"><button class="btn btn-success btn-sm" id="dn-save">Enregistrer au dossier</button></div>`;
        el.querySelector('#dn-save').addEventListener('click', async () => {
            const title = el.querySelector('#dn-title').value.trim(); if (!title) { Api.toast('Titre requis', 'warning'); return; }
            try { const d = await Api.post(`/api/dossier/${selected}/entries`, { type: el.querySelector('#dn-type').value, title, content: el.querySelector('#dn-content').value, service: el.querySelector('#dn-service').value });
                Api.toast('Document ajouté au dossier', 'success'); await reload(); open(d.id); } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (mounted && host && m.type === 'dossier_summary' && m.patient_id === selected) loadSummary(m.summary);
    });
    function select(pid) { selected = pid; current = null; if (mounted && host) render(host); }
    Views.register('dossier', { title: 'Dossier médical', perm: 'open_medical_record', mount(el) { mounted = true; render(el); }, unmount() { mounted = false; if (chart) { chart.destroy(); chart = null; } if (observer) observer.disconnect(); } });
    return { select };
})();
