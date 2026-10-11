/**
 * HackCure — équipements animés des chambres (extension additive).
 *  - fenêtre : deux battants qui s'ouvrent vers l'intérieur dans les 4 chambres (la vitre fixe de scene.js est
 *    masquée pendant l'ouverture ; les chambres 103/104, à paroi vitrée, reçoivent un châssis), courant d'air visible ;
 *  - radiateur qui rougeoie, climatiseur avec flux bleu, veilleuse ;
 *  - étiquettes de valeurs sur la potence (perfusion) et le chariot moniteur.
 * Tout est ajouté dans le groupe de la chambre (coordonnées locales : x −4..4, z −3..3).
 */
const Equipment = (() => {
    'use strict';
    const rooms = {};   // room -> parts

    function mat(color, extra) { return new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.7 }, extra || {})); }
    function box(w, h, d, m, x, y, z, parent) { const o = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); o.position.set(x, y, z); parent.add(o); return o; }

    function labelSprite(w, h) {
        const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 96;
        const tex = new THREE.CanvasTexture(canvas);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
        sprite.scale.set(w, h, 1); sprite.renderOrder = 12;
        sprite.userData = { canvas, tex, lines: [] };
        return sprite;
    }
    function drawLabel(sprite, lines, accent) {
        const key = lines.join('|') + accent;
        if (sprite.userData.key === key) return;
        sprite.userData.key = key;
        const c = sprite.userData.canvas, g = c.getContext('2d');
        g.clearRect(0, 0, c.width, c.height);
        g.fillStyle = 'rgba(2,6,23,0.82)'; g.fillRect(0, 0, c.width, c.height);
        g.strokeStyle = accent || 'rgba(56,189,248,0.8)'; g.lineWidth = 3; g.strokeRect(1, 1, c.width - 2, c.height - 2);
        g.textAlign = 'center'; g.textBaseline = 'middle';
        lines.forEach((l, i) => {
            g.fillStyle = i === 0 ? '#e2e8f0' : (accent || '#7dd3fc');
            g.font = (i === 0 ? '600 20px' : 'bold 30px') + ' Inter, sans-serif';
            g.fillText(l, c.width / 2, 24 + i * 40);
        });
        sprite.userData.tex.needsUpdate = true;
    }

    function build(room) {
        const g = HospitalScene.getRoomGroup(room); if (!g) return null;
        const cfg = HospitalScene.getRoomConfig(room) || {};
        const BED = HospitalScene.BED;
        const parts = { room, group: g, t: Math.random() * 10 };
        const topRow = cfg.rotY === 0;

        // Fenêtre : deux battants (charnières aux montants, ouverture vers l'intérieur), dans les 4 chambres
        if (cfg.window) {
            const W = cfg.window, w = (W.x1 - W.x0) / 2, h = W.top - W.sill, cy = W.sill + h / 2, z = -3 + 0.04;
            const sashMat = mat(0xffffff, { roughness: 0.4 });
            const glass = new THREE.MeshStandardMaterial({ color: 0xbfe3ff, transparent: true, opacity: 0.3, roughness: 0.1, depthWrite: false });
            const leaf = (hx, dir) => {            // dir = +1 : battant qui s'étend vers +x depuis sa charnière
                const hinge = new THREE.Group(); hinge.position.set(hx, cy, z); g.add(hinge);
                box(w, 0.06, 0.06, sashMat, dir * w / 2, h / 2 - 0.03, 0, hinge); box(w, 0.06, 0.06, sashMat, dir * w / 2, -h / 2 + 0.03, 0, hinge);
                box(0.06, h, 0.06, sashMat, dir * 0.03, 0, 0, hinge); box(0.06, h, 0.06, sashMat, dir * (w - 0.03), 0, 0, hinge);
                const gl = box(w - 0.12, h - 0.12, 0.02, glass, dir * w / 2, 0, 0, hinge); gl.renderOrder = 3;
                box(0.03, 0.14, 0.05, mat(0x94a3b8, { metalness: 0.6, roughness: 0.3 }), dir * (w - 0.08), 0, 0.05, hinge);   // poignée
                return hinge;
            };
            const left = leaf(W.x0, 1), right = leaf(W.x1, -1);
            if (!topRow) {                          // paroi vitrée : châssis dormant pour matérialiser la fenêtre
                const zf = -3 + 0.01;
                box(2 * w + 0.12, 0.07, 0.08, sashMat, (W.x0 + W.x1) / 2, W.top + 0.035, zf, g); box(2 * w + 0.12, 0.07, 0.08, sashMat, (W.x0 + W.x1) / 2, W.sill - 0.035, zf, g);
                box(0.07, h, 0.08, sashMat, W.x0 - 0.035, cy, zf, g); box(0.07, h, 0.08, sashMat, W.x1 + 0.035, cy, zf, g);
            }
            // courant d'air : filets clairs qui entrent dans la chambre quand la fenêtre est ouverte
            const airMat = new THREE.MeshBasicMaterial({ color: 0xe0f2fe, transparent: true, opacity: 0, depthWrite: false });
            const air = []; for (let i = 0; i < 6; i++) air.push(box(0.5, 0.015, 0.015, airMat, W.x0 + 0.25 + (i % 3) * 0.5, W.sill + 0.25 + (i % 2) * 0.55 + i * 0.07, -2.9, g));
            parts.window = { left, right, air, airMat, pane: g.userData.windowPane || null, open: 0, target: 0 };
        }
        // Radiateur sous la fenêtre (ou contre le mur du fond)
        const radMat = mat(0xe5e7eb, { emissive: 0x000000, emissiveIntensity: 0 });
        const rad = new THREE.Group(); rad.position.set(topRow ? 2.4 : -2.4, 0.32, -2.84); g.add(rad);
        for (let i = 0; i < 8; i++) box(0.09, 0.5, 0.08, radMat, -0.42 + i * 0.12, 0, 0, rad);
        box(1.0, 0.04, 0.1, radMat, 0, 0.27, 0, rad); box(1.0, 0.04, 0.1, radMat, 0, -0.27, 0, rad);
        parts.heater = { mat: radMat, on: false, glow: 0 };
        // Climatiseur mural (au-dessus de la porte côté couloir)
        const acBody = box(0.9, 0.28, 0.24, mat(0xf8fafc, { roughness: 0.5 }), 0.4, 2.62, 2.82, g);
        box(0.8, 0.04, 0.02, mat(0x94a3b8), 0.4, 2.52, 2.69, g);
        const acLed = box(0.05, 0.03, 0.01, new THREE.MeshBasicMaterial({ color: 0x38bdf8 }), 0.78, 2.56, 2.69, g);
        acLed.visible = false;
        const flowMat = new THREE.MeshBasicMaterial({ color: 0x7dd3fc, transparent: true, opacity: 0.0, depthWrite: false });
        const flow = new THREE.Group(); flow.position.set(0.4, 2.45, 2.68); g.add(flow);
        const flowParts = [];
        for (let i = 0; i < 6; i++) { const f = box(0.8 - i * 0.05, 0.02, 0.02, flowMat, 0, -i * 0.09, -i * 0.12, flow); flowParts.push(f); }
        parts.ac = { led: acLed, flowMat, flow, flowParts, on: false, level: 0 };
        // Veilleuse (petite lampe au mur de tête de lit)
        const lampMat = new THREE.MeshBasicMaterial({ color: 0xfde68a, transparent: true, opacity: 0.25 });
        const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), lampMat); lamp.position.set(BED.x - 0.9, 1.9, -2.9); g.add(lamp);
        const light = new THREE.PointLight(0xffd27a, 0.0, 4.5); light.position.set(BED.x - 0.9, 1.9, -2.6); g.add(light);
        parts.light = { lamp, lampMat, light, on: false, level: 0 };
        // Étiquettes : potence (perfusion) et chariot moniteur
        const iv = labelSprite(0.9, 0.34); iv.position.set(BED.x + 0.85, 2.15, BED.z - 0.85); iv.visible = false; g.add(iv);
        const mon = labelSprite(1.0, 0.38); mon.position.set(1.7, 1.85, -2.5); mon.visible = false; g.add(mon);
        parts.ivLabel = iv; parts.monLabel = mon;
        return parts;
    }

    function get(room) { if (!rooms[room]) { const p = build(room); if (!p) return null; rooms[room] = p; } return rooms[room]; }

    function setState(room, eq) {
        const p = get(room); if (!p || !eq) return;
        if (p.window) p.window.target = eq.window === 'open' ? 1 : 0;
        p.heater.on = eq.heater === 'on';
        p.ac.on = eq.ac === 'on'; p.ac.led.visible = p.ac.on;
        p.light.on = eq.light === 'on';
    }

    function setIV(room, volumeLeftMl, rateMlH, occlusion) {
        const p = get(room); if (!p) return;
        if (volumeLeftMl == null) { p.ivLabel.visible = false; return; }
        p.ivLabel.visible = true;
        const warn = occlusion || volumeLeftMl < 50;
        drawLabel(p.ivLabel, [occlusion ? 'PERFUSION · OCCLUSION' : `Perfusion ${rateMlH != null ? rateMlH + ' ml/h' : ''}`, `${Math.round(volumeLeftMl)} ml`], warn ? '#f87171' : '#7dd3fc');
    }

    function setMonitor(room, v) {
        const p = get(room); if (!p) return;
        if (!v || v.hr == null) { p.monLabel.visible = false; return; }
        p.monLabel.visible = true;
        const bp = (v.sys != null && v.dia != null) ? `${Math.round(v.sys)}/${Math.round(v.dia)}` : '—';
        const alarm = (v.hr > 120 || v.hr < 45 || (v.spo2 != null && v.spo2 < 90) || (v.sys != null && v.sys < 90));
        drawLabel(p.monLabel, [`FC ${Math.round(v.hr)} · SpO2 ${v.spo2 != null ? Math.round(v.spo2) + '%' : '—'}`, `PA ${bp}${v.tempC != null ? ' · ' + Number(v.tempC).toFixed(1) + '°' : ''}`], alarm ? '#f87171' : '#86efac');
    }

    function update(delta) {
        const k = 1 - Math.exp(-4 * Math.min(delta, 0.1));
        Object.values(rooms).forEach(p => {
            p.t += delta;
            if (p.window) {
                const w = p.window; w.open += (w.target - w.open) * k;
                w.left.rotation.y = -w.open * 1.25; w.right.rotation.y = w.open * 1.25;      // vers l'intérieur de la chambre
                if (w.pane) w.pane.visible = w.open < 0.03;                                  // baie réellement ouverte
                w.airMat.opacity = w.open * 0.55;
                w.air.forEach((a, i) => { const u = (p.t * 0.45 + i * 0.17) % 1; a.position.z = -2.9 + u * 1.1; a.rotation.y = Math.sin(p.t * 2 + i) * 0.25; });
            }
            const h = p.heater; h.glow += ((h.on ? 1 : 0) - h.glow) * k;
            h.mat.emissive.setHex(0xff3b1f); h.mat.emissiveIntensity = h.glow * (0.55 + 0.15 * Math.sin(p.t * 3));
            const a = p.ac; a.level += ((a.on ? 1 : 0) - a.level) * k;
            a.flowMat.opacity = a.level * 0.45;
            a.flowParts.forEach((f, i) => { f.position.z = -((p.t * 0.6 + i * 0.12) % 0.72); f.position.y = -((p.t * 0.6 + i * 0.12) % 0.72) * 0.75; });
            const l = p.light; l.level += ((l.on ? 1 : 0) - l.level) * k;
            l.lampMat.opacity = 0.25 + l.level * 0.75; l.light.intensity = l.level * 0.9;
        });
    }

    function windowOpen(room) { const p = rooms[room]; return p && p.window ? p.window.open : null; }
    return { setState, setIV, setMonitor, update, get, windowOpen };
})();

window.StaffAvatars = StaffAvatars; window.Equipment = Equipment;
