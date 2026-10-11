/**
 * HackCure V3 — export HL7 FHIR R4 depuis le dossier médical.
 * Ajoute le bouton « Exporter en FHIR » dans la barre d'outils de la vue « Dossier médical » (sans modifier views/dossier.js) :
 * la vue est redessinée à chaque changement de patient, un MutationObserver remet donc le bouton une fois par rendu.
 * Au clic : GET /fhir/Patient/{id}/$everything (cookie de session, même origine) puis téléchargement de « PAT-xxxx-fhir.json ».
 * Le serveur applique les droits du rôle (contenu restreint, identité pseudonymisée) et trace l'export.
 */
(() => {
    'use strict';
    const BTN_ID = 'fhir-export-btn';

    function toast(msg, level) {
        if (window.Api && typeof Api.toast === 'function') Api.toast(msg, level || 'info'); else console.log('[fhir]', msg);
    }

    // Patient affiché : la vue garde sa sélection en interne, le sélecteur #dos-patient en est le reflet dans le DOM
    function selectedPatient() {
        const sel = document.getElementById('dos-patient');
        return sel && sel.value ? sel.value : null;
    }

    function pseudonym(bundle, fallback) {
        const entry = (bundle.entry || []).find(e => e.resource && e.resource.resourceType === 'Patient');
        return (entry && entry.resource.id) || fallback;
    }

    function download(name, text) {
        const url = URL.createObjectURL(new Blob([text], { type: 'application/fhir+json' }));
        const a = document.createElement('a');
        a.href = url; a.download = name; a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1000);
    }

    async function exportFhir(btn) {
        const pid = selectedPatient();
        if (!pid) { toast('Aucun patient sélectionné', 'warning'); return; }
        const label = btn.textContent;
        btn.disabled = true; btn.textContent = 'Export FHIR…';
        try {
            const r = await fetch(`/fhir/Patient/${encodeURIComponent(pid)}/$everything`, { credentials: 'same-origin', headers: { Accept: 'application/fhir+json' } });
            let data = null;
            try { data = await r.json(); } catch (_) { /* réponse non JSON */ }
            if (!r.ok || !data) {
                const issue = data && data.issue && data.issue[0];
                throw new Error((issue && issue.diagnostics) || (data && data.detail) || `Export FHIR impossible (HTTP ${r.status})`);
            }
            const code = pseudonym(data, pid);
            download(`${code}-fhir.json`, JSON.stringify(data, null, 2));
            toast(`Export FHIR R4 de ${code} : ${data.total != null ? data.total : (data.entry || []).length} ressource(s)`, 'success');
        } catch (e) {
            toast(e.message || 'Export FHIR impossible', 'critical');
        } finally {
            btn.disabled = false; btn.textContent = label;
        }
    }

    function inject() {
        const sel = document.getElementById('dos-patient');
        if (!sel || document.getElementById(BTN_ID)) return;
        const bar = sel.closest('.view-toolbar');
        if (!bar) return;
        const btn = document.createElement('button');
        btn.id = BTN_ID;
        btn.type = 'button';
        btn.className = 'btn btn-sm fhir-export-btn';
        btn.title = 'Télécharger le dossier au format HL7 FHIR R4 (JSON, identifiants pseudonymisés)';
        btn.textContent = '⇩ Exporter en FHIR';
        btn.addEventListener('click', () => exportFhir(btn));
        bar.appendChild(btn);
    }

    function start() {
        const root = document.getElementById('view-body') || document.body;
        if (!root || typeof MutationObserver === 'undefined') return;
        new MutationObserver(inject).observe(root, { childList: true, subtree: true });
        inject();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
