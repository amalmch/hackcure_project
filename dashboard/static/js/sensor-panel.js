/**
 * HackCure — panneau « Capteurs d'environnement » (barre gauche, repris du panneau capteurs d'Amal).
 * Affiche les vraies mesures de `room_state.env` (température, humidité, porte) et l'état des équipements.
 */
const SensorPanel = (() => {
    'use strict';
    const rooms = {};
    const EQ = { window: ['🪟', { open: 'ouverte', closed: 'fermée' }], heater: ['🔥', { on: 'marche', off: 'arrêt' }], ac: ['❄️', { on: 'marche', off: 'arrêt' }], light: ['💡', { on: 'allumée', off: 'éteinte' }] };

    function row(code) {
        const rs = rooms[code] || {}, env = rs.env || {}, eq = rs.equipment || {};
        const t = env.tempC != null ? `${Number(env.tempC).toFixed(1)} °C` : '—';
        const h = env.humidity != null ? `${Math.round(env.humidity)} %` : '—';
        const cls = env.tempC == null ? '' : (env.tempC > 27 ? 'hot' : env.tempC < 19 ? 'cold' : 'ok');
        const active = Object.keys(EQ).filter(k => eq[k] === 'open' || eq[k] === 'on').map(k => `<span title="${k} : ${EQ[k][1][eq[k]]}">${EQ[k][0]}</span>`).join('');
        return `<div class="sensor-row ${cls}"><span class="sensor-room">${code}</span><span class="sensor-temp">🌡️ ${t}</span><span class="sensor-hum">💧 ${h}</span><span class="sensor-eq">${env.doorOpen ? '🚪' : ''}${active}</span></div>`;
    }

    function render() {
        const el = document.getElementById('sensor-rows'); if (!el) return;
        const codes = Object.keys(rooms).sort();
        el.innerHTML = codes.length ? codes.map(row).join('') : '<div class="muted small">En attente des capteurs…</div>';
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'room_state' && m.room) { rooms[m.room] = m; render(); }
        else if (m.type === 'init' && m.room_states) { Object.assign(rooms, m.room_states); render(); }
    });
    document.addEventListener('DOMContentLoaded', () => {
        if (typeof Auth === 'undefined') return;
        Auth.onReady(async () => { try { Object.assign(rooms, await Api.get('/api/rooms/states', { noRedirect: true })); render(); } catch (_) { /* rôle sans accès clinique */ } });
    });
    return { render, rooms };
})();
