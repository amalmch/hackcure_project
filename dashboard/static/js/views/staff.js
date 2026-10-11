/**
 * Vue « Personnel présent » : équipe en service, présence détectée par chambre, dernières visites.
 */
(function () {
    'use strict';
    let mounted = false;

    async function render(el) {
        let data, visits;
        try { data = await Api.get('/api/staff'); visits = await Api.get('/api/staff/visits?limit=20'); } catch (e) { el.innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        const canEdit = Auth.can('manage_risks');
        const presence = ['101', '102', '103', '104'].map(r => {
            const p = data.presence[r] || {};
            const live = window.RoomLive && RoomLive.get(r);
            const present = live ? (live.staffPresent || (live.persons || 0) > 1) : p.staffPresent;
            return `<div class="kpi" style="pointer-events:auto"><span class="kpi-label">Chambre ${r}</span><span class="kpi-value">${present ? '🧑‍⚕️ présent' : '—'}</span><span class="kpi-sub">${(live ? live.persons : p.persons) ?? '?'} personne(s) détectée(s)</span></div>`;
        }).join('');
        el.innerHTML = `<div class="card"><h3>Présence détectée par la vision (personnes > 1 = personnel)</h3><div style="display:flex;gap:10px">${presence}</div></div>
            <div class="grid-2" style="align-items:start">
            <div class="card"><h3>Équipe (${data.on_duty} en service)</h3>
                <table class="data"><thead><tr><th>Nom</th><th>Rôle</th><th>Service</th><th>Chambre</th><th>Téléphone</th></tr></thead><tbody>
                ${data.staff.map(s => `<tr><td>${Api.esc(s.name)}</td><td>${s.role_label}</td>
                    <td><label class="small" style="cursor:${canEdit ? 'pointer' : 'default'}"><input type="checkbox" data-id="${s.id}" ${s.on_duty ? 'checked' : ''} ${canEdit ? '' : 'disabled'}> ${s.on_duty ? '<span class="tag tag-low">en service</span>' : '<span class="tag">repos</span>'}</label></td>
                    <td>${s.current_room ? `<span class="room-pill">${s.current_room}</span>` : '—'}</td><td class="muted">${Api.esc(s.phone || '')}</td></tr>`).join('')}
                </tbody></table>
                ${canEdit ? `<div class="inline-form" style="margin-top:10px"><input id="staff-name" placeholder="Nom"><select id="staff-role"><option value="nurse">Infirmier(ère)</option><option value="aide">Aide-soignant(e)</option><option value="duty_doctor">Médecin de garde</option><option value="general_doctor">Médecin</option></select><button class="btn btn-sm" id="staff-add">+ Ajouter</button></div>` : ''}
            </div>
            <div class="card"><h3>Dernières visites en chambre</h3>
                ${visits.length ? `<table class="data"><thead><tr><th>Chambre</th><th>Début</th><th>Fin</th><th>Durée</th><th>Pers.</th><th>Risque</th></tr></thead><tbody>
                ${visits.map(v => `<tr><td><span class="room-pill">${v.room}</span></td><td>${Api.fmtTime(v.started_at)}</td><td>${v.ended_at ? Api.fmtTime(v.ended_at) : '<span class="tag tag-in_progress">en cours</span>'}</td><td>${v.duration_s != null ? v.duration_s + ' s' : '—'}</td><td>${v.persons}</td><td>${v.risk_id ? `<a style="color:#93c5fd;cursor:pointer" data-risk="${v.risk_id}">#${v.risk_id}</a>` : '—'}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">Aucune visite enregistrée</div>'}
            </div></div>`;
        el.querySelectorAll('input[data-id]').forEach(cb => cb.addEventListener('change', async () => { try { await Api.patch(`/api/staff/${cb.dataset.id}`, { on_duty: cb.checked }); render(el); } catch (e) { Api.toast(e.message, 'critical'); } }));
        el.querySelector('#staff-add')?.addEventListener('click', async () => {
            const name = el.querySelector('#staff-name').value.trim(); if (!name) return;
            try { await Api.post('/api/staff', { name, role: el.querySelector('#staff-role').value }); render(el); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        el.querySelectorAll('a[data-risk]').forEach(a => a.addEventListener('click', () => AgentsPanel.openRisk(Number(a.dataset.risk))));
    }

    let host = null;
    window.addEventListener('hackcure:ws', (e) => { if (mounted && host && (e.detail.type === 'staff_visit')) render(host); });
    Views.register('staff', { title: 'Personnel présent', perm: 'view_clinical', mount(el) { mounted = true; host = el; render(el); }, unmount() { mounted = false; host = null; } });
})();
