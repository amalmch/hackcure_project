/**
 * HackCure V3 — SADM (système d'aide à la décision médicale), extension additive.
 *
 * Sans modifier les vues existantes, ce script :
 *  1. affiche un bandeau permanent « Recommandation consultative — la décision et la signature restent celles du médecin » ;
 *  2. ajoute sous chaque recommandation affichée (risque et plan d'action, parcours fièvre et bilan biologique proposé,
 *     hypothèses diagnostiques, prédictions, psychologie) une bande : indice de confiance (méthode de calcul en infobulle),
 *     paramètres cliniques déclencheurs, boutons Valider / Rejeter (motif facultatif) tracés dans le journal d'audit ;
 *  3. raccourcit les parcours : « Valider » directement sur une notification, et « Signer » une ordonnance en attente
 *     depuis la cloche (3 actions maximum, voir docs/ergonomie.md).
 * Données : GET /api/sadm/explain, POST /api/sadm/decisions, GET /api/sadm/to-sign.
 */
const SADM = (() => {
    'use strict';
    const BANNER = 'Recommandation consultative — la décision et la signature restent celles du médecin';
    const cache = {};          // clé de requête -> { at, data | error }
    const TTL = 12000;
    let cfg = { enabled: true, can_decide: false };
    let scanTimer = null, ready = false;

    const esc = (s) => (window.Api && Api.esc ? Api.esc(String(s == null ? '' : s)) : String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));
    const qs = (o) => Object.entries(o).filter(([, v]) => v != null && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');

    // ── 1. bandeau permanent ────────────────────────────────────────────────
    function banner() {
        if (document.getElementById('sadm-banner')) return;
        const b = document.createElement('div');
        b.id = 'sadm-banner'; b.setAttribute('role', 'note');
        b.innerHTML = `<span class="sadm-banner-icon">⚖️</span> <b>${BANNER}.</b> <span class="sadm-banner-sub">Aide à la décision — validation médicale requise · données fictives</span>`;
        document.body.appendChild(b);
        document.body.classList.add('has-sadm-banner');
    }

    // ── 2. bande SADM ───────────────────────────────────────────────────────
    async function explain(query) {
        const key = qs(query);
        const hit = cache[key];
        if (hit && (Date.now() - hit.at < TTL || hit.pending)) return hit;
        // la dernière réponse connue reste affichée pendant le rafraîchissement : une vue qui se redessine retrouve sa bande aussitôt
        const entry = cache[key] = { at: Date.now(), data: hit ? hit.data : null, error: null, pending: null };
        entry.pending = Api.get('/api/sadm/explain?' + key, { noRedirect: true }).then(d => { entry.data = d; }).catch(e => { entry.error = e.message || 'indisponible'; }).finally(() => { entry.pending = null; scanSoon(); });
        return entry;
    }

    function stripHtml(d) {
        const c = d.confidence, cls = c.pct >= 80 ? 'high' : (c.pct >= 60 ? 'mid' : 'low');
        const dec = d.decision;
        const decided = dec ? `<span class="sadm-decided ${dec.decision}">${dec.decision === 'validated' ? '✔ Validée' : '✖ Rejetée'} par ${esc(dec.by)} · ${Api.fmtDateTime ? Api.fmtDateTime(dec.at) : esc(dec.at)}${dec.reason ? ' — ' + esc(dec.reason) : ''}</span>` : '';
        const actions = d.can_decide ? `<span class="sadm-actions"><input class="sadm-reason" placeholder="Motif (facultatif)" aria-label="Motif (facultatif)">
            <button class="btn btn-sm btn-success sadm-btn" data-sadm="validated">✔ Valider</button><button class="btn btn-sm btn-warn sadm-btn" data-sadm="rejected">✖ Rejeter</button></span>` : '';
        return `<div class="sadm-head">
                <span class="sadm-conf ${cls}" title="${esc(c.method)} ${esc(d.disclaimer || '')}" tabindex="0">Indice de confiance <b>${c.pct} %</b> (${esc(c.level)}) <span class="sadm-info">ⓘ</span></span>
                <span class="sadm-bar"><span class="sadm-bar-fill ${cls}" style="width:${c.pct}%"></span></span>
                ${decided}${actions}
            </div>
            <details class="sadm-why"${d.triggers.length <= 3 ? ' open' : ''}><summary>Paramètres cliniques déclencheurs (${d.triggers.length})</summary><ul>${d.triggers.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
                <div class="sadm-method">Calcul : ${esc(c.method)}</div></details>
            <div class="sadm-foot">${BANNER}.</div>`;
    }

    function mount(anchor, where, query) {
        const key = qs(query);
        let strip = anchor.parentNode && [...(where === 'append' ? anchor.children : anchor.parentNode.children)].find(n => n.classList && n.classList.contains('sadm-strip') && n.dataset.key === key);
        if (strip && strip.dataset.done === '1' && Date.now() - Number(strip.dataset.at) < TTL) return;
        explain(query).then(entry => {
            if (!entry.data) return;                       // en cours, ou recommandation non concernée (404 / 403) : rien à afficher
            if (!document.body.contains(anchor)) return;
            if (!strip) {
                strip = document.createElement('div'); strip.className = 'sadm-strip'; strip.dataset.key = key;
                if (where === 'append') anchor.appendChild(strip); else anchor.insertAdjacentElement(where, strip);
            }
            if (strip.contains(document.activeElement)) return;   // ne pas effacer un motif en cours de saisie
            strip.innerHTML = stripHtml(entry.data); strip.dataset.done = '1'; strip.dataset.at = String(entry.at);
            strip.querySelectorAll('[data-sadm]').forEach(btn => btn.addEventListener('click', (e) => { e.stopPropagation(); decide(entry.data, btn.dataset.sadm, strip.querySelector('.sadm-reason').value, key); }));
            strip.addEventListener('click', e => e.stopPropagation());
        });
    }

    async function decide(d, decision, reason, key) {
        try {
            await Api.post('/api/sadm/decisions', { kind: d.kind, ref: d.ref, decision, reason: reason || '' });
            Object.keys(cache).forEach(k => delete cache[k]);
            Api.toast(decision === 'validated' ? 'Recommandation validée — tracée dans le journal d\'audit.' : 'Recommandation rejetée — tracée dans le journal d\'audit.', 'success');
            scanSoon(50);
        } catch (e) { Api.toast(e.message, 'critical'); }
    }

    // Où se trouvent les recommandations dans les vues existantes (aucune vue n'est modifiée)
    function scan() {
        if (!ready || !cfg.enabled) return;
        // Centre de commande : risque sélectionné + plan d'action
        const plan = document.getElementById('cmd-plan');
        if (plan) {
            // le premier titre peut être celui du profil clinique : on cherche le titre « #12 · … » du risque
            const m = [...plan.querySelectorAll('h3')].map(h => h.textContent.match(/^\s*#(\d+)/)).find(Boolean);
            const hint = plan.querySelector('.ai-hint');
            if (m && hint) mount(hint, 'afterend', { kind: 'risk', ref: m[1] });
            const fever = plan.querySelector('.fever-panel');
            if (m && fever) { const h = fever.querySelector('h3'); if (h) mount(h, 'afterend', { kind: 'fever', ref: m[1] }); }
        }
        // Diagnostics live : une bande par hypothèse
        const diagPatient = (document.getElementById('diag-patient') || {}).value;
        document.querySelectorAll('.diag-card').forEach(card => {
            const btn = card.querySelector('[data-decide]');
            const h3 = card.querySelector('h3'); if (!h3) return;
            const label = (h3.childNodes[0] && h3.childNodes[0].textContent || '').trim();
            const q = btn ? { kind: 'hypothesis', ref: btn.dataset.decide.split('|')[0] } : { kind: 'hypothesis', patient: diagPatient, label };
            mount(h3, 'afterend', q);
        });
        // Prédictions : une bande par condition détaillée
        const predSel = document.querySelector('.pred-patient.selected');
        if (predSel) document.querySelectorAll('#pred-detail .pred-detail').forEach(block => {
            const b = block.querySelector('b'); if (!b) return;
            const label = b.textContent.replace(/^[^\p{L}]+/u, '').split(' — ')[0].trim();
            mount(block, 'append', { kind: 'prediction', patient: predSel.dataset.id, label });
        });
        // Psychologie : score du patient sélectionné
        const psy = document.querySelector('#psy-list .agent-card.selected');
        const psyScore = document.querySelector('#psy-detail .psy-score');
        if (psy && psyScore) { const h = psyScore.closest('h3'); if (h) mount(h, 'afterend', { kind: 'psych', ref: psy.dataset.id }); }
        notifShortcuts();
    }
    function scanSoon(ms) { if (scanTimer) return; scanTimer = setTimeout(() => { scanTimer = null; try { scan(); } catch (e) { console.error('[SADM]', e); } }, ms == null ? 80 : ms); }

    // ── 3. parcours en 3 actions maximum depuis la cloche ───────────────────
    let toSign = { at: 0, rows: [] };
    async function loadToSign() {
        if (Date.now() - toSign.at < 8000) return;
        toSign.at = Date.now();
        try { toSign.rows = await Api.get('/api/sadm/to-sign', { noRedirect: true }); } catch (_) { toSign.rows = []; }
        scanSoon();
    }
    function notifShortcuts() {
        const dd = document.getElementById('notif-dropdown');
        if (!dd || dd.classList.contains('hidden')) return;
        // (a) valider une alerte : cloche → « Valider » sur la notification (2 actions) ; le détail reste à un clic
        if (cfg.can_decide) dd.querySelectorAll('.notif-item[data-risk]').forEach(item => {
            if (!item.dataset.risk || item.querySelector('.sadm-quick')) return;
            const box = document.createElement('div'); box.className = 'sadm-quick';
            box.innerHTML = '<button class="btn btn-sm btn-success" data-q="validated" title="Valider la recommandation (tracé dans le journal d\'audit)">✔ Valider</button><button class="btn btn-sm btn-warn" data-q="rejected">✖ Rejeter</button><span class="muted small">ou cliquer pour le détail</span>';
            box.querySelectorAll('button').forEach(b => b.addEventListener('click', async (e) => {
                e.stopPropagation();
                try { await Api.post('/api/sadm/decisions', { kind: 'risk', ref: item.dataset.risk, decision: b.dataset.q, reason: '' }); box.innerHTML = `<span class="sadm-decided ${b.dataset.q}">${b.dataset.q === 'validated' ? '✔ Validée' : '✖ Rejetée'} — tracé</span>`; Object.keys(cache).forEach(k => delete cache[k]); }
                catch (err) { Api.toast(err.message, 'critical'); }
            }));
            item.appendChild(box);
        });
        // (b) signer une ordonnance : cloche → « Signer » (2 actions) ; l'alerte d'allergie demande une confirmation explicite (3)
        loadToSign();
        const head = dd.querySelector('.notif-head');
        if (head && !dd.querySelector('.sadm-sign') && toSign.rows.length) {
            const box = document.createElement('div'); box.className = 'sadm-sign';
            box.innerHTML = `<div class="sadm-sign-title">✍️ À signer (${toSign.rows.length})</div>` + toSign.rows.map((r, i) => `<div class="sadm-sign-row"><span>${esc(r.label)}</span><span><button class="btn btn-sm" data-open="${i}">Ouvrir</button><button class="btn btn-sm btn-accent" data-sign="${i}">Signer</button></span></div>`).join('');
            head.insertAdjacentElement('afterend', box);
            box.addEventListener('click', e => e.stopPropagation());
            box.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => { const r = toSign.rows[Number(b.dataset.open)]; dd.classList.add('hidden'); Views.show(r.view); }));
            box.querySelectorAll('[data-sign]').forEach(b => b.addEventListener('click', async () => {
                const r = toSign.rows[Number(b.dataset.sign)];
                const sign = async (force) => Api.post(r.sign_url + (force ? '?force=true' : ''), {});
                try { await sign(false); done(); }
                catch (err) {
                    if (/allergie/i.test(err.message) && b.dataset.confirm !== '1') { b.dataset.confirm = '1'; b.textContent = '⚠ Confirmer malgré l\'allergie'; b.classList.add('btn-warn'); Api.toast(err.message, 'warning'); return; }
                    if (b.dataset.confirm === '1') { try { await sign(true); done(); } catch (e2) { Api.toast(e2.message, 'critical'); } return; }
                    Api.toast(err.message, 'critical');
                }
                function done() { Api.toast(`${r.label} signée — tracée dans le journal d'audit.`, 'success'); toSign.at = 0; box.remove(); if (window.Views && Views.refresh) Views.refresh(); }
            }));
        }
    }

    async function init() {
        try { cfg = await Api.get('/api/sadm/config', { noRedirect: true }); } catch (_) { return; }   // non connecté ou module absent : rien n'est ajouté
        if (!cfg.enabled) return;
        ready = true; banner();
        new MutationObserver((muts) => { if (muts.some(m => !(m.target.closest && m.target.closest('.sadm-strip, #sadm-banner')))) scanSoon(); }).observe(document.body, { childList: true, subtree: true });
        scanSoon(0);
    }
    document.addEventListener('DOMContentLoaded', () => { if (window.Auth && Auth.onReady) Auth.onReady(init); else init(); });
    if (document.readyState !== 'loading') { if (window.Auth && Auth.onReady) Auth.onReady(init); else init(); }

    return { scan: () => scanSoon(0), debug: () => Object.entries(cache).map(([k, v]) => `${k} → ${v.data ? 'ok' : (v.error || 'en cours')}`), state: () => ({ ready, strips: document.querySelectorAll('.sadm-strip').length, banner: !!document.getElementById('sadm-banner'), canDecide: cfg.can_decide }), BANNER };
})();

window.SADM = SADM;
