/**
 * HackCure — client REST minimal (cookies de session, JSON, redirection vers /login sur 401).
 */
const Api = (() => {
    'use strict';

    async function request(method, url, body, opts = {}) {
        const init = { method, headers: {}, credentials: 'same-origin' };
        if (body !== undefined && body !== null) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(body);
        }
        let resp;
        try {
            resp = await fetch(url, init);
        } catch (e) {
            throw new Error('Serveur injoignable');
        }
        if (resp.status === 401 && !opts.noRedirect) {
            location.href = '/login?next=' + encodeURIComponent(location.pathname);
            throw new Error('Authentification requise');
        }
        if (resp.status === 204) return null;
        const text = await resp.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
        if (!resp.ok) {
            const detail = (data && (data.detail || data.error)) || resp.statusText;
            const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
            err.status = resp.status; err.data = data;
            throw err;
        }
        return data;
    }

    return {
        get: (url, opts) => request('GET', url, undefined, opts),
        post: (url, body, opts) => request('POST', url, body ?? {}, opts),
        put: (url, body, opts) => request('PUT', url, body ?? {}, opts),
        patch: (url, body, opts) => request('PATCH', url, body ?? {}, opts),
        del: (url, opts) => request('DELETE', url, undefined, opts),
        // petit utilitaire d'échappement HTML pour les vues
        esc: (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
        fmtTime: (iso) => iso ? new Date(iso).toLocaleTimeString('fr-FR') : '—',
        fmtDate: (iso) => iso ? new Date(iso).toLocaleDateString('fr-FR') : '—',
        fmtDateTime: (iso) => iso ? new Date(iso).toLocaleString('fr-FR') : '—',
        toast: (msg, level = 'info') => {
            const host = document.getElementById('toast-host');
            if (!host) { console.log('[toast]', msg); return; }
            const el = document.createElement('div');
            el.className = `toast toast-${level}`; el.textContent = msg;
            host.appendChild(el);
            setTimeout(() => el.classList.add('show'), 10);
            setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 4000);
        },
    };
})();
