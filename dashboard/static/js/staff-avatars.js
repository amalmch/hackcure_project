/**
 * HackCure — avatars du personnel — extension additive.
 * Un avatar apparaît près du lit quand `persons > 1` (room_state.staffPresent). Sa tenue et son étiquette
 * suivent `room_state.staffRole` : infirmier (tenue bleu-vert), médecin (blouse blanche), psychiatre…
 */
const StaffAvatars = (() => {
    'use strict';
    const staff = {};   // room -> { group, parts, visible, target }
    const COLORS = { scrubs: 0x14b8a6, scrubsDark: 0x0f766e, skin: 0xd9a98a, hair: 0x3f3f46, shoe: 0xf8fafc };
    // rôle → tenue (haut, bas), coiffe d'infirmier, étiquette
    const ROLES = {
        nurse: { top: 0x14b8a6, bottom: 0x0f766e, cap: true, label: 'Infirmier(ère)', accent: 'rgba(20,184,166,0.9)', text: '#ccfbf1' },
        duty_doctor: { top: 0xffffff, bottom: 0x334155, cap: false, label: 'Médecin de garde', accent: 'rgba(96,165,250,0.95)', text: '#dbeafe' },
        general_doctor: { top: 0xffffff, bottom: 0x334155, cap: false, label: 'Médecin', accent: 'rgba(96,165,250,0.95)', text: '#dbeafe' },
        psychiatrist: { top: 0xede9fe, bottom: 0x4c1d95, cap: false, label: 'Psychiatre', accent: 'rgba(167,139,250,0.95)', text: '#ede9fe' },
        pharmacist: { top: 0xdcfce7, bottom: 0x166534, cap: false, label: 'Pharmacien', accent: 'rgba(74,222,128,0.95)', text: '#dcfce7' },
        paramedic: { top: 0xf97316, bottom: 0x1e293b, cap: false, label: 'Ambulancier', accent: 'rgba(249,115,22,0.95)', text: '#ffedd5' },
    };

    function drawLabel(s, role) {
        const r = ROLES[role] || ROLES.nurse, c = s.canvas, ctx = c.getContext('2d');
        ctx.clearRect(0, 0, c.width, c.height);
        ctx.fillStyle = 'rgba(15,23,42,0.88)'; ctx.fillRect(0, 0, c.width, c.height);
        ctx.strokeStyle = r.accent; ctx.lineWidth = 3; ctx.strokeRect(1, 1, c.width - 2, c.height - 2);
        ctx.fillStyle = r.text; ctx.font = 'bold 24px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(r.label, c.width / 2, c.height / 2);
        s.label.material.map.needsUpdate = true;
    }

    function applyRole(s, role) {
        role = ROLES[role] ? role : 'nurse';
        if (s.role === role) return;
        s.role = role;
        const r = ROLES[role];
        s.mats.top.color.setHex(r.top); s.mats.bottom.color.setHex(r.bottom);
        s.cap.visible = r.cap; s.coat.visible = !r.cap;
        drawLabel(s, role);
    }

    function mk(geo, mat, parent, x, y, z) { const m = new THREE.Mesh(geo, mat); m.position.set(x || 0, y || 0, z || 0); m.castShadow = true; parent.add(m); return m; }

    function build(room) {
        const scene = HospitalScene.getScene(); if (!scene) return null;
        const bp = HospitalScene.getBedWorldPosition(room);
        const group = new THREE.Group();
        group.position.set(bp.x, 0, bp.z); group.rotation.y = bp.rotY;
        const body = new THREE.Group(); group.add(body);
        // position lit-locale : côté libre du lit, près de la tête, tourné vers le patient
        body.position.set(1.15, 0, -0.75); body.rotation.y = Math.PI / 2 + 0.6;

        const scrubs = new THREE.MeshStandardMaterial({ color: COLORS.scrubs, roughness: 0.85 });
        const dark = new THREE.MeshStandardMaterial({ color: COLORS.scrubsDark, roughness: 0.9 });
        const skin = new THREE.MeshStandardMaterial({ color: COLORS.skin, roughness: 0.6 });
        const hair = new THREE.MeshStandardMaterial({ color: COLORS.hair, roughness: 0.9 });
        const white = new THREE.MeshStandardMaterial({ color: COLORS.shoe, roughness: 0.6 });

        const pelvis = mk(new THREE.BoxGeometry(0.34, 0.18, 0.2), dark, body, 0, 1.0, 0);
        const torso = new THREE.Group(); torso.position.y = 0.09; pelvis.add(torso);
        const chest = mk(new THREE.CylinderGeometry(0.2, 0.18, 0.58, 18), scrubs, torso, 0, 0.3, 0); chest.scale.z = 0.62;
        // badge + poche
        mk(new THREE.BoxGeometry(0.08, 0.05, 0.01), white, torso, -0.09, 0.42, 0.13);
        const neck = new THREE.Group(); neck.position.y = 0.58; torso.add(neck);
        mk(new THREE.CylinderGeometry(0.05, 0.06, 0.08, 10), skin, neck, 0, 0.03, 0);
        const head = mk(new THREE.SphereGeometry(0.135, 22, 16), skin, neck, 0, 0.18, 0.01);
        const cap = mk(new THREE.SphereGeometry(0.145, 22, 12, 0, Math.PI * 2, 0, Math.PI * 0.5), scrubs, neck, 0, 0.2, -0.005);
        cap.rotation.x = -0.2;
        // blouse longue (médecins) : pan qui descend sous le bassin + stéthoscope
        const coat = new THREE.Group(); torso.add(coat); coat.visible = false;
        const skirt = mk(new THREE.CylinderGeometry(0.19, 0.22, 0.42, 18), scrubs, coat, 0, -0.2, 0); skirt.scale.z = 0.66;
        const steth = mk(new THREE.TorusGeometry(0.1, 0.012, 8, 20, Math.PI), new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.5 }), coat, 0, 0.5, 0.1); steth.rotation.z = Math.PI;
        mk(new THREE.SphereGeometry(0.14, 16, 10, 0, Math.PI * 2, 0, Math.PI * 0.45), hair, neck, 0, 0.17, -0.03);
        [-0.05, 0.05].forEach(x => mk(new THREE.SphereGeometry(0.013, 8, 6), new THREE.MeshBasicMaterial({ color: 0x1f2937 }), neck, x, 0.2, 0.13));
        const arms = {};
        [-1, 1].forEach(side => {
            const sh = new THREE.Group(); sh.position.set(side * 0.24, 0.5, 0); torso.add(sh);
            mk(new THREE.CylinderGeometry(0.055, 0.045, 0.33, 12), scrubs, sh, 0, -0.165, 0);
            const el = new THREE.Group(); el.position.y = -0.33; sh.add(el);
            mk(new THREE.CylinderGeometry(0.045, 0.04, 0.3, 12), skin, el, 0, -0.15, 0);
            mk(new THREE.SphereGeometry(0.04, 10, 8), skin, el, 0, -0.32, 0);
            sh.rotation.x = -0.9; el.rotation.x = -0.9; sh.rotation.z = side * -0.15;
            arms[side] = { sh, el };
        });
        [-1, 1].forEach(side => {
            const hip = new THREE.Group(); hip.position.set(side * 0.11, -0.09, 0); pelvis.add(hip);
            mk(new THREE.CylinderGeometry(0.085, 0.07, 0.45, 12), dark, hip, 0, -0.225, 0);
            const knee = new THREE.Group(); knee.position.y = -0.45; hip.add(knee);
            mk(new THREE.CylinderGeometry(0.065, 0.05, 0.42, 12), dark, knee, 0, -0.21, 0);
            mk(new THREE.BoxGeometry(0.11, 0.07, 0.2), white, knee, 0, -0.44, 0.05);
        });
        // étiquette
        const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 64;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'rgba(15,23,42,0.85)'; ctx.fillRect(0, 0, 256, 64);
        ctx.strokeStyle = 'rgba(20,184,166,0.8)'; ctx.lineWidth = 2; ctx.strokeRect(0, 0, 256, 64);
        ctx.fillStyle = '#ccfbf1'; ctx.font = 'bold 24px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('Infirmier(ère)', 128, 32);
        const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false }));
        label.scale.set(1.3, 0.325, 1); label.position.set(1.15, 2.45, -0.75); label.renderOrder = 10; group.add(label);

        group.visible = false; group.scale.set(0.001, 0.001, 0.001);
        scene.add(group);
        return { group, body, head, arms, label, canvas, cap, coat, mats: { top: scrubs, bottom: dark }, role: 'nurse', visible: false, t: Math.random() * 10 };
    }

    function setPresent(room, present, count, role) {
        let s = staff[room];
        if (!s) { s = build(room); if (!s) return; staff[room] = s; }
        if (present) applyRole(s, role || 'nurse');
        s.visible = !!present;
        if (present) s.group.visible = true;
        if (s.label.userData.count !== count) {
            s.label.userData.count = count;
        }
    }

    function update(delta) {
        const k = 1 - Math.exp(-5 * Math.min(delta, 0.1));
        Object.values(staff).forEach(s => {
            const target = s.visible ? 1 : 0.001;
            const cur = s.group.scale.x;
            const n = cur + (target - cur) * k;
            s.group.scale.set(n, n, n);
            if (!s.visible && n < 0.01) s.group.visible = false;
            if (s.visible) {
                s.t += delta;
                s.body.position.y = Math.sin(s.t * 1.6) * 0.012;     // respiration
                s.body.rotation.y = Math.PI / 2 + 0.6 + Math.sin(s.t * 0.7) * 0.08;
                s.arms[1].sh.rotation.x = -0.9 + Math.sin(s.t * 1.3) * 0.15;  // geste de soin
            }
        });
    }

    function isPresent(room) { return !!(staff[room] && staff[room].visible); }
    function roleOf(room) { return staff[room] && staff[room].visible ? staff[room].role : null; }
    return { setPresent, update, isPresent, roleOf, ROLES };
})();
