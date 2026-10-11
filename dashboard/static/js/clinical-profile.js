/**
 * HackCure — « Profil clinique » (V2) : bandeau affiché en tête des vues patient.
 * Allergies, maladies chroniques, antécédents, traitements actifs — extraits du dossier médical
 * (`GET /api/dossier/{patient_id}/profile`, contenu restreint par le serveur selon le rôle).
 */
const ClinicalProfile = (() => {
    'use strict';
    const cache = {};

    function html(p) {
        if (!p) return '';
        const tags = (xs, cls, fmt) => xs && xs.length ? xs.map(x => `<span class="tag ${cls}">${Api.esc(fmt(x))}</span>`).join(' ') : '<span class="muted">aucun</span>';
        const rows = [];
        if (p.allergies) rows.push(['⚠️ Allergies', p.allergies.length ? tags(p.allergies, 'tag-danger', a => a.allergen + (a.since ? ` (${a.since})` : '')) : '<span class="tag tag-ok">aucune connue</span>']);
        if (p.chronic) rows.push(['♾️ Maladies chroniques', tags(p.chronic, 'tag-warn', c => `${c.label} (${c.since})`)]);
        if (p.history) rows.push(['📁 Antécédents', p.history.length ? `<span class="small">${p.history.slice(-6).map(h => Api.esc(`${h.label} (${h.year})`)).join(' · ')}</span>` : '<span class="muted">aucun</span>']);
        const treatments = [...(p.hospital_treatments || []).map(t => `${t.dci} ${t.posology} ${t.route}`), ...(p.long_term_treatments || []).map(t => `${t.dci} ${t.posology}`)];
        if (p.hospital_treatments || p.long_term_treatments) rows.push(['💊 Traitements actifs', treatments.length ? `<span class="small">${treatments.map(Api.esc).join(' · ')}</span>` : '<span class="muted">aucun</span>']);
        return `<div class="clinical-profile"><div class="cp-head"><b>${Api.esc(p.name)}</b> <span class="muted small">${Api.esc(p.code || '')} · ${p.age} ans${p.sex ? ' · ' + p.sex : ''}${p.blood_group ? ' · groupe ' + p.blood_group : ''}${p.room ? ' · chambre ' + p.room : ''}${p.admission_reason ? ' · ' + Api.esc(p.admission_reason) : ''}</span>
            <span class="cp-title">Profil clinique</span></div>${rows.map(([k, v]) => `<div class="cp-row"><span class="cp-key">${k}</span><span>${v}</span></div>`).join('')}</div>`;
    }

    /** Charge (avec cache de 60 s) et insère le profil du patient dans `el`. */
    async function mount(el, patientId) {
        if (!el || !patientId) return;
        const c = cache[patientId];
        if (c && Date.now() - c.t < 60000) { el.innerHTML = html(c.p); return; }
        try { const p = await Api.get(`/api/dossier/${patientId}/profile`, { noRedirect: true }); cache[patientId] = { t: Date.now(), p }; el.innerHTML = html(p); } catch (_) { el.innerHTML = ''; }
    }
    function invalidate(patientId) { delete cache[patientId]; }
    return { html, mount, invalidate };
})();
window.ClinicalProfile = ClinicalProfile;
