/**
 * HackCure V3 — indicateur « Intégrité des trames » de la page Machines (vue `devices`).
 *
 * Carte injectée en tête de la vue quand elle est affichée (MutationObserver sur #view-body : la vue peut être
 * reconstruite à tout moment par Views.show / Views.refresh), alimentée par GET /api/integrity toutes les 5 s
 * tant que la vue est visible. Aucun autre fichier n'est modifié : sans ce script, la page Machines est inchangée.
 */
(function () {
    'use strict';
    const CARD_ID = 'frame-integrity-card';
    const POLL_MS = 5000;
    const REASONS = [
        ['bad_signature', 'signature invalide'],
        ['replay', 'rejeu'],
        ['stale', 'trop ancienne'],
        ['unsigned', 'non signée'],
    ];
    let timer = null;
    let last = null;
    let loading = false;

    const esc = (s) => (typeof Api !== 'undefined' && Api.esc) ? Api.esc(s) : String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const fmtTime = (iso) => { try { return iso ? new Date(iso).toLocaleTimeString('fr-FR') : '—'; } catch (_) { return '—'; } };
    const num = (n) => Number(n || 0).toLocaleString('fr-FR');

    function onDevicesView() {
        return typeof Views !== 'undefined' && Views.current === 'devices';
    }

    function render(d) {
        const c = d.counters || {};
        const by = c.byReason || {};
        const enforced = d.mode === 'enforced';
        const modeTag = enforced
            ? '<span class="tag tag-low">Vérification HMAC-SHA256 active</span>'
            : '<span class="tag tag-warn">Mode démo — clé non configurée, trames acceptées sans vérification</span>';
        const accepted = enforced
            ? `<span class="fi-stat"><b>${num(c.verified)}</b> acceptées (signature vérifiée)</span>`
            : `<span class="fi-stat"><b>${num(c.unverified)}</b> acceptées sans vérification</span>`;
        const rejected = `<span class="fi-stat"><span class="tag ${c.rejected ? 'tag-danger' : ''}">${num(c.rejected)} rejetée${c.rejected > 1 ? 's' : ''}</span></span>`;
        const reasons = REASONS.map(([k, label]) => `<span class="fi-reason${by[k] ? ' fi-hit' : ''}">${label} : <b>${num(by[k])}</b></span>`).join('');
        const lr = d.lastRejection;
        const lastRej = lr
            ? `Dernier rejet : <b>${esc(lr.label || lr.reason)}</b> · ${esc(lr.sender || '?')} · <span class="fi-topic">${esc(lr.topic)}</span> · ${fmtTime(lr.at)}`
            : 'Aucun rejet depuis le démarrage du serveur.';
        const senders = (d.senders || []).length ? ` · ${d.senders.length} émetteur${d.senders.length > 1 ? 's' : ''} authentifié${d.senders.length > 1 ? 's' : ''}` : '';
        return `<h3>Intégrité des trames <span class="muted small fi-sub">séquence · horodatage (≤ ${esc(Math.round(d.maxAgeS || 30))} s) · signature${senders}</span></h3>
            <div class="fi-row">${modeTag}${accepted}${rejected}</div>
            <div class="fi-row fi-reasons small">${reasons}</div>
            <div class="fi-last small ${lr ? '' : 'muted'}">${lastRej}</div>`;
    }

    function paint() {
        const card = document.getElementById(CARD_ID);
        if (!card) return;
        if (last && last.error) card.innerHTML = `<h3>Intégrité des trames</h3><div class="muted small">Indicateur indisponible (${esc(last.error)}).</div>`;
        else if (last) card.innerHTML = render(last);
        else card.innerHTML = '<h3>Intégrité des trames</h3><div class="muted small">Chargement…</div>';
    }

    async function load() {
        if (loading || typeof Api === 'undefined') return;
        loading = true;
        try {
            last = await Api.get('/api/integrity', { noRedirect: true });
        } catch (e) {
            last = { error: (e && e.message) || 'erreur' };
        } finally {
            loading = false;
        }
        paint();
    }

    function stop() {
        if (timer) { clearInterval(timer); timer = null; }
    }

    function ensure() {
        const body = document.getElementById('view-body');
        if (!body || !onDevicesView()) { stop(); return; }
        if (!document.getElementById(CARD_ID)) {
            const card = document.createElement('div');
            card.id = CARD_ID;
            card.className = 'card frame-integrity';
            body.insertBefore(card, body.firstChild);
            paint();
            load();
        }
        if (!timer) {
            timer = setInterval(() => {
                if (!onDevicesView() || !document.getElementById(CARD_ID)) { stop(); return; }
                if (!document.hidden) load();
            }, POLL_MS);
        }
    }

    function init() {
        const body = document.getElementById('view-body');
        if (!body || typeof MutationObserver === 'undefined') return;
        new MutationObserver(() => { try { ensure(); } catch (e) { console.error('frame-integrity', e); } }).observe(body, { childList: true });
        try { ensure(); } catch (e) { console.error('frame-integrity', e); }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
