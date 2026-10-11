/**
 * Vue « Utilisateurs » (owner) : comptes, rôles, activation, création.
 */
(function () {
    'use strict';
    let roles = [];
    async function render(el) {
        let users;
        try { users = await Api.get('/api/users'); roles = (await Api.get('/api/auth/roles')).roles; } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        el.innerHTML = `<div class="card"><h3>Comptes (${users.length})</h3><table class="data"><thead><tr><th>Identifiant</th><th>Nom</th><th>Rôle</th><th>Actif</th><th>Créé</th><th></th></tr></thead><tbody>
            ${users.map(u => `<tr><td><b>${Api.esc(u.username)}</b></td><td>${Api.esc(u.full_name)}</td><td><select data-role="${u.id}">${roles.map(r => `<option value="${r.role}" ${r.role === u.role ? 'selected' : ''}>${r.label}</option>`).join('')}</select></td>
                <td><input type="checkbox" data-active="${u.id}" ${u.active ? 'checked' : ''}></td><td class="muted small">${Api.fmtDate(u.created_at)}</td><td><button class="btn btn-sm" data-pwd="${u.id}">🔑 Mot de passe</button> <button class="btn btn-sm btn-danger" data-del="${u.id}">🗑</button></td></tr>`).join('')}</tbody></table></div>
            <div class="card"><h3>Nouveau compte</h3><div class="inline-form"><input id="u-name" placeholder="identifiant"><input id="u-full" placeholder="nom complet"><input id="u-pwd" type="password" placeholder="mot de passe"><select id="u-role">${roles.map(r => `<option value="${r.role}">${r.label}</option>`).join('')}</select><button class="btn btn-success" id="u-add">Créer</button></div></div>
            <div class="card"><h3>Matrice des permissions</h3><table class="data"><thead><tr><th>Permission</th>${roles.map(r => `<th>${r.label}</th>`).join('')}</tr></thead><tbody>
            ${[...new Set(roles.flatMap(r => r.permissions))].sort().map(p => `<tr><td class="small">${p}</td>${roles.map(r => `<td style="text-align:center">${r.permissions.includes(p) ? '✅' : '—'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
        el.querySelectorAll('[data-role]').forEach(s => s.addEventListener('change', async () => { try { await Api.patch(`/api/users/${s.dataset.role}`, { role: s.value }); Api.toast('Rôle mis à jour', 'success'); } catch (e) { Api.toast(e.message, 'critical'); } }));
        el.querySelectorAll('[data-active]').forEach(c => c.addEventListener('change', async () => { try { await Api.patch(`/api/users/${c.dataset.active}`, { active: c.checked }); } catch (e) { Api.toast(e.message, 'critical'); } }));
        el.querySelectorAll('[data-pwd]').forEach(b => b.addEventListener('click', async () => { const p = prompt('Nouveau mot de passe'); if (!p) return; try { await Api.patch(`/api/users/${b.dataset.pwd}`, { password: p }); Api.toast('Mot de passe modifié', 'success'); } catch (e) { Api.toast(e.message, 'critical'); } }));
        el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => { if (!confirm('Supprimer ce compte ?')) return; try { await Api.del(`/api/users/${b.dataset.del}`); render(el); } catch (e) { Api.toast(e.message, 'critical'); } }));
        el.querySelector('#u-add').addEventListener('click', async () => {
            try { await Api.post('/api/users', { username: el.querySelector('#u-name').value, full_name: el.querySelector('#u-full').value, password: el.querySelector('#u-pwd').value, role: el.querySelector('#u-role').value }); Api.toast('Compte créé', 'success'); render(el); } catch (e) { Api.toast(e.message, 'critical'); }
        });
    }
    Views.register('users', { title: 'Utilisateurs', perm: 'manage_users', mount(el) { render(el); }, unmount() { } });
})();
