/**
 * HackCure — statut de l'orchestration n8n (badge dans la barre du haut, bouton « Ouvrir n8n »).
 * online = n8n orchestre les risques ; offline = repli sur les agents locaux ; disabled = N8N_ENABLED=0.
 */
const N8nStatus = (() => {
    'use strict';
    let info = null;

    function render() {
        const el = document.getElementById('n8n-status'); if (!el) return;
        const st = info ? info.status : 'disabled';
        el.className = `n8n-badge n8n-${st}`;
        const txt = { online: 'n8n · orchestration', offline: 'n8n hors ligne · repli local', disabled: 'n8n désactivé' }[st] || 'n8n';
        el.querySelector('.n8n-text').textContent = txt;
        el.title = info && info.base_url ? `${txt} — ${info.base_url}${info.last_error ? ' (' + info.last_error + ')' : ''} · ${info.sent || 0} événement(s) envoyé(s), ${info.fallbacks || 0} repli(s)` : txt;
        const btn = document.getElementById('btn-open-n8n');
        if (btn) {
            const allowed = Auth.can('write_medical_docs') || Auth.can('manage_users');
            btn.classList.toggle('hidden', !(allowed && info && info.enabled));
            if (info && info.base_url) btn.href = info.base_url;
        }
    }

    async function load() {
        try { info = await Api.get('/api/n8n/status', { noRedirect: true }); } catch (_) { info = null; }
        render();
    }

    document.addEventListener('DOMContentLoaded', () => { Auth.onReady(() => { load(); setInterval(load, 30000); }); });
    window.addEventListener('hackcure:ws', (e) => { if (e.detail.type === 'n8n_status') { info = Object.assign(info || {}, e.detail); render(); } });
    return { load, get info() { return info; } };
})();
window.N8nStatus = N8nStatus;
