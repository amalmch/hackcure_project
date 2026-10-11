/**
 * Vue « Ambulances » (V2, étape 5) : carte Leaflet + OpenStreetMap centrée sur la clinique, position des
 * ambulances en temps réel, itinéraire, heure d'arrivée estimée (ETA) mise à jour en continu, fiche
 * d'intervention, chambre réservée automatiquement au départ.
 * GPS simulé (trajet le long d'une polyligne) ou réel (téléphone de l'équipe sur /ambulance/track/{jeton}).
 */
(() => {
    'use strict';
    let mounted = false, host = null, info = null, map = null, layers = {}, records = [];
    const canManage = () => Auth.can('manage_ambulances');
    const ST = { en_route: ['en route', 'tag-warn'], arrived: ['arrivée — transfert', 'tag-high'], admitted: ['patient installé', 'tag-ok'], cancelled: ['annulée', ''] };
    const icon = (emoji, cls) => L.divIcon({ html: `<div class="map-pin ${cls || ''}">${emoji}</div>`, className: '', iconSize: [34, 34], iconAnchor: [17, 17] });
    const eta = (m) => m.status === 'en_route' ? (m.eta_seconds >= 90 ? `${Math.round(m.eta_seconds / 60)} min` : `${m.eta_seconds} s`) : '—';

    function missionHtml(m) {
        const prep = (m.ai && m.ai.preparation && m.ai.preparation.materiel.length ? m.ai.preparation : m.preparation) || {};
        const list = (t, xs) => xs && xs.length ? `<div class="small"><b>${t}</b> : ${xs.map(Api.esc).join(' · ')}</div>` : '';
        const v = m.vitals || {};
        return `<div class="card mission ${m.status}" data-mission="${m.id}"><h3>🚑 ${Api.esc(m.ambulance)} <span class="tag ${ST[m.status][1]}">${ST[m.status][0]}</span> ${m.status === 'en_route' ? `<span class="eta-big" data-eta="${m.id}">ETA ${eta(m)}</span>` : ''}</h3>
            <div class="small"><b>${Api.esc(m.patient_name)}</b>${m.age ? ` · ${m.age} ans` : ''} · <span class="tag tag-danger">${Api.esc(m.emergency_label)}</span> <span class="tag">${Api.esc(m.severity_label)}</span></div>
            <div class="small">Motif : ${Api.esc(m.reason)}</div>
            <div class="small">Constantes transmises : ${Object.keys(v).length ? Object.entries(v).map(([k, x]) => `${Api.esc(k)} ${Api.esc(x)}`).join(' · ') : 'non transmises'}</div>
            <div class="small">Départ ${new Date(m.departed_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })} · ${Api.esc(m.route_label)} · <span data-dist="${m.id}">${(m.remaining_m / 1000).toFixed(1)} km restants, ${m.speed_kmh} km/h</span></div>
            <div class="small">Chambre <span class="room-pill">${m.reserved_room}</span> ${m.status === 'en_route' ? '<b>réservée</b>' : m.status === 'admitted' ? `— admission #${m.admission_id}` : ''}</div>
            ${m.ai && m.ai.briefing ? `<div class="ai-hint">🧠 ${Api.esc(m.ai.briefing)}${m.ai.fallback ? ' <span class="tag tag-fallback">réponse de secours</span>' : ''}</div>` : ''}
            ${list('Matériel', prep.materiel)}${list('Équipe', prep.equipe)}${list('Examens', prep.examens)}
            ${m.status === 'en_route' ? `<div class="inline-form" style="margin-top:6px">${m.mode === 'gps' || canManage() ? `<a class="btn btn-sm" href="${m.track_url}" target="_blank" rel="noopener" title="À ouvrir sur le téléphone de l'équipe (HTTPS ou localhost)">📱 Suivi GPS réel</a>` : ''}
                ${canManage() ? `<button class="btn btn-sm btn-warn" data-cancel="${m.id}">Annuler</button>` : ''}</div>` : ''}</div>`;
    }

    function formHtml() {
        const out = records.filter(p => !p.room), inside = records.filter(p => p.room);
        return `<div class="card"><h3>Fiche d'intervention — départ d'une ambulance</h3>
            ${info.free_rooms.length ? `<div class="small">Chambres libres : ${info.free_rooms.map(r => `<span class="room-pill">${r}</span>`).join(' ')}</div>` : `<div class="ai-hint" style="border-left-color:#f59e0b">Aucune chambre libre : une sortie est nécessaire avant le départ.
                ${Auth.can('edit_patients') && inside.length ? `<div class="inline-form" style="margin-top:6px"><select id="amb-out">${inside.map(p => `<option value="${p.patient_id}">${Api.esc(p.full_name)} · ch. ${p.room}</option>`).join('')}</select><button class="btn btn-sm" id="amb-discharge">Faire la sortie (démo)</button></div>` : ''}</div>`}
            <div class="form-grid" style="margin-top:8px">
                <label>Patient <select id="amb-patient"><option value="">— nouveau patient —</option>${out.map(p => `<option value="${p.patient_id}">${Api.esc(p.full_name)} (${p.code}, déjà connu)</option>`).join('')}</select></label>
                <label>Type d'urgence <select id="amb-type">${Object.entries(info.types).map(([k, v]) => `<option value="${k}">${Api.esc(v)}</option>`).join('')}</select></label>
                <label class="amb-new">Prénom <input id="amb-first" placeholder="Prénom"></label><label class="amb-new">Nom <input id="amb-last" placeholder="Nom"></label>
                <label class="amb-new">Âge <input id="amb-age" type="number" value="60" min="0" max="120"></label>
                <label>Gravité <select id="amb-sev">${Object.entries(info.severities).map(([k, v]) => `<option value="${k}" ${k === '2' ? 'selected' : ''}>${Api.esc(v)}</option>`).join('')}</select></label>
                <label>Motif <input id="amb-reason" placeholder="ex. douleur thoracique depuis 30 min"></label>
                <label>Constantes (ambulance) <input id="amb-vitals" placeholder="FC 110, PA 95/60, SpO2 93"></label>
                <label>GPS <select id="amb-mode"><option value="sim">Simulé (trajet le long d'un itinéraire)</option><option value="gps">Réel (téléphone de l'équipe)</option></select></label>
                <label>Itinéraire simulé <select id="amb-route">${Object.entries(info.routes).map(([k, v]) => `<option value="${k}">${Api.esc(v.label)} — ${v.km} km</option>`).join('')}</select></label>
            </div><div class="inline-form" style="margin-top:8px"><button class="btn btn-accent" id="amb-go">🚑 Départ de l'ambulance</button><span class="muted small">Au départ, une chambre adaptée est réservée et l'équipe est prévenue.${info.time_scale > 1 ? ` Trajet simulé accéléré ×${info.time_scale}.` : ''}</span></div></div>`;
    }

    function paintList() {
        const el = host.querySelector('#amb-list'); if (!el) return;
        const active = info.missions.filter(m => m.status === 'en_route' || m.status === 'arrived'), done = info.missions.filter(m => !(m.status === 'en_route' || m.status === 'arrived'));
        const typing = el.contains(document.activeElement) && ['INPUT', 'SELECT'].includes(document.activeElement.tagName);
        if (typing) return;
        el.innerHTML = active.map(missionHtml).join('') + (canManage() ? formHtml() : '') + (done.length ? `<h3 style="margin-top:10px">Missions terminées</h3>${done.slice(0, 6).map(missionHtml).join('')}` : '');
        const sel = el.querySelector('#amb-patient'), toggle = () => el.querySelectorAll('.amb-new').forEach(x => x.style.display = sel && sel.value ? 'none' : '');
        sel?.addEventListener('change', toggle); toggle();
        el.querySelector('#amb-discharge')?.addEventListener('click', async () => { try { await Api.post(`/api/records/${el.querySelector('#amb-out').value}/discharge`); Api.toast('Sortie enregistrée : chambre libre', 'success'); document.activeElement.blur(); load(); } catch (e) { Api.toast(e.message, 'critical'); } });
        el.querySelector('#amb-go')?.addEventListener('click', async () => {
            const g = (id) => el.querySelector(id).value.trim();
            const vitals = {}; g('#amb-vitals').split(',').map(x => x.trim()).filter(Boolean).forEach(x => { const i = x.indexOf(' '); if (i > 0) vitals[x.slice(0, i)] = x.slice(i + 1); });
            const body = { reason: g('#amb-reason'), emergency_type: g('#amb-type'), severity: Number(g('#amb-sev')), vitals, mode: g('#amb-mode'), route: g('#amb-route') };
            if (!body.reason) { Api.toast('Motif requis', 'warning'); return; }
            if (g('#amb-patient')) body.patient_id = g('#amb-patient'); else { if (!g('#amb-first') || !g('#amb-last')) { Api.toast('Prénom et nom du nouveau patient requis', 'warning'); return; } body.new_patient = { first_name: g('#amb-first'), last_name: g('#amb-last'), age: Number(g('#amb-age')) || 60 }; }
            try { const m = await Api.post('/api/ambulances/missions', body); Api.toast(`Ambulance partie : chambre ${m.reserved_room} réservée, arrivée dans ${Math.max(1, Math.round(m.eta_seconds / 60))} min`, 'success'); document.activeElement.blur(); load(); } catch (e) { Api.toast(e.message, 'critical'); }
        });
        el.querySelectorAll('[data-cancel]').forEach(b => b.addEventListener('click', async () => { try { await Api.post(`/api/ambulances/missions/${b.dataset.cancel}/cancel`); load(); } catch (e) { Api.toast(e.message, 'critical'); } }));
    }

    function paintMap(fit) {
        if (!map || !info) return;
        const seen = new Set();
        info.missions.filter(m => m.status === 'en_route' || m.status === 'arrived').forEach(m => {
            seen.add(m.id);
            let l = layers[m.id];
            if (!l) { l = layers[m.id] = { marker: L.marker([m.lat, m.lon], { icon: icon('🚑', 'amb'), zIndexOffset: 500 }).addTo(map), line: L.polyline([], { color: '#ef4444', weight: 4, opacity: .75, dashArray: m.mode === 'gps' ? null : '8 8' }).addTo(map) }; }
            l.marker.setLatLng([m.lat, m.lon]).bindTooltip(`${m.ambulance} — ${m.patient_name}<br>ETA ${eta(m)} · chambre ${m.reserved_room}`, { permanent: true, direction: 'top', offset: [0, -16], className: 'map-tip' });
            if (m.route && m.route.length) l.line.setLatLngs(m.route);
        });
        Object.keys(layers).forEach(id => { if (!seen.has(Number(id))) { map.removeLayer(layers[id].marker); map.removeLayer(layers[id].line); delete layers[id]; } });
        if (fit) { const pts = [[info.clinic.lat, info.clinic.lon]]; Object.values(layers).forEach(l => { pts.push(l.marker.getLatLng()); l.line.getLatLngs().forEach(p => pts.push(p)); }); if (pts.length > 1) map.fitBounds(pts, { padding: [40, 40] }); else map.setView(pts[0], 14); }
    }

    function onPosition(m) {
        if (!info) return;
        const i = info.missions.findIndex(x => x.id === m.id);
        if (i < 0) { load(); return; }
        const route = info.missions[i].route;
        info.missions[i] = Object.assign({}, m, { route: m.mode === 'gps' ? [...(route || []), [m.lat, m.lon]] : route });
        paintMap(false);
        const e = host.querySelector(`[data-eta="${m.id}"]`), d = host.querySelector(`[data-dist="${m.id}"]`);
        if (e) e.textContent = `ETA ${eta(m)}`;
        if (d) d.textContent = `${(m.remaining_m / 1000).toFixed(1)} km restants, ${m.speed_kmh} km/h`;
    }

    async function load(fit) {
        if (!mounted) return;
        try { info = await Api.get('/api/ambulances'); records = Auth.can('view_patients') ? await Api.get('/api/records') : []; } catch (e) { host.querySelector('#amb-list').innerHTML = `<div class="view-error">${Api.esc(e.message)}</div>`; return; }
        if (!map && typeof L !== 'undefined') {
            map = L.map(host.querySelector('#amb-map'), { zoomControl: true }).setView([info.clinic.lat, info.clinic.lon], 13);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map);
            L.marker([info.clinic.lat, info.clinic.lon], { icon: icon('🏥', 'clinic') }).addTo(map).bindTooltip(info.clinic.name, { permanent: true, direction: 'bottom', offset: [0, 14], className: 'map-tip' });
            fit = true;
        }
        if (typeof L === 'undefined') host.querySelector('#amb-map').innerHTML = '<div class="empty">Carte indisponible (Leaflet non chargé : pas de réseau). Les missions restent suivies dans la liste.</div>';
        paintList(); paintMap(fit);
        if (map) setTimeout(() => map.invalidateSize(), 60);
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail; if (!mounted || m.type !== 'ambulance') return;
        if (m.event === 'position') onPosition(m.mission); else load(m.event === 'dispatched');
    });
    Views.register('ambulances', { title: 'Ambulances', perm: 'view_ambulances',
        mount(el) { mounted = true; host = el; map = null; layers = {};
            el.innerHTML = `<div class="grid-2" style="grid-template-columns:1fr 1.25fr;align-items:start"><div id="amb-list"></div><div class="card" style="padding:6px"><div id="amb-map" style="height:calc(100vh - 210px);min-height:420px;border-radius:8px"></div>
                <div class="muted small" style="padding:4px 6px">Coordonnées de démonstration (Tunis). GPS réel : ouvrir le lien « Suivi GPS réel » sur un téléphone — voir docs/ambulance.md.</div></div></div>`; load(true); },
        unmount() { mounted = false; if (map) { map.remove(); map = null; } layers = {}; } });
})();
