/**
 * HackCure — session utilisateur côté client.
 * Charge /api/auth/me, affiche utilisateur + rôle dans la barre du haut, gère la déconnexion
 * et expose `Auth.can(permission)` pour filtrer l'interface (l'autorisation réelle est côté serveur).
 */
const Auth = (() => {
    'use strict';
    let user = null;
    const ready = [];

    async function init() {
        try {
            user = await Api.get('/api/auth/me');
        } catch (e) {
            return; // redirection déjà déclenchée sur 401
        }
        renderTopBar();
        document.body.dataset.role = user.role;
        ready.forEach(cb => { try { cb(user); } catch (e) { console.error(e); } });
        ready.length = 0;
    }

    function renderTopBar() {
        const chip = document.getElementById('user-chip');
        if (chip && user) {
            chip.innerHTML = `<span class="user-avatar">${(user.name || user.username).slice(0, 1).toUpperCase()}</span>
                <span class="user-text"><span class="user-name">${Api.esc(user.name || user.username)}</span>
                <span class="user-role">${Api.esc(user.role_label || user.role)}</span></span>`;
        }
        const logout = document.getElementById('btn-logout');
        if (logout) logout.addEventListener('click', async () => {
            try { await Api.post('/api/auth/logout'); } catch (_) { }
            location.href = '/login';
        });
    }

    function can(perm) { return !!(user && user.permissions && user.permissions.includes(perm)); }
    function onReady(cb) { if (user) cb(user); else ready.push(cb); }

    document.addEventListener('DOMContentLoaded', init);

    return { init, can, onReady, get user() { return user; }, get role() { return user ? user.role : null; } };
})();
