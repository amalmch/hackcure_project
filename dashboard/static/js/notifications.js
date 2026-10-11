/**
 * HackCure — cloche de notifications (in-app) : badge non lues, liste, toasts temps réel.
 */
const Notifications = (() => {
    'use strict';
    let items = [];
    let unread = 0;
    const ICON = { info: 'ℹ️', warning: '⚠️', critical: '🚨' };

    function badge() {
        const b = document.getElementById('notif-badge'); if (!b) return;
        b.dataset.count = unread; b.textContent = unread > 99 ? '99+' : (unread || '');
    }

    function itemHtml(n) {
        return `<div class="notif-item level-${n.level} ${n.read ? '' : 'unread'}" data-id="${n.id}" data-risk="${n.risk_id || ''}">
            <div class="notif-title"><span>${ICON[n.level] || ''} ${Api.esc(n.title)}</span><span class="notif-time">${Api.fmtTime(n.created_at)}</span></div>
            <div class="notif-body">${Api.esc(n.body || '')}</div>
            <div class="muted small">→ ${({ duty_doctor: 'médecin de garde', nurse: 'infirmier', psychiatrist: 'psychiatre', general_doctor: 'médecin généraliste', pharmacist: 'pharmacien' }[n.target_role] || 'tous')} · ${(n.channels || []).includes('telegram') ? (n.telegram_sent ? 'Telegram ✓' : 'Telegram') : 'in-app'}</div>
        </div>`;
    }

    function render() {
        const dd = document.getElementById('notif-dropdown'); if (!dd) return;
        dd.innerHTML = `<div class="notif-head"><span>Notifications (${unread} non lue${unread > 1 ? 's' : ''})</span><button class="btn btn-sm" id="notif-read-all">Tout marquer lu</button></div>`
            + (items.length ? items.map(itemHtml).join('') : '<div class="empty">Aucune notification</div>');
        dd.querySelector('#notif-read-all')?.addEventListener('click', async () => { await Api.post('/api/notifications/read-all'); items.forEach(i => i.read = true); unread = 0; badge(); render(); });
        dd.querySelectorAll('.notif-item').forEach(el => el.addEventListener('click', async () => {
            const id = Number(el.dataset.id); const it = items.find(i => i.id === id);
            if (it && !it.read) { it.read = true; unread = Math.max(0, unread - 1); badge(); try { await Api.post(`/api/notifications/${id}/read`); } catch (_) { } }
            el.classList.remove('unread');
            if (el.dataset.risk) { toggle(false); AgentsPanel.openRisk(Number(el.dataset.risk)); }
        }));
    }

    function toggle(force) {
        const dd = document.getElementById('notif-dropdown'); if (!dd) return;
        const show = force !== undefined ? force : dd.classList.contains('hidden');
        dd.classList.toggle('hidden', !show);
        document.getElementById('demo-menu')?.classList.add('hidden');
        if (show) render();
    }

    async function load() {
        try { const d = await Api.get('/api/notifications?limit=40', { noRedirect: true }); items = d.items; unread = d.unread; badge(); } catch (_) { }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.getElementById('notif-bell')?.addEventListener('click', (e) => { e.stopPropagation(); toggle(); });
        document.addEventListener('click', (e) => { if (!e.target.closest('#notif-dropdown') && !e.target.closest('#notif-bell')) document.getElementById('notif-dropdown')?.classList.add('hidden'); });
        Auth.onReady(load);
    });
    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type !== 'notification') return;
        items.unshift({ ...m, read: false }); if (items.length > 60) items.length = 60;
        unread += 1; badge();
        Api.toast(`${ICON[m.level] || ''} ${m.title}`, m.level === 'critical' ? 'critical' : (m.level === 'warning' ? 'warning' : 'info'));
        if (!document.getElementById('notif-dropdown')?.classList.contains('hidden')) render();
    });
    return { load, toggle };
})();
