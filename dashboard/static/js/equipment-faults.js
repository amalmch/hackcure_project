/**
 * HackCure — pannes d'équipement dans la 3D (extension additive).
 * Source : `room_state.deviceFaults` ({type d'appareil: {name, label, device}}), alimenté par le VitalsAgent
 * (flux de l'appareil ou événement `machine_error`). Affiche :
 *   - dans la chambre : un bandeau « PANNE » au-dessus de la potence, à côté de l'indicateur d'Amal (engrenage) ;
 *   - dans la salle Équipements de l'étage 1 : un tableau du parc et un repère sur le poste de l'appareil de remplacement.
 */
const EquipmentFaults = (() => {
    'use strict';
    const faults = {};      // room -> deviceFaults
    const roomTags = {};    // room -> sprite
    let board = null, markers = null;
    // type d'appareil -> poste de la salle Équipements (floors.js, buildEquipment) : [x, z, n°, nom]
    const STATION = {
        ecg: [-3.0, -1.95, '01', 'CARDIOLOGIE'], spo2: [-3.0, -1.95, '01', 'CARDIOLOGIE'], bp: [-1.35, -1.95, '02', 'TENSION'],
        iv_pump: [0.25, -1.95, '03', 'SÉRUM'], transfusion: [0.25, -1.95, '03', 'SÉRUM'], thermometer: [1.35, -1.85, '04', 'TEMPÉRATURE'],
        nutrition_pump: [-3.62, 0.5, '05', 'NUTRITION'], urine_bag: [2.55, -0.1, '06', 'ÉLIMINATION'],
    };

    function sprite(w, h, cw, ch) {
        const canvas = document.createElement('canvas'); canvas.width = cw; canvas.height = ch;
        const tex = new THREE.CanvasTexture(canvas);
        const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
        s.scale.set(w, h, 1); s.renderOrder = 14; s.userData = { canvas, tex, noCollide: true };
        return s;
    }
    function draw(s, lines, bg) {
        const c = s.userData.canvas, g = c.getContext('2d');
        g.clearRect(0, 0, c.width, c.height);
        g.fillStyle = bg; g.fillRect(0, 0, c.width, c.height);
        g.strokeStyle = 'rgba(255,255,255,0.85)'; g.lineWidth = 4; g.strokeRect(2, 2, c.width - 4, c.height - 4);
        g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = '#fff';
        const step = c.height / (lines.length + 0.4);
        lines.forEach((l, i) => { g.font = (i === 0 ? 'bold ' : '') + Math.round(Math.min(step * 0.62, i === 0 ? 34 : 26)) + 'px sans-serif'; g.fillText(l, c.width / 2, step * (i + 0.7), c.width - 20); });
        s.userData.tex.needsUpdate = true;
    }

    function list() {
        const out = [];
        Object.keys(faults).sort().forEach(room => Object.entries(faults[room] || {}).forEach(([type, f]) => out.push({ room, type, name: f.name || type, label: f.label || 'panne' })));
        return out;
    }

    function renderRoom(room) {
        if (typeof HospitalScene === 'undefined' || !HospitalScene.getScene()) return;
        const f = Object.values(faults[room] || {});
        let tag = roomTags[room];
        if (!f.length) { if (tag) tag.visible = false; return; }
        if (!tag) {
            const g = HospitalScene.getRoomGroup(room); if (!g) return;
            const BED = HospitalScene.BED;
            tag = roomTags[room] = sprite(1.7, 0.56, 512, 168);
            tag.position.set(BED.x + 0.85, 3.15, BED.z - 0.85); g.add(tag);
        }
        draw(tag, ['⚠ PANNE D\'ÉQUIPEMENT'].concat(f.slice(0, 2).map(x => `${x.name} — ${x.label}`)), 'rgba(204,55,0,0.94)');
        tag.visible = true;
    }

    function renderBoard() {
        if (typeof HospitalFloors === 'undefined' || !HospitalFloors.regs || !HospitalFloors.regs.EQP) return;
        const grp = HospitalFloors.regs.EQP.group;
        if (!board) {
            board = sprite(3.4, 1.0, 768, 224); board.position.set(0, 3.35, 0.4); grp.add(board);
            markers = {};
            Object.entries(STATION).forEach(([type, st]) => {
                const key = st[2];
                if (markers[key]) return;
                const m = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.045, 8, 24), new THREE.MeshBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.95, depthTest: false }));
                m.position.set(st[0], 2.05, st[1] + 0.35); m.rotation.x = Math.PI / 2; m.renderOrder = 13; m.visible = false; m.userData.noCollide = true;
                grp.add(m); markers[key] = m;
            });
        }
        const all = list();
        Object.values(markers).forEach(m => { m.visible = false; });
        if (!all.length) { draw(board, ['PARC D\'ÉQUIPEMENTS', 'Tous les appareils des chambres sont en service'], 'rgba(22,101,52,0.92)'); return; }
        const lines = [`${all.length} PANNE${all.length > 1 ? 'S' : ''} EN CHAMBRE — appareil de remplacement ici`];
        all.slice(0, 3).forEach(x => {
            const st = STATION[x.type];
            lines.push(`Ch. ${x.room} · ${x.name} (${x.label})` + (st ? ` → poste ${st[2]} ${st[3]}` : ''));
            if (st && markers[st[2]]) markers[st[2]].visible = true;
        });
        draw(board, lines, 'rgba(204,55,0,0.94)');
    }

    function apply(rs) {
        if (!rs || !rs.room) return;
        faults[rs.room] = rs.deviceFaults || {};
        try { renderRoom(rs.room); renderBoard(); } catch (e) { console.error('[EquipmentFaults]', e); }
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'init') { Object.values(m.room_states || {}).forEach(apply); setTimeout(renderBoard, 2500); }  // la salle Équipements est créée par floors.js après l'init
        else if (m.type === 'room_state') apply(m);
    });
    // repère clignotant sur le poste de remplacement
    setInterval(() => { if (markers) Object.values(markers).forEach(m => { if (m.visible) m.material.opacity = m.material.opacity > 0.6 ? 0.35 : 0.95; }); }, 500);

    return { list, state: () => ({ faults: list(), roomTags: Object.keys(roomTags).filter(r => roomTags[r].visible), board: !!board }) };
})();

window.EquipmentFaults = EquipmentFaults;
