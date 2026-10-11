/**
 * Vue « Caméras » : chambre 101 = aperçu MJPEG flouté relayé depuis le Pi (si EDGE_CAMERA_URL),
 * sinon vue schématique ; chambres 102–104 = vue schématique animée à partir de room_state.
 * Aucune image brute n'est affichée ni stockée.
 */
(function () {
    'use strict';
    let mounted = false, timer = null, camStatus = null;
    const POS = { lying_bed: [0.30, 0.42], sitting_bed: [0.30, 0.42], sitting_chair: [0.80, 0.55], standing: [0.52, 0.45], walking: [0.70, 0.78], on_floor: [0.52, 0.52], absent: null };
    const POSTURE_FR = { lying_bed: 'allongé', sitting_bed: 'assis dans le lit', sitting_chair: 'assis au fauteuil', standing: 'debout', walking: 'en marche', on_floor: 'AU SOL', absent: 'absent' };

    function schematic(room) {
        const rs = (window.RoomLive && RoomLive.get(room)) || {};
        const pos = POS[rs.posture] ?? POS.lying_bed;
        const risk = rs.riskLevel || 'none';
        const col = { none: '#22c55e', low: '#22c55e', medium: '#f59e0b', high: '#ef4444', critical: '#a855f7' }[risk];
        const fp = rs.floorPos;
        const px = fp && pos ? 0.35 + fp.x * 0.6 : (pos ? pos[0] : 0.5), py = fp && pos ? 0.2 + fp.y * 0.7 : (pos ? pos[1] : 0.5);
        return `<svg viewBox="0 0 400 300" width="100%" height="100%">
            <rect x="8" y="8" width="384" height="284" rx="8" fill="#0f172a" stroke="${col}" stroke-width="3"/>
            <rect x="40" y="60" width="110" height="170" rx="6" fill="#1e3a5f" stroke="#60a5fa"/><text x="95" y="150" fill="#93c5fd" font-size="12" text-anchor="middle">LIT</text>
            <rect x="290" y="130" width="60" height="60" rx="8" fill="#1f2a44" stroke="#64748b"/><text x="320" y="165" fill="#94a3b8" font-size="10" text-anchor="middle">fauteuil</text>
            <rect x="230" y="270" width="70" height="14" fill="#334155"/><text x="265" y="263" fill="#94a3b8" font-size="10" text-anchor="middle">porte</text>
            <rect x="150" y="8" width="90" height="10" fill="#38bdf8" opacity=".6"/><text x="195" y="32" fill="#7dd3fc" font-size="10" text-anchor="middle">fenêtre</text>
            ${rs.posture !== 'absent' && pos ? `<circle cx="${px * 400}" cy="${py * 300}" r="14" fill="${rs.activity === 'fall' ? '#ef4444' : '#22d3ee'}" stroke="#fff" stroke-width="2"><animate attributeName="r" values="13;16;13" dur="1.6s" repeatCount="indefinite"/></circle>` : ''}
            ${rs.staffPresent ? `<circle cx="${(px || 0.5) * 400 + 40}" cy="${(py || 0.5) * 300 - 20}" r="12" fill="#14b8a6" stroke="#fff" stroke-width="2"/><text x="${(px || 0.5) * 400 + 40}" y="${(py || 0.5) * 300 - 40}" fill="#99f6e4" font-size="10" text-anchor="middle">personnel</text>` : ''}
            <text x="200" y="290" fill="#e2e8f0" font-size="12" text-anchor="middle">${POSTURE_FR[rs.posture] || '—'} · ${rs.persons ?? '?'} pers. · ${rs.expression || 'neutral'}${rs.skinTempC ? ' · ' + Number(rs.skinTempC).toFixed(1) + '°C' : ''}</text>
        </svg>`;
    }

    function card(room, real) {
        const rs = (window.RoomLive && RoomLive.get(room)) || {};
        const src = real && camStatus && camStatus['101'] && camStatus['101'].url && camStatus['101'].edge_alive;
        return `<div class="card"><h3><span class="room-pill">Chambre ${room}</span> ${real ? '<span class="tag tag-warn">caméra réelle · flux flouté</span>' : '<span class="tag">vue schématique</span>'} <span class="muted small">${rs.visionSource ? 'source ' + rs.visionSource : ''}</span></h3>
            ${src ? `<div class="cam-blur"><img src="/api/camera/101/stream?t=${Date.now()}" alt="flux flouté"></div>` : `<div class="cam-schematic" id="cam-${room}">${schematic(room)}</div>`}
            ${real && !src ? '<div class="muted small" style="margin-top:6px">Aucun flux edge (EDGE_CAMERA_URL non défini ou Pi hors ligne) : vue schématique à partir des états publiés par la vision.</div>' : ''}
        </div>`;
    }

    async function render(el) {
        try { camStatus = await Api.get('/api/camera/status'); } catch (_) { camStatus = null; }
        el.innerHTML = `<div class="ai-hint">Vie privée : aucune image ne quitte le Raspberry Pi hors d'un aperçu basse résolution flouté (chambre 101, rôles médicaux). Les autres chambres sont représentées schématiquement à partir de l'état (posture, nombre de personnes, expression, température).</div>
            <div class="grid-2">${card('101', true)}${card('102', false)}${card('103', false)}${card('104', false)}</div>`;
    }

    function tick() { if (!mounted) return; ['101', '102', '103', '104'].forEach(r => { const el = document.getElementById(`cam-${r}`); if (el) el.innerHTML = schematic(r); }); }
    Views.register('cameras', { title: 'Caméras', perm: 'view_clinical', mount(el) { mounted = true; render(el); timer = setInterval(tick, 1000); }, unmount() { mounted = false; clearInterval(timer); } });
})();
