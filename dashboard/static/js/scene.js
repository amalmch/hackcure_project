/**
 * HackCure — Hospital Ward (rebuilt)
 * ===================================
 * Four identical patient rooms (2 top, 2 bottom) off a central corridor.
 * Every room is built in ONE local frame and then placed/rotated as a unit,
 * so beds, avatars, curtains, doors and the CCTV view can never drift apart.
 *
 * Room-local frame (x: -4..4, z: -3..3)
 *   -z = headwall side (outer wall)   +z = corridor side (door)
 * Bed-local frame (used by avatars.js): head at -z, foot at +z, centred on the bed.
 *
 * Look: white + clear-blue ward with patterned tile floor, headwall rail with
 * outlets/gas/suction, ceiling-track curtains, IV pole, nightstand, monitor
 * trolley, overbed table, blue armchair, ICU glass partition to the corridor.
 */

const HospitalScene = (() => {
    let scene, camera, renderer, controls, container, animationId;
    let camTween = null;
    let lastMonitorDraw = 0, lastVitalsSync = 0;
    const textures = {};
    const roomGroups = {};
    const bedParts = {};
    const monitors = [];
    let MAT = {};

    // ─── Layout ────────────────────────────────────────────
    const ROOM_W = 8, ROOM_D = 6, WALL_H = 3.0, WALL_T = 0.16;
    const ROOMS = {
        '101': { x: -4, z: -5, rotY: 0 },
        '102': { x: 4, z: -5, rotY: 0 },
        '103': { x: -4, z: 5, rotY: Math.PI },
        '104': { x: 4, z: 5, rotY: Math.PI },
    };
    // Bed centre in room-local coordinates + bed geometry shared with avatars.js
    const BED = { x: -1.2, z: -1.85, deckY: 0.8, hingeZ: -0.25, backAngle: Math.PI / 6 };
    const DOOR = { x: 2.6, w: 1.3, h: 2.1 };
    const WINDOW = { x0: 1.6, x1: 3.2, sill: 0.95, top: 2.35 };
    const CCTV_LOCAL = { x: 0.6, y: 2.7, z: 2.65 };
    // Reception wing attached to the WEST end of the corridor. D = interior depth in metres.
    // Hall interior is x: -(8.16 + D) .. -8.16, z: -8 .. 8. The west garden is pushed out by D.
    const REC = { D: 10 };
    REC.cx = -(8 + WALL_T + REC.D / 2);   // world x of the hall centre (-13.16 for D = 10)

    const CAMERA_POSITIONS = {
        overview: { pos: [-REC.D / 2, 28, 19.5], target: [-REC.D / 2, 0, 0], fov: 45 },
        topdown: { pos: [-REC.D / 2, 38, 0.1], target: [-REC.D / 2, 0, 0], fov: 45 },
    };

    // ─── Small builders ────────────────────────────────────
    function mesh(geo, m, x, y, z, parent, shadow = true) {
        const o = new THREE.Mesh(geo, m);
        o.position.set(x || 0, y || 0, z || 0);
        o.castShadow = shadow; o.receiveShadow = true;
        if (parent) parent.add(o);
        return o;
    }
    const B = (w, h, d, m, x, y, z, p, s) => mesh(new THREE.BoxGeometry(w, h, d), m, x, y, z, p, s);
    const C = (r, h, m, x, y, z, p, seg = 16) => mesh(new THREE.CylinderGeometry(r, r, h, seg), m, x, y, z, p);
    function tube(len, r, axis, m, x, y, z, p) {
        const g = new THREE.CylinderGeometry(r, r, len, 10);
        if (axis === 'z') g.rotateX(Math.PI / 2);
        if (axis === 'x') g.rotateZ(Math.PI / 2);
        return mesh(g, m, x, y, z, p);
    }
    function rbox(w, h, d, r, m, x, y, z, p) {
        const s = new THREE.Shape(), hw = w / 2, hh = h / 2;
        s.moveTo(-hw + r, -hh); s.lineTo(hw - r, -hh); s.quadraticCurveTo(hw, -hh, hw, -hh + r);
        s.lineTo(hw, hh - r); s.quadraticCurveTo(hw, hh, hw - r, hh); s.lineTo(-hw + r, hh);
        s.quadraticCurveTo(-hw, hh, -hw, hh - r); s.lineTo(-hw, -hh + r); s.quadraticCurveTo(-hw, -hh, -hw + r, -hh);
        const g = new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false, curveSegments: 6 });
        g.translate(0, 0, -d / 2);
        return mesh(g, m, x, y, z, p);
    }
    const std = (color, o = {}) => new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.55, metalness: 0 }, o));

    function canvasTex(w, h, draw) {
        const c = document.createElement('canvas'); c.width = w; c.height = h;
        const g = c.getContext('2d'); draw(g, w, h);
        const t = new THREE.CanvasTexture(c); t.encoding = THREE.sRGBEncoding;
        return t;
    }

    // ─── Materials & textures ──────────────────────────────
    function buildMaterials() {
        MAT = {
            wall: std(0xf3f6fa, { roughness: 0.9 }),
            base: std(0x2d8fe5),
            white: std(0xf7f9fc, { roughness: 0.35 }),
            accent: std(0x2d8fe5, { roughness: 0.5 }),
            accentDark: std(0x1f6fb8),
            steel: std(0xc9d2db, { metalness: 0.8, roughness: 0.3 }),
            dark: std(0x2a3440, { roughness: 0.5 }),
            black: new THREE.MeshBasicMaterial({ color: 0x05080c }),
            sheet: std(0xf2f6fa, { roughness: 0.9 }),
            blanket: std(0x3b82d6, { roughness: 0.95 }),
            curtain: std(0x4aa3e0, { roughness: 0.95, side: THREE.DoubleSide }),
            glass: new THREE.MeshStandardMaterial({ color: 0xbfe3ff, transparent: true, opacity: 0.22, roughness: 0.05, depthWrite: false }),
            bag: new THREE.MeshStandardMaterial({ color: 0xe6f6ff, transparent: true, opacity: 0.75, roughness: 0.2 }),
            wood: std(0xb98e5f, { roughness: 0.7 }),
            red: std(0xdc2626),
            green: std(0x16a34a),
            yellow: std(0xeab308),
            slab: std(0x1e293b, { roughness: 1 }),
            concrete: std(0xcfd4d9, { roughness: 0.95 }),
            coping: std(0xe4e8ed, { roughness: 0.6 }),
            mirror: new THREE.MeshStandardMaterial({ color: 0xe8f1f8, roughness: 0.03, metalness: 0.95 }),
            screenFrame: std(0x0b1018, { roughness: 0.3 }),
            railWood: std(0xd9b98b, { roughness: 0.6 }),
            chairBlue: std(0x2d8fe5, { roughness: 0.9 }),
        };
    }

    function buildTextures() {
        // Blue geometric tile (image 2): 2x2 tiles per texture, each tile 0.6 m
        textures.room = canvasTex(512, 512, (g) => {
            g.fillStyle = '#eef5fb'; g.fillRect(0, 0, 512, 512);
            for (let tx = 0; tx < 2; tx++) for (let ty = 0; ty < 2; ty++) {
                const ox = tx * 256, oy = ty * 256, cx = ox + 128, cy = oy + 128;
                g.strokeStyle = '#a9cdee'; g.lineWidth = 7;
                [0, Math.PI / 4].forEach(r => { g.save(); g.translate(cx, cy); g.rotate(r); g.strokeRect(-70, -70, 140, 140); g.restore(); });
                g.strokeStyle = '#cfe3f5'; g.lineWidth = 5; g.beginPath(); g.arc(cx, cy, 104, 0, Math.PI * 2); g.stroke();
                g.fillStyle = '#bcd9f1';
                [[ox, oy], [ox + 256, oy], [ox, oy + 256], [ox + 256, oy + 256]].forEach(([x, y]) => { g.beginPath(); g.arc(x, y, 20, 0, Math.PI * 2); g.fill(); });
                g.strokeStyle = '#d3dce5'; g.lineWidth = 3; g.strokeRect(ox, oy, 256, 256);
            }
        });
        textures.corridor = canvasTex(512, 512, (g) => {
            g.fillStyle = '#e9e7e1'; g.fillRect(0, 0, 512, 512);
            g.strokeStyle = '#cdcac2'; g.lineWidth = 4;
            for (let i = 0; i <= 512; i += 256) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 512); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(512, i); g.stroke(); }
            for (let i = 0; i < 3000; i++) { g.fillStyle = 'rgba(0,0,0,0.025)'; g.fillRect(Math.random() * 512, Math.random() * 512, 2, 2); }
        });
        textures.lobby = canvasTex(512, 512, (g) => {
            g.fillStyle = '#eceff2'; g.fillRect(0, 0, 512, 512);
            g.strokeStyle = '#c7ced6'; g.lineWidth = 4;
            for (let i = 0; i <= 512; i += 256) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 512); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(512, i); g.stroke(); }
            g.fillStyle = '#d6e6f5';
            for (let x = 0; x <= 512; x += 256) for (let y = 0; y <= 512; y += 256) g.fillRect(x - 10, y - 10, 20, 20);
            for (let i = 0; i < 2500; i++) { g.fillStyle = 'rgba(0,0,0,0.02)'; g.fillRect(Math.random() * 512, Math.random() * 512, 2, 2); }
        });
        [textures.room, textures.corridor, textures.lobby].forEach(t => { t.wrapS = t.wrapT = THREE.RepeatWrapping; });
    }

    function tiledMat(tex, w, d, tile, rough) {
        const t = tex.clone(); t.needsUpdate = true;
        t.wrapS = t.wrapT = THREE.RepeatWrapping; t.encoding = THREE.sRGBEncoding;
        t.repeat.set(w / tile, d / tile);
        return new THREE.MeshStandardMaterial({ map: t, roughness: rough });
    }

    // ─── Walls (built along local x, centred on z = zc) ───
    function buildWallX(parent, x0, x1, zc, openings, glassStyle, inner) {
        const solid = (a, b, y0, y1) => { if (b - a > 0.001 && y1 - y0 > 0.001) B(b - a, y1 - y0, WALL_T, MAT.wall, (a + b) / 2, (y0 + y1) / 2, zc, parent); };
        const glass = (a, b, y0, y1) => { const g = B(b - a, y1 - y0, 0.03, MAT.glass, (a + b) / 2, (y0 + y1) / 2, zc, parent, false); g.renderOrder = 2; };
        const full = (a, b) => {
            if (b - a <= 0.001) return;
            if (!glassStyle) solid(a, b, 0, WALL_H);
            else {
                solid(a, b, 0, 0.9); glass(a, b, 0.9, 2.3); solid(a, b, 2.3, WALL_H);
                for (let x = Math.ceil((a + 0.1) / 1.0) * 1.0; x < b - 0.1; x += 1.0) B(0.05, 1.4, 0.07, MAT.white, x, 1.6, zc, parent, false);
            }
            B(b - a, 0.12, 0.02, MAT.base, (a + b) / 2, 0.06, zc + inner * (WALL_T / 2 + 0.01), parent, false);
        };
        let cur = x0;
        openings.slice().sort((a, b) => a.x0 - b.x0).forEach(o => {
            full(cur, o.x0);
            solid(o.x0, o.x1, o.top, WALL_H);
            if (o.sill > 0) solid(o.x0, o.x1, 0, o.sill);
            cur = o.x1;
        });
        full(cur, x1);
        B(x1 - x0, 0.05, WALL_T + 0.05, MAT.coping, (x0 + x1) / 2, WALL_H + 0.025, zc, parent, false);   // wall cap
    }

    function pleats(parent, ax, az, bx, bz, y0, y1, folds, amp, mat) {
        // Pleated curtain ribbon from (ax,az) to (bx,bz)
        const N = Math.max(12, folds * 8);
        const dx = bx - ax, dz = bz - az, len = Math.hypot(dx, dz);
        const nx = -dz / len, nz = dx / len;
        const pos = [], idx = [];
        for (let i = 0; i <= N; i++) {
            const t = i / N, off = Math.sin(t * folds * Math.PI * 2) * amp;
            const x = ax + dx * t + nx * off, z = az + dz * t + nz * off;
            pos.push(x, y0, z, x, y1, z);
            if (i < N) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
        g.setIndex(idx); g.computeVertexNormals();
        const m = new THREE.Mesh(g, mat); m.castShadow = true; m.receiveShadow = true;
        parent.add(m); return m;
    }

    // ─── Animated vital-signs screens ──────────────────────
    const gauss = (p, mu, s, a) => a * Math.exp(-Math.pow((p - mu) / s, 2));
    const phase = (t, hr) => { const per = 60 / hr; return (((t % per) + per) % per) / per; };
    const ecg = (t, hr) => { const p = phase(t, hr); return gauss(p, .12, .035, .12) + gauss(p, .2, .012, -.12) + gauss(p, .22, .014, 1) + gauss(p, .25, .014, -.25) + gauss(p, .42, .05, .22); };
    const pleth = (t, hr) => { const p = phase(t, hr); return gauss(p, .2, .09, .9) + gauss(p, .5, .1, .3) - .25; };
    const resp = (t) => Math.sin(t * 1.6) * .8;

    function makeMonitor(room) {
        const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 128;
        const tex = new THREE.CanvasTexture(canvas); tex.encoding = THREE.sRGBEncoding;
        const m = { canvas, ctx: canvas.getContext('2d'), tex, room, hr: 72, targetHr: 72, spo2: 98, bp: '120/80', alarm: false };
        monitors.push(m); drawMonitor(m, 0); return m;
    }
    function drawMonitor(m, t) {
        const g = m.ctx, W = 256, plotW = 168;
        g.fillStyle = '#03101a'; g.fillRect(0, 0, W, 128);
        g.fillStyle = m.alarm ? '#b91c1c' : '#0e3a52'; g.fillRect(0, 0, W, 18);
        g.fillStyle = '#fff'; g.font = 'bold 12px sans-serif'; g.textBaseline = 'middle'; g.textAlign = 'left';
        g.fillText((m.alarm ? 'ALARM  ' : '') + 'ROOM ' + m.room, 8, 9);
        [{ y: 50, c: '#22ff7a', a: 20, f: ecg }, { y: 84, c: '#38bdf8', a: 13, f: pleth }, { y: 114, c: '#facc15', a: 8, f: resp }].forEach(r => {
            g.strokeStyle = r.c; g.lineWidth = 2; g.beginPath();
            for (let x = 0; x <= plotW; x += 2) {
                const v = r.f(t - (plotW - x) / 55, m.hr), y = r.y - v * r.a;
                x === 0 ? g.moveTo(x, y) : g.lineTo(x, y);
            }
            g.stroke();
        });
        g.fillStyle = '#22ff7a'; g.font = 'bold 32px sans-serif'; g.fillText(String(Math.round(m.hr)), 180, 46);
        g.fillStyle = '#38bdf8'; g.font = 'bold 24px sans-serif'; g.fillText(Math.round(m.spo2) + '%', 180, 82);
        g.fillStyle = '#e2e8f0'; g.font = 'bold 15px sans-serif'; g.fillText(m.bp, 180, 112);
    }
    function screenMesh(w, h, m, x, y, z, parent) {
        const s = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: m.tex }));
        s.position.set(x, y, z); parent.add(s); return s;
    }

    function syncVitals() {
        if (typeof PatientStateManager === 'undefined') return;
        const list = PatientStateManager.getPatientList();
        const vit = {
            normal: [72, 98, '120/80'], pain_detected: [112, 95, '146/92'],
            fall_detected: [124, 93, '98/60'], fall_and_pain: [136, 90, '88/52'],
        };
        monitors.forEach(m => {
            const p = list.find(q => q.room === m.room);
            const v = vit[(p && p.state) || 'normal'] || vit.normal;
            m.targetHr = v[0]; m.spo2 = v[1]; m.bp = v[2];
            m.alarm = !!p && p.state !== 'normal' && p.state !== undefined;
        });
    }

    // ─── Furniture ─────────────────────────────────────────
    function buildBed(room, id) {
        const bed = new THREE.Group();
        const { deckY, hingeZ, backAngle } = BED;

        // chassis + casters
        B(0.7, 0.18, 1.7, MAT.white, 0, 0.3, 0, bed);
        B(1.0, 0.07, 2.2, MAT.steel, 0, deckY - 0.17, 0, bed);
        [[-0.38, -0.85], [0.38, -0.85], [-0.38, 0.85], [0.38, 0.85]].forEach(([x, z]) => {
            const w = C(0.07, 0.05, MAT.dark, x, 0.07, z, bed, 12); w.rotation.z = Math.PI / 2;
            B(0.04, 0.12, 0.04, MAT.dark, x, 0.17, z, bed);
        });
        // foot mattress section + sheet
        B(0.92, 0.16, 1.3, MAT.sheet, 0, deckY - 0.08, 0.4, bed);

        // raisable backrest (hinged)
        const backrest = new THREE.Group();
        backrest.position.set(0, deckY - 0.08, hingeZ);
        backrest.rotation.x = backAngle;
        B(0.92, 0.16, 0.95, MAT.sheet, 0, 0, -0.475, backrest);
        rbox(0.5, 0.08, 0.32, 0.035, MAT.white, 0, 0.12, -0.74, backrest);   // pillow (thin, head rests on it)
        bed.add(backrest);

        // head / foot boards (white shell + blue insert, like image 2)
        const board = (z, h, ins) => {
            rbox(1.04, h, 0.07, 0.1, MAT.white, 0, 0.42 + h / 2, z, bed);
            rbox(0.82, ins, 0.02, 0.07, MAT.accent, 0, 0.42 + h / 2, z + Math.sign(z) * 0.04, bed);
        };
        board(-1.13, 0.72, 0.4);
        board(1.13, 0.52, 0.34);

        // side rails
        [-0.54, 0.54].forEach(x => {
            tube(1.0, 0.025, 'z', MAT.white, x, deckY + 0.36, -0.2, bed);
            tube(1.0, 0.02, 'z', MAT.white, x, deckY + 0.14, -0.2, bed);
            for (let z = -0.65; z <= 0.26; z += 0.23) C(0.014, 0.22, MAT.steel, x, deckY + 0.25, z, bed, 6);
            C(0.03, 0.4, MAT.white, x, deckY + 0.2, -0.7, bed, 8);
            C(0.03, 0.4, MAT.white, x, deckY + 0.2, 0.3, bed, 8);
        });

        // blanket: origin at the foot end so avatars can bunch it by scaling z
        const bg = new THREE.BoxGeometry(1.04, 0.24, 1.1); bg.translate(0, 0, -0.55);
        const blanket = mesh(bg, MAT.blanket, 0, deckY + 0.12, 1.06, bed);
        const fold = B(1.05, 0.26, 0.1, MAT.sheet, 0, 0, -1.1 + 0.05, blanket); // turned-down edge

        bed.position.set(BED.x, 0, BED.z);
        room.add(bed);
        bedParts[id] = { group: bed, backrest, blanket };
    }

    function buildHeadwall(room, id) {
        const z = -3 + 0.045, cx = BED.x;
        B(5.0, 0.55, 0.09, MAT.white, cx, 1.28, z, room);
        B(5.0, 0.12, 0.095, MAT.accent, cx, 1.5, z, room);               // blue band
        for (let i = 0; i < 4; i++) {                                       // power outlets
            B(0.1, 0.1, 0.03, MAT.white, cx - 1.7 + i * 0.28, 1.25, z + 0.06, room);
            B(0.045, 0.045, 0.02, MAT.black, cx - 1.7 + i * 0.28, 1.25, z + 0.08, room, false);
        }
        const gas = (x, m) => { const c = C(0.045, 0.04, m, x, 1.25, z + 0.07, room, 16); c.rotation.x = Math.PI / 2; };
        gas(cx + 0.2, MAT.green); gas(cx + 0.45, MAT.yellow); gas(cx + 0.7, MAT.white);
        [cx + 1.4, cx + 1.75].forEach(x => {                                 // suction bottles
            C(0.065, 0.2, MAT.sheet, x, 1.2, z + 0.12, room, 14);
            C(0.07, 0.04, MAT.accent, x, 1.33, z + 0.12, room, 14);
        });
        const call = C(0.04, 0.03, MAT.red, cx - 0.55, 1.25, z + 0.07, room, 12); call.rotation.x = Math.PI / 2;
        // reading lamp over bed
        B(0.04, 0.04, 0.3, MAT.steel, cx, 1.95, z + 0.17, room);
        const hood = B(0.6, 0.06, 0.16, MAT.white, cx, 1.93, z + 0.34, room);
        B(0.54, 0.01, 0.1, new THREE.MeshBasicMaterial({ color: 0xfff6dc }), cx, 1.895, z + 0.34, room, false);
        // intercom unit with handset (image 2)
        const ix = cx - 3.05;
        B(0.36, 0.3, 0.05, MAT.white, ix, 1.45, -3 + 0.03, room);
        B(0.24, 0.16, 0.01, std(0x0b5fa8, { emissive: 0x0b5fa8, emissiveIntensity: 0.6 }), ix - 0.03, 1.5, -3 + 0.06, room, false);
        [0, 1, 2].forEach(i => C(0.014, 0.01, MAT.accent, ix + 0.14, 1.55 - i * 0.05, -3 + 0.06, room, 8).rotation.x = Math.PI / 2);
        tube(0.5, 0.012, 'y', MAT.white, ix - 0.1, 1.12, -3 + 0.06, room);
    }

    function buildNightstand(room) {
        const g = new THREE.Group();
        B(0.5, 0.8, 0.48, MAT.white, 0, 0.5, 0, g);
        B(0.44, 0.14, 0.02, MAT.accent, 0, 0.78, 0.245, g, false);
        B(0.44, 0.4, 0.02, MAT.accent, 0, 0.45, 0.245, g, false);
        B(0.16, 0.015, 0.02, MAT.steel, 0, 0.78, 0.265, g, false);
        B(0.015, 0.14, 0.02, MAT.steel, 0.17, 0.5, 0.265, g, false);
        [[-0.2, -0.18], [0.2, -0.18], [-0.2, 0.18], [0.2, 0.18]].forEach(([x, z]) => { C(0.04, 0.04, MAT.dark, x, 0.06, z, g, 8); B(0.03, 0.08, 0.03, MAT.dark, x, 0.12, z, g); });
        C(0.05, 0.16, MAT.bag, -0.1, 0.98, 0, g, 12);        // water jug
        C(0.035, 0.07, MAT.white, 0.1, 0.935, 0.05, g, 12);  // cup
        g.position.set(-2.45, 0, -2.68); g.rotation.y = Math.PI / 2; room.add(g);
    }

    function buildIVPole(room) {
        const g = new THREE.Group();
        C(0.28, 0.03, MAT.steel, 0, 0.03, 0, g, 20);
        for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2 + Math.PI / 4; B(0.3, 0.025, 0.04, MAT.steel, Math.cos(a) * 0.14, 0.05, Math.sin(a) * 0.14, g).rotation.y = -a; }
        C(0.014, 2.1, MAT.steel, 0, 1.08, 0, g, 8);
        B(0.5, 0.025, 0.025, MAT.steel, 0, 2.12, 0, g);
        [-0.2, 0.2].forEach(x => {
            const bag = C(0.065, 0.24, MAT.bag, x, 1.95, 0, g, 14);
            B(0.05, 0.05, 0.05, MAT.accent, x, 1.8, 0, g, false);
            C(0.004, 0.55, MAT.bag, x * 0.8, 1.5, 0, g, 5);
        });
        g.position.set(BED.x + 0.85, 0, BED.z - 0.85); room.add(g);
    }

    function buildMonitorTrolley(room, id) {
        const g = new THREE.Group();
        C(0.28, 0.03, MAT.dark, 0, 0.05, 0, g, 6);
        C(0.025, 1.0, MAT.steel, 0, 0.55, 0, g, 8);
        B(0.5, 0.025, 0.28, MAT.white, 0, 0.78, 0.08, g);      // keyboard shelf
        B(0.4, 0.015, 0.12, MAT.dark, 0, 0.8, 0.1, g, false);
        B(0.54, 0.4, 0.05, MAT.white, 0, 1.28, 0, g);
        screenMesh(0.48, 0.3, makeMonitor(id), 0, 1.28, 0.03, g);
        g.position.set(1.7, 0, -2.5);
        g.rotation.y = Math.atan2(BED.x - 1.7, BED.z + 0.5 - -2.5);
        room.add(g);
    }

    function buildOverbedTable(room) {
        const x = BED.x - 1.5;
        B(0.12, 0.05, 0.7, MAT.white, x, 0.08, BED.z + 0.6, room);
        C(0.025, 0.85, MAT.steel, x, 0.5, BED.z + 0.6, room, 8);
        B(0.85, 0.035, 0.42, MAT.wood, x + 0.37, 0.93, BED.z + 0.6, room);
        B(0.85, 0.01, 0.42, MAT.white, x + 0.37, 0.915, BED.z + 0.6, room, false);
    }

    function buildArmchair(room) {
        const g = new THREE.Group();
        const fab = std(0x2d8fe5, { roughness: 0.95 });
        B(0.8, 0.2, 0.72, fab, 0, 0.42, 0, g);
        const back = B(0.8, 0.55, 0.18, fab, 0, 0.78, -0.3, g); back.rotation.x = -0.18;
        [-0.4, 0.4].forEach(x => { const a = C(0.09, 0.72, fab, x, 0.6, 0, g, 12); a.rotation.x = Math.PI / 2; });
        [-0.34, 0.34].forEach(x => {
            tube(0.8, 0.02, 'z', MAT.steel, x, 0.15, 0, g);
            tube(0.35, 0.02, 'y', MAT.steel, x, 0.3, 0.38, g);
            tube(0.35, 0.02, 'y', MAT.steel, x, 0.3, -0.38, g);
        });
        g.position.set(2.9, 0, -0.6);
        g.rotation.y = Math.atan2(BED.x - 2.9, BED.z - -0.6);
        room.add(g);
    }

    function buildCabinet(room) {
        const g = new THREE.Group();
        B(0.9, 0.9, 0.45, MAT.white, 0, 0.45, 0, g);
        [0.18, 0.45, 0.72].forEach(y => { B(0.8, 0.22, 0.02, MAT.accent, 0, y, 0.23, g, false); B(0.2, 0.02, 0.025, MAT.steel, 0, y + 0.05, 0.25, g, false); });
        g.position.set(3.45, 0, -2.72); room.add(g);
    }

    function buildStool(room) {
        const g = new THREE.Group();
        C(0.17, 0.06, MAT.white, 0, 0.55, 0, g, 18);
        C(0.02, 0.4, MAT.steel, 0, 0.3, 0, g, 8);
        for (let i = 0; i < 5; i++) { const a = i * Math.PI * 2 / 5; const l = B(0.28, 0.02, 0.03, MAT.steel, Math.cos(a) * 0.14, 0.08, Math.sin(a) * 0.14, g); l.rotation.y = -a; C(0.025, 0.03, MAT.dark, Math.cos(a) * 0.27, 0.03, Math.sin(a) * 0.27, g, 8); }
        g.position.set(1.5, 0, -0.1); room.add(g);
    }

    function buildCurtains(room) {
        const y = 2.82, tx0 = -3.2, tx1 = 0.9, tz0 = -2.9, tz1 = -0.15;
        tube(tz1 - tz0, 0.02, 'z', MAT.steel, tx0, y, (tz0 + tz1) / 2, room);
        tube(tz1 - tz0, 0.02, 'z', MAT.steel, tx1, y, (tz0 + tz1) / 2, room);
        tube(tx1 - tx0, 0.02, 'x', MAT.steel, (tx0 + tx1) / 2, y, tz1, room);
        // fabric: head-end panels on both sides + bunched stacks at the foot corners
        pleats(room, tx0, tz0, tx0, -1.45, 0.4, 2.8, 6, 0.05, MAT.curtain);
        pleats(room, tx1, tz0, tx1, -1.95, 0.4, 2.8, 5, 0.05, MAT.curtain);
        pleats(room, tx0, tz1, tx0 + 0.6, tz1, 0.4, 2.8, 4, 0.06, MAT.curtain);
        pleats(room, tx1 - 0.6, tz1, tx1, tz1, 0.4, 2.8, 4, 0.06, MAT.curtain);
        // rings
        for (let z = tz0; z <= -1.45; z += 0.3) C(0.025, 0.02, MAT.steel, tx0, y - 0.02, z, room, 8);
    }

    function buildWindow(room) {
        const cx = (WINDOW.x0 + WINDOW.x1) / 2, w = WINDOW.x1 - WINDOW.x0, h = WINDOW.top - WINDOW.sill, zc = -3 - WALL_T / 2;
        const pane = B(w, h, 0.03, MAT.glass, cx, WINDOW.sill + h / 2, zc, room, false); pane.renderOrder = 2;
        B(w + 0.12, 0.06, 0.2, MAT.white, cx, WINDOW.top + 0.03, zc, room);
        B(w + 0.12, 0.06, 0.2, MAT.white, cx, WINDOW.sill - 0.03, zc, room);
        [WINDOW.x0 - 0.03, WINDOW.x1 + 0.03, cx].forEach(x => B(0.06, h, 0.2, MAT.white, x, WINDOW.sill + h / 2, zc, room));
        B(w + 0.3, 0.04, 0.28, MAT.white, cx, WINDOW.sill - 0.08, zc + 0.14, room);  // inner sill
        // drapes either side
        pleats(room, WINDOW.x0 - 0.75, -2.85, WINDOW.x0 - 0.15, -2.85, 0.5, 2.7, 4, 0.05, MAT.curtain);
        pleats(room, WINDOW.x1 + 0.15, -2.85, WINDOW.x1 + 0.75, -2.85, 0.5, 2.7, 4, 0.05, MAT.curtain);
    }

    function buildDoor(room, id) {
        const x0 = DOOR.x - DOOR.w / 2, x1 = DOOR.x + DOOR.w / 2, zc = 3 + WALL_T / 2;
        B(0.08, DOOR.h, WALL_T + 0.06, MAT.accentDark, x0 - 0.04, DOOR.h / 2, zc, room);
        B(0.08, DOOR.h, WALL_T + 0.06, MAT.accentDark, x1 + 0.04, DOOR.h / 2, zc, room);
        B(DOOR.w + 0.16, 0.08, WALL_T + 0.06, MAT.accentDark, DOOR.x, DOOR.h + 0.04, zc, room);
        // leaf hinged on the x1 side, ajar into the corridor
        const hinge = new THREE.Group();
        hinge.position.set(x1, 0, zc);
        hinge.rotation.y = 1.15;
        const L = DOOR.w - 0.03;
        B(L, DOOR.h - 0.03, 0.05, MAT.white, -L / 2, (DOOR.h - 0.03) / 2, 0, hinge);
        B(L * 0.7, 1.2, 0.055, MAT.accent, -L / 2, 0.85, 0, hinge, false);
        const vg = B(0.3, 0.6, 0.056, MAT.glass, -L / 2, 1.7, 0, hinge, false); vg.renderOrder = 2;
        B(0.14, 0.03, 0.08, MAT.steel, -L + 0.12, 1.0, 0, hinge, false);
        room.add(hinge);
        // number plate above the door (corridor side)
        const tex = canvasTex(256, 96, (g, w, h) => {
            g.fillStyle = '#ffffff'; g.fillRect(0, 0, w, h);
            g.strokeStyle = '#2d8fe5'; g.lineWidth = 8; g.strokeRect(4, 4, w - 8, h - 8);
            g.fillStyle = '#1f6fb8'; g.font = 'bold 48px Inter, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
            g.fillText('ROOM ' + id, w / 2, h / 2 + 2);
        });
        const plate = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.34), new THREE.MeshBasicMaterial({ map: tex }));
        plate.position.set(DOOR.x, 2.55, 3 + WALL_T + 0.012); room.add(plate);
    }

    function buildCCTV(room) {
        const g = new THREE.Group();
        B(0.1, 0.1, 0.12, MAT.white, 0, 0, 0, g);
        const lens = C(0.05, 0.08, MAT.black, 0, 0, 0.1, g, 14); lens.rotation.x = Math.PI / 2;
        mesh(new THREE.SphereGeometry(0.014, 8, 8), new THREE.MeshBasicMaterial({ color: 0xff2222 }), 0.04, 0.05, 0.05, g, false);
        g.position.set(CCTV_LOCAL.x, CCTV_LOCAL.y, CCTV_LOCAL.z);
        room.add(g);
        return g;
    }

    function buildRoom(id, cfg) {
        const room = new THREE.Group();
        const topRow = cfg.rotY === 0;

        const floor = new THREE.Mesh(new THREE.PlaneGeometry(ROOM_W, ROOM_D), tiledMat(textures.room, ROOM_W, ROOM_D, 1.2, 0.3));
        floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; room.add(floor);

        // back (headwall) wall: solid for top rooms, ICU glass for bottom rooms (they face the camera)
        buildWallX(room, -4, 4, -3 - WALL_T / 2, topRow ? [{ x0: WINDOW.x0, x1: WINDOW.x1, sill: WINDOW.sill, top: WINDOW.top }] : [], !topRow, 1);
        // corridor wall with door: ICU glass for top rooms, solid for bottom rooms
        buildWallX(room, -4, 4, 3 + WALL_T / 2, [{ x0: DOOR.x - DOOR.w / 2, x1: DOOR.x + DOOR.w / 2, sill: 0, top: DOOR.h }], topRow, -1);

        if (topRow) buildWindow(room);
        buildDoor(room, id);
        buildHeadwall(room, id);
        buildBed(room, id);
        buildNightstand(room);
        buildIVPole(room);
        buildMonitorTrolley(room, id);
        buildOverbedTable(room);
        buildArmchair(room);
        buildCabinet(room);
        buildStool(room);
        buildCurtains(room);
        buildRoomDetails(room, id, topRow);
        const cctv = buildCCTV(room);

        const light = new THREE.PointLight(0xfff4e0, 0.3, 10);
        light.position.set(-0.5, 2.7, -0.5); room.add(light);

        room.position.set(cfg.x, 0, cfg.z);
        room.rotation.y = cfg.rotY;
        scene.add(room);
        room.updateMatrixWorld(true);
        cctv.lookAt(room.localToWorld(new THREE.Vector3(BED.x, 0.7, BED.z)));
        roomGroups[id] = room;
    }

    // ─── Building shell, corridor, props ───────────────────
    function buildShell() {
        // diorama base
        B(17.6, 0.3, 17.6, MAT.concrete, 0, -0.16, 0, scene, false).receiveShadow = true;

        // corridor floor + guide stripes
        const cor = new THREE.Mesh(new THREE.PlaneGeometry(16, 3.84), tiledMat(textures.corridor, 16, 3.84, 1.2, 0.25));
        cor.rotation.x = -Math.PI / 2; cor.receiveShadow = true; scene.add(cor);
        [-0.9, 0.9].forEach(z => { const s = new THREE.Mesh(new THREE.PlaneGeometry(16, 0.1), new THREE.MeshBasicMaterial({ color: 0x7fbaf0 })); s.rotation.x = -Math.PI / 2; s.position.set(0, 0.006, z); scene.add(s); });

        // outer side walls (corridor end windows) and the divider between rooms
        [-1, 1].forEach(s => {
            const g = new THREE.Group(); g.position.set(s * (8 + WALL_T / 2), 0, 0); g.rotation.y = Math.PI / 2;
            if (s === 1) {   // east end: main entrance (doors + canopy built in buildEntrance)
                buildWallX(g, -8.16, 8.16, 0, [{ x0: -1.2, x1: 1.2, sill: 0, top: 2.5 }], false, -s);
            } else {         // west end: 3 m wide archway into the reception wing
                buildWallX(g, -8.16, 8.16, 0, [{ x0: -1.5, x1: 1.5, sill: 0, top: 2.5 }], false, -s);
            }
            scene.add(g);
        });
        [[-5, 6.32], [5, 6.32]].forEach(([zc, len]) => B(WALL_T, WALL_H, len, MAT.wall, 0, WALL_H / 2, zc, scene));
        B(WALL_T, 0.12, 6.32, MAT.base, 0, 0.06, -5, scene, false);

        // corridor props: crash cart & wheelchair
        const cart = new THREE.Group();
        B(0.7, 0.9, 0.5, MAT.red, 0, 0.55, 0, cart);
        [0.35, 0.55, 0.75].forEach(y => B(0.62, 0.15, 0.02, MAT.white, 0, y, 0.26, cart, false));
        [[-0.3, -0.2], [0.3, -0.2], [-0.3, 0.2], [0.3, 0.2]].forEach(([x, z]) => { const w = C(0.05, 0.04, MAT.dark, x, 0.05, z, cart, 10); w.rotation.z = Math.PI / 2; });
        cart.position.set(-4.3, 0, 1.5); cart.rotation.y = Math.PI; scene.add(cart);

        const wc = new THREE.Group();
        const fab = std(0x334155, { roughness: 0.9 });
        B(0.5, 0.06, 0.5, fab, 0, 0.5, 0, wc);
        B(0.5, 0.5, 0.05, fab, 0, 0.78, -0.25, wc);
        [-0.3, 0.3].forEach(x => {
            const w = mesh(new THREE.TorusGeometry(0.3, 0.015, 8, 24), MAT.steel, x, 0.32, -0.05, wc); w.rotation.y = Math.PI / 2;
            B(0.03, 0.03, 0.55, MAT.steel, x * 0.85, 0.62, 0, wc);
        });
        wc.position.set(-2.0, 0, 1.3); wc.rotation.y = Math.PI - 0.3; scene.add(wc);
        buildCorridorDetails();
        buildReception();
    }

    function createLighting() {
        scene.add(new THREE.HemisphereLight(0xcfe8ff, 0x6f8f5a, 0.65));
        const sun = new THREE.DirectionalLight(0xfff1dc, 1.0);
        sun.target.position.set(-REC.D / 2, 0, 0);   // centre the shadow frustum on the wider building
        sun.position.set(10 - REC.D / 2, 20, 8);
        sun.castShadow = true;
        sun.shadow.mapSize.set(4096, 4096);
        const d = 18;
        Object.assign(sun.shadow.camera, { left: -d, right: d, top: d, bottom: -d, near: 1, far: 60 });
        sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.02;
        scene.add(sun); scene.add(sun.target);
        [-5, 0, 5].forEach(x => { const l = new THREE.PointLight(0xffffff, 0.18, 10); l.position.set(x, 2.8, 0); scene.add(l); });
    }

    // ─── Init / loop ───────────────────────────────────────
    // ═══════════════════════════════════════════════════════
    //  EXTERIOR: sky, garden, entrance, ambulance bay
    //  + clinic interior details (rooms & corridor)
    // ═══════════════════════════════════════════════════════
    const swayers = [], cloudSprites = [], blinkers = [];
    let fountainAnim = null, EX = {};
    const rand = (() => { let s = 20260610; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); })();
    const rr = (a, b) => a + (b - a) * rand();
    const pick = (arr) => arr[Math.floor(rand() * arr.length)];
    const GY = -0.08;   // lawn level

    function buildGardenMaterials() {
        const fl = (c) => std(c, { roughness: 0.95, flatShading: true });
        EX = {
            bark: std(0x6b4a2f, { roughness: 1 }), birch: std(0xe6e1d6, { roughness: 0.9 }),
            leaves: [0x3f9142, 0x58a84a, 0x2e7d3a, 0x6fb04a].map(fl),
            pine: fl(0x20603c), cherry: fl(0xf2aec4), autumn: fl(0xd9822b),
            bush: std(0xffffff, { roughness: 1, flatShading: true }),
            stone: std(0xcfcac0, { roughness: 0.9 }), rock: std(0x8f938f, { roughness: 1, flatShading: true }),
            soil: std(0x4a3426, { roughness: 1 }),
            wood: std(0xa4764a, { roughness: 0.8 }), woodWhite: std(0xf1f3f5, { roughness: 0.6 }),
            metal: std(0x2b3139, { roughness: 0.4, metalness: 0.6 }),
            bulb: new THREE.MeshBasicMaterial({ color: 0xfff4cf }),
            water: new THREE.MeshStandardMaterial({ color: 0x55b4e0, transparent: true, opacity: 0.8, roughness: 0.05, metalness: 0.2, depthWrite: false }),
            pondBed: std(0x2e6f8f, { roughness: 0.6 }),
            asphalt: std(0x3b4048, { roughness: 0.95 }), line: new THREE.MeshBasicMaterial({ color: 0xf3f4f6 }),
            amb: std(0xf8fafc, { roughness: 0.3 }), tire: std(0x14171b, { roughness: 0.9 }),
            glassDark: std(0x1e3a52, { roughness: 0.1, metalness: 0.5 }),
            red: std(0xdc2626, { roughness: 0.4 }),
            pad: std(0x2f9e44, { roughness: 0.9, flatShading: true }),
        };
    }

    function buildGardenTextures() {
        textures.grass = canvasTex(512, 512, (g, w, h) => {
            g.fillStyle = '#5f9f46'; g.fillRect(0, 0, w, h);
            for (let i = 0; i < 9000; i++) {
                const l = rand();
                g.fillStyle = l < 0.33 ? 'rgba(40,110,40,0.35)' : l < 0.66 ? 'rgba(130,185,75,0.30)' : 'rgba(70,140,50,0.30)';
                g.fillRect(rand() * w, rand() * h, 1.5 + rand() * 2, 4 + rand() * 7);
            }
        });
        textures.stripes = canvasTex(256, 256, (g, w, h) => {
            g.clearRect(0, 0, w, h);
            g.fillStyle = 'rgba(255,255,255,0.07)'; g.fillRect(0, 0, w / 2, h);
            g.fillStyle = 'rgba(0,50,10,0.08)'; g.fillRect(w / 2, 0, w / 2, h);
        });
        textures.paving = canvasTex(512, 512, (g, w, h) => {
            g.fillStyle = '#b9b4a8'; g.fillRect(0, 0, w, h);
            for (let r = 0; r < 4; r++) for (let c = -1; c < 3; c++) {
                const x = c * 256 + (r % 2) * 128, l = 76 + rand() * 9;
                g.fillStyle = 'hsl(40,8%,' + l + '%)'; g.fillRect(x + 3, r * 128 + 3, 250, 122);
            }
        });
        textures.cloud = canvasTex(256, 128, (g, w, h) => {
            g.clearRect(0, 0, w, h);
            for (let i = 0; i < 14; i++) {
                const x = 40 + rand() * 176, y = 50 + rand() * 30, r = 22 + rand() * 26;
                const gr = g.createRadialGradient(x, y, 0, x, y, r);
                gr.addColorStop(0, 'rgba(255,255,255,0.9)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
                g.fillStyle = gr; g.fillRect(0, 0, w, h);
            }
        });
        textures.sky = canvasTex(4, 512, (g, w, h) => {
            const gr = g.createLinearGradient(0, 0, 0, h);
            gr.addColorStop(0, '#4b9be8'); gr.addColorStop(0.42, '#9fd0f5'); gr.addColorStop(0.5, '#e6f3ff');
            gr.addColorStop(0.52, '#dcecd6'); gr.addColorStop(1, '#cfe3c0');
            g.fillStyle = gr; g.fillRect(0, 0, w, h);
        });
    }

    // ─── Exterior helpers ──────────────────────────────────
    function flat(w, d, x, z, y, mat, shadow = true) {
        const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat);
        m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); m.receiveShadow = shadow; scene.add(m); return m;
    }
    function paved(x0, z0, x1, z1, y) {
        const w = x1 - x0, d = z1 - z0;
        return flat(w, d, (x0 + x1) / 2, (z0 + z1) / 2, y, tiledMat(textures.paving, w, d, 1.5, 0.85));
    }
    function pavedCircle(cx, cz, r, y) {
        const m = new THREE.Mesh(new THREE.CircleGeometry(r, 48), tiledMat(textures.paving, 2 * r, 2 * r, 1.5, 0.85));
        m.rotation.x = -Math.PI / 2; m.position.set(cx, y, cz); m.receiveShadow = true; scene.add(m); return m;
    }
    function bushes(list, mat, castShadow = true) {
        if (!list.length) return null;
        const im = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 1), mat, list.length);
        const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), c = new THREE.Color(), e = new THREE.Euler(), p = new THREE.Vector3(), s = new THREE.Vector3();
        list.forEach(([x, z, r, col], i) => {
            q.setFromEuler(e.set(0, rand() * 6.28, 0));
            p.set(x, GY + r * 0.5, z); s.set(r * (1 + rand() * 0.2), r * 0.85, r * (1 + rand() * 0.2));
            im.setMatrixAt(i, m4.compose(p, q, s)); im.setColorAt(i, c.setHex(col));
        });
        im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true;
        im.castShadow = castShadow; im.receiveShadow = true; scene.add(im); return im;
    }
    function hedgeLine(out, x0, z0, x1, z1, r, skip) {
        const len = Math.hypot(x1 - x0, z1 - z0), n = Math.max(1, Math.round(len / (r * 1.05)));
        for (let i = 0; i <= n; i++) {
            const t = i / n, x = x0 + (x1 - x0) * t, z = z0 + (z1 - z0) * t;
            if (skip && skip(x, z)) continue;
            out.push([x + rr(-0.05, 0.05), z + rr(-0.05, 0.05), r * rr(0.9, 1.1), pick([0x2f7d32, 0x3a8a3a, 0x2b6f2e])]);
        }
    }

    const flowerSpots = [], cushionList = [];
    const PALETTE = [0xe11d48, 0xf472b6, 0xfacc15, 0xf8fafc, 0xa855f7, 0xfb923c, 0x60a5fa];
    function bedRect(x0, z0, x1, z1) {
        const w = x1 - x0, d = z1 - z0, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
        B(w, 0.14, d, EX.soil, cx, GY + 0.02, cz, scene, false);
        [[w, 0.12, 0.14, cx, z0], [w, 0.12, 0.14, cx, z1], [0.14, 0.12, d, x0, cz], [0.14, 0.12, d, x1, cz]].forEach(([a, b, c, x, z]) => B(a, b, c, EX.stone, x, GY + 0.06, z, scene, false));
        const n = Math.floor(w * d * 9), nc = Math.floor(w * d * 0.9);
        for (let i = 0; i < n; i++) flowerSpots.push([x0 + 0.2 + rand() * (w - 0.4), z0 + 0.2 + rand() * (d - 0.4), pick(PALETTE)]);
        for (let i = 0; i < nc; i++) cushionList.push([x0 + 0.3 + rand() * (w - 0.6), z0 + 0.3 + rand() * (d - 0.6), rr(0.25, 0.4), pick([0x3f9142, 0x2e7d3a, 0x58a84a])]);
    }
    function flushFlowers() {
        bushes(cushionList, EX.bush, false);
        if (!flowerSpots.length) return;
        const im = new THREE.InstancedMesh(new THREE.SphereGeometry(0.075, 6, 5), std(0xffffff, { roughness: 0.8 }), flowerSpots.length);
        const m4 = new THREE.Matrix4(), c = new THREE.Color();
        flowerSpots.forEach(([x, z, col], i) => { im.setMatrixAt(i, m4.makeTranslation(x, GY + 0.36 + rand() * 0.1, z)); im.setColorAt(i, c.setHex(col)); });
        im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true;
        scene.add(im);
    }

    // ─── Trees ─────────────────────────────────────────────
    const TG = {};
    function tree(kind, x, z, s, shadows = true, small = false) {
        if (!TG.trunk) {
            TG.trunk = new THREE.CylinderGeometry(0.12, 0.2, 1, 8); TG.trunk.translate(0, 0.5, 0);
            TG.crown = new THREE.IcosahedronGeometry(1, 1);
            TG.cone = new THREE.ConeGeometry(1, 1, 8); TG.cone.translate(0, 0.5, 0);
        }
        const g = new THREE.Group(); g.position.set(x, GY, z); g.rotation.y = rand() * 6.28; g.scale.setScalar(s);
        const crown = new THREE.Group(); g.add(crown);
        const add = (geo, m, px, py, pz, sx, sy, sz, parent) => {
            const o = new THREE.Mesh(geo, m); o.position.set(px, py, pz); o.scale.set(sx, sy, sz);
            o.castShadow = shadows; o.receiveShadow = false; parent.add(o); return o;
        };
        if (kind === 'pine') {
            add(TG.trunk, EX.bark, 0, 0, 0, 0.9, 1.4, 0.9, g);
            crown.position.y = 1.2;
            [[1.5, 2.0, 0], [1.2, 1.7, 1.1], [0.85, 1.4, 2.0]].forEach(([r, h, y]) => add(TG.cone, EX.pine, 0, y, 0, r, h, r, crown));
        } else {
            const th = kind === 'birch' ? 3.0 : 2.4;
            add(TG.trunk, kind === 'birch' ? EX.birch : EX.bark, 0, 0, 0, kind === 'birch' ? 0.8 : 1.1, th, kind === 'birch' ? 0.8 : 1.1, g);
            crown.position.y = th;
            const mat = kind === 'cherry' ? EX.cherry : kind === 'autumn' ? EX.autumn : pick(EX.leaves);
            const R = kind === 'birch' ? 1.0 : 1.5, n = small ? 2 : 4;
            add(TG.crown, mat, 0, R * 0.6, 0, R, R * 0.85, R, crown);
            for (let i = 1; i < n; i++) { const a = rand() * 6.28; add(TG.crown, mat, Math.cos(a) * R * 0.7, R * rr(0.3, 0.9), Math.sin(a) * R * 0.7, R * 0.7, R * 0.6, R * 0.7, crown); }
        }
        scene.add(g);
        swayers.push({ g: crown, ph: rand() * 6.28, amp: 0.006 + rand() * 0.008 });
        return g;
    }

    function lamp(x, z) {
        const g = new THREE.Group(); g.position.set(x, GY, z);
        C(0.12, 0.1, EX.metal, 0, 0.05, 0, g, 10); C(0.04, 3.2, EX.metal, 0, 1.65, 0, g, 8);
        mesh(new THREE.SphereGeometry(0.16, 10, 8), EX.bulb, 0, 3.3, 0, g, false);
        mesh(new THREE.ConeGeometry(0.28, 0.18, 10), EX.metal, 0, 3.52, 0, g);
        scene.add(g);
    }
    function bench(x, z, rotY) {
        const g = new THREE.Group(); g.position.set(x, GY, z); g.rotation.y = rotY;
        [-0.15, 0, 0.15].forEach(dz => B(1.7, 0.05, 0.1, EX.wood, 0, 0.45, dz, g));
        [0.62, 0.72, 0.82].forEach(y => B(1.7, 0.07, 0.04, EX.wood, 0, y, -0.22 - (y - 0.45) * 0.1, g));
        [-0.75, 0.75].forEach(px => { B(0.06, 0.45, 0.5, EX.metal, px, 0.225, 0, g); B(0.06, 0.4, 0.05, EX.metal, px, 0.65, -0.24, g); });
        scene.add(g);
    }
    function pictureTable(x, z, rotY) {
        const g = new THREE.Group(); g.position.set(x, GY, z); g.rotation.y = rotY;
        B(1.8, 0.05, 0.8, EX.wood, 0, 0.76, 0, g);
        [-0.62, 0.62].forEach(dz => { B(1.8, 0.05, 0.28, EX.wood, 0, 0.45, dz, g); });
        [-0.7, 0.7].forEach(dx => { B(0.07, 0.76, 0.07, EX.woodWhite, dx, 0.38, -0.2, g); B(0.07, 0.76, 0.07, EX.woodWhite, dx, 0.38, 0.2, g); });
        scene.add(g);
    }

    // ─── Fountain ──────────────────────────────────────────
    function buildFountain(cx, cz) {
        const g = new THREE.Group(); g.position.set(cx, -0.04, cz); scene.add(g);
        const stone = std(0xd9d6cc, { roughness: 0.85, side: THREE.DoubleSide });
        const V2 = (a) => a.map(p => new THREE.Vector2(p[0], p[1]));
        const lathe = (pts, m) => { const o = new THREE.Mesh(new THREE.LatheGeometry(V2(pts), 48), m); o.castShadow = o.receiveShadow = true; g.add(o); return o; };
        lathe([[0, 0], [2.05, 0], [2.05, 0.5], [1.85, 0.5], [1.85, 0.12], [0, 0.12]], stone);
        const pool = new THREE.Mesh(new THREE.CircleGeometry(1.85, 48), EX.water); pool.rotation.x = -Math.PI / 2; pool.position.y = 0.4; g.add(pool);
        mesh(new THREE.CylinderGeometry(0.2, 0.3, 1.0, 16), stone, 0, 0.62, 0, g);
        lathe([[0, 1.0], [0.25, 1.0], [0.95, 1.25], [1.0, 1.32], [0.88, 1.32], [0.2, 1.12], [0, 1.12]], stone);
        const bowl = new THREE.Mesh(new THREE.CircleGeometry(0.88, 36), EX.water); bowl.rotation.x = -Math.PI / 2; bowl.position.y = 1.28; g.add(bowl);
        mesh(new THREE.CylinderGeometry(0.1, 0.16, 0.7, 12), stone, 0, 1.5, 0, g);
        mesh(new THREE.SphereGeometry(0.13, 12, 10), stone, 0, 1.9, 0, g);

        const N = 84, drops = new THREE.InstancedMesh(new THREE.SphereGeometry(0.05, 6, 5),
            new THREE.MeshStandardMaterial({ color: 0xdff3ff, transparent: true, opacity: 0.85, roughness: 0.1 }), N);
        g.add(drops);
        const ang = [], ph = [], reach = [];
        for (let i = 0; i < N; i++) { ang.push(rand() * 6.28); ph.push(rand()); reach.push(i < 60 ? rr(0.5, 1.7) : 0); }
        const rings = [0, 1, 2].map(i => {
            const mt = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.4, depthWrite: false, side: THREE.DoubleSide });
            const r = new THREE.Mesh(new THREE.RingGeometry(0.93, 1, 40), mt); r.rotation.x = -Math.PI / 2; r.position.y = 0.43; g.add(r); return r;
        });
        const dummy = new THREE.Object3D();
        fountainAnim = (t) => {
            for (let i = 0; i < N; i++) {
                const u = (t * 0.7 + ph[i]) % 1, r = reach[i];
                if (r > 0) dummy.position.set(Math.cos(ang[i]) * r * u, 1.9 + (0.4 + 0.5 * r / 1.7) * 4 * u * (1 - u) - 1.45 * u, Math.sin(ang[i]) * r * u);
                else dummy.position.set(Math.cos(ang[i]) * 0.04 * u, 1.95 + 1.2 * 4 * u * (1 - u), Math.sin(ang[i]) * 0.04 * u);
                dummy.updateMatrix(); drops.setMatrixAt(i, dummy.matrix);
            }
            drops.instanceMatrix.needsUpdate = true;
            rings.forEach((r, i) => { const k = (t * 0.35 + i / 3) % 1; r.scale.setScalar(0.3 + k * 1.6); r.material.opacity = 0.45 * (1 - k); });
        };
    }

    // ─── Pond ──────────────────────────────────────────────
    function buildPond(cx, cz) {
        const pts = [];
        for (let i = 0; i < 48; i++) { const a = i / 48 * Math.PI * 2, r = 3.1 + 0.5 * Math.sin(a * 3 + 1) + 0.3 * Math.sin(a * 5 + 2); pts.push(new THREE.Vector2(Math.cos(a) * r, Math.sin(a) * r)); }
        const geo = new THREE.ShapeGeometry(new THREE.Shape(pts));
        const bed = new THREE.Mesh(geo, EX.pondBed); bed.rotation.x = -Math.PI / 2; bed.position.set(cx, GY + 0.01, cz); bed.receiveShadow = true; scene.add(bed);
        const water = new THREE.Mesh(geo, EX.water); water.rotation.x = -Math.PI / 2; water.position.set(cx, GY + 0.04, cz); water.renderOrder = 1; scene.add(water);
        // rim stones (shape y maps to world -z after the rotation)
        const nS = 40, rim = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 0), EX.rock, nS);
        const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3(), e = new THREE.Euler();
        for (let i = 0; i < nS; i++) {
            const a = i / nS * Math.PI * 2, r = 3.1 + 0.5 * Math.sin(a * 3 + 1) + 0.3 * Math.sin(a * 5 + 2) + 0.12, k = rr(0.18, 0.34);
            q.setFromEuler(e.set(rand() * 3, rand() * 3, rand() * 3));
            rim.setMatrixAt(i, m4.compose(p.set(cx + Math.cos(a) * r, GY + 0.05, cz - Math.sin(a) * r), q, s.set(k * 1.3, k * 0.8, k)));
        }
        rim.castShadow = true; scene.add(rim);
        for (let i = 0; i < 8; i++) {
            const a = rand() * 6.28, r = rr(0.4, 2.3);
            const pad = new THREE.Mesh(new THREE.CircleGeometry(rr(0.22, 0.34), 12, 0.3, 5.7), EX.pad);
            pad.rotation.x = -Math.PI / 2; pad.position.set(cx + Math.cos(a) * r, GY + 0.06, cz + Math.sin(a) * r); pad.renderOrder = 2; scene.add(pad);
            if (i % 3 === 0) mesh(new THREE.SphereGeometry(0.07, 8, 6), std(0xf9a8d4), pad.position.x, GY + 0.1, pad.position.z, scene, false);
        }
        for (let i = 0; i < 16; i++) {
            const a = rr(2.2, 3.6), r = 3.0 + rr(-0.1, 0.5), h = rr(0.9, 1.5);
            const x = cx + Math.cos(a) * r, z = cz + Math.sin(a) * r;
            C(0.015, h, EX.leaves[2], x, GY + h / 2, z, scene, 5);
            if (i % 3 === 0) C(0.035, 0.18, EX.bark, x, GY + h, z, scene, 6);
        }
    }

    // ─── Vehicles ──────────────────────────────────────────
    function wheel(parent, x, y, z, r) { const w = C(r, 0.26, EX.tire, x, y, z, parent, 14); w.rotation.x = Math.PI / 2; C(r * 0.5, 0.28, MAT.steel, x, y, z, parent, 10).rotation.x = Math.PI / 2; }
    function buildAmbulance(x, z, rotY) {
        const g = new THREE.Group();
        B(3.0, 1.7, 1.95, EX.amb, -0.7, 1.3, 0, g);
        B(1.4, 1.2, 1.95, EX.amb, 1.5, 1.05, 0, g);
        B(0.6, 0.7, 1.9, EX.amb, 2.3, 0.8, 0, g);
        B(4.8, 0.16, 1.99, EX.red, 0.2, 0.95, 0, g);
        const ws = B(0.05, 0.65, 1.7, EX.glassDark, 2.12, 1.4, 0, g); ws.rotation.z = -0.5;
        [-1, 1].forEach(sd => B(0.8, 0.5, 0.02, EX.glassDark, 1.5, 1.35, sd * 0.98, g, false));
        const decal = canvasTex(256, 256, (c) => {
            c.fillStyle = '#ffffff'; c.fillRect(0, 0, 256, 256);
            c.fillStyle = '#dc2626'; c.fillRect(103, 20, 50, 130); c.fillRect(63, 60, 130, 50);
            c.fillStyle = '#1f2937'; c.font = 'bold 34px sans-serif'; c.textAlign = 'center'; c.fillText('AMBULANCE', 128, 220);
        });
        [-1, 1].forEach(sd => { const p = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1.6), new THREE.MeshBasicMaterial({ map: decal })); p.position.set(-0.7, 1.55, sd * 0.985); if (sd < 0) p.rotation.y = Math.PI; g.add(p); });
        B(1.2, 0.1, 0.9, EX.metal, 1.2, 1.7, 0, g);
        const red = new THREE.MeshBasicMaterial({ color: 0xff2d2d }), blue = new THREE.MeshBasicMaterial({ color: 0x2d6bff });
        B(0.5, 0.1, 0.9, red, 1.2, 1.78, -0.0, g, false).position.x = 1.0;
        B(0.5, 0.1, 0.9, blue, 1.45, 1.78, 0, g, false);
        blinkers.push({ a: red, b: blue });
        B(0.1, 0.3, 1.9, EX.metal, 2.62, 0.5, 0, g); B(0.1, 0.3, 1.9, EX.metal, -2.25, 0.5, 0, g);
        [-1, 1].forEach(sd => mesh(new THREE.SphereGeometry(0.1, 8, 6), EX.bulb, 2.64, 0.8, sd * 0.65, g, false));
        [-1.5, 1.5].forEach(wx => [-1, 1].forEach(sd => wheel(g, wx, 0.42, sd * 0.95, 0.42)));
        g.position.set(x, GY + 0.01, z); g.rotation.y = rotY; scene.add(g);
    }
    function buildCar(x, z, rotY, color) {
        const g = new THREE.Group(), body = std(color, { roughness: 0.3, metalness: 0.3 });
        B(3.8, 0.6, 1.7, body, 0, 0.62, 0, g);
        B(2.0, 0.5, 1.55, body, -0.2, 1.15, 0, g);
        B(1.9, 0.38, 1.58, EX.glassDark, -0.2, 1.17, 0, g, false);
        [-1.2, 1.2].forEach(wx => [-1, 1].forEach(sd => wheel(g, wx, 0.33, sd * 0.8, 0.33)));
        g.position.set(x, GY + 0.01, z); g.rotation.y = rotY; scene.add(g);
    }

    // ─── Entrance: sliding glass doors, canopy, signage ────
    function buildEntrance() {
        const g = new THREE.Group(); g.position.set(8.08, 0, 0); g.rotation.y = Math.PI / 2; scene.add(g);
        [-1.25, 1.25].forEach(x => B(0.1, 2.5, WALL_T + 0.1, MAT.steel, x, 1.25, 0, g));
        B(2.6, 0.12, WALL_T + 0.1, MAT.steel, 0, 2.56, 0, g);
        [-0.6, 0.6].forEach((x, i) => {
            const pane = B(1.15, 2.4, 0.03, MAT.glass, x, 1.2, i ? 0.05 : -0.05, g, false); pane.renderOrder = 2;
            B(1.15, 0.06, 0.05, MAT.steel, x, 0.03, i ? 0.05 : -0.05, g, false); B(1.15, 0.06, 0.05, MAT.steel, x, 2.37, i ? 0.05 : -0.05, g, false);
            [-0.575, 0.575].forEach(dx => B(0.05, 2.4, 0.05, MAT.steel, x + dx, 1.2, i ? 0.05 : -0.05, g, false));
            tube(0.7, 0.014, 'y', MAT.steel, x + (i ? -0.5 : 0.5), 1.05, i ? 0.1 : -0.1, g);
        });
        B(2.4, 0.04, 0.2, MAT.steel, 0, 0.02, 0, g, false);
        B(0.3, 0.08, 0.08, MAT.dark, 0, 2.47, 0.1, g, false);
        const band = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 0.12), new THREE.MeshBasicMaterial({ color: 0x2d8fe5, transparent: true, opacity: 0.8 }));
        band.position.set(0, 1.5, 0.08); g.add(band);
        // canopy
        B(7.2, 0.14, 3.9, MAT.white, 0, 3.3, 2.05, g);
        B(7.2, 0.03, 3.9, MAT.accent, 0, 3.38, 2.05, g, false);
        B(7.3, 0.8, 0.12, MAT.accent, 0, 3.0, 4.0, g);
        [[-3.1, 3.7], [3.1, 3.7], [-1.6, 3.7], [1.6, 3.7]].forEach(([x, z]) => C(0.09, 3.25, MAT.white, x, 1.62, z, g, 14));
        [[-2.4, 3.0], [0, 3.0], [2.4, 3.0], [-2.4, 1.2], [0, 1.2], [2.4, 1.2]].forEach(([x, z]) => B(0.3, 0.02, 0.3, EX.bulb, x, 3.22, z, g, false));
        const sign = canvasTex(1024, 160, (c, w, h) => {
            const gr = c.createLinearGradient(0, 0, w, 0); gr.addColorStop(0, '#1f6fb8'); gr.addColorStop(1, '#2d8fe5');
            c.fillStyle = gr; c.fillRect(0, 0, w, h);
            c.fillStyle = '#ffffff'; c.fillRect(98, 40, 24, 80); c.fillRect(70, 68, 80, 24);
            c.font = 'bold 84px sans-serif'; c.textBaseline = 'middle'; c.textAlign = 'left'; c.fillText('HACKCURE CLINIC', 180, 84);
        });
        const sp = new THREE.Mesh(new THREE.PlaneGeometry(6.4, 1.0), new THREE.MeshBasicMaterial({ map: sign })); sp.position.set(0, 3.0, 4.07); sp.scale.y = 0.62; g.add(sp);
        // planters either side of the doors
        [-1, 1].forEach(sd => {
            B(1.0, 0.5, 0.5, MAT.white, 9.4, 0.25, sd * 2.5, scene);
            bushes([[9.2, sd * 2.5, 0.38, 0x3a8a3a], [9.55, sd * 2.5, 0.32, 0x2f7d32], [9.4, sd * 2.5 + 0.1, 0.3, 0x58a84a]], EX.bush, false);
        });
    }

    function buildSignTotem(x, z, rotY) {
        const g = new THREE.Group(); g.position.set(x, GY, z); g.rotation.y = rotY;
        B(1.3, 2.2, 0.2, MAT.white, 0, 1.1, 0, g); B(1.3, 0.12, 0.22, MAT.accent, 0, 2.2, 0, g);
        const tex = canvasTex(256, 512, (c, w, h) => {
            c.fillStyle = '#ffffff'; c.fillRect(0, 0, w, h);
            c.fillStyle = '#2d8fe5'; c.fillRect(100, 40, 56, 150); c.fillRect(53, 87, 150, 56);
            c.fillStyle = '#1f6fb8'; c.textAlign = 'center'; c.font = 'bold 40px sans-serif';
            c.fillText('HACKCURE', 128, 270); c.fillText('CLINIC', 128, 316);
            c.fillStyle = '#475569'; c.font = '26px sans-serif'; c.fillText('Open 24 / 7', 128, 380); c.fillText('Emergency · Care', 128, 420);
        });
        [-1, 1].forEach(sd => { const p = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 2.0), new THREE.MeshBasicMaterial({ map: tex })); p.position.set(0, 1.1, sd * 0.106); if (sd < 0) p.rotation.y = Math.PI; g.add(p); });
        scene.add(g);
    }

    function buildPergola(cx, cz) {
        const g = new THREE.Group(); g.position.set(cx, GY, cz);
        [[-1.4, -1.4], [1.4, -1.4], [-1.4, 1.4], [1.4, 1.4]].forEach(([x, z]) => B(0.14, 2.6, 0.14, EX.woodWhite, x, 1.3, z, g));
        [-1.4, 1.4].forEach(z => B(3.2, 0.14, 0.14, EX.woodWhite, 0, 2.6, z, g));
        for (let x = -1.3; x <= 1.31; x += 0.4) B(0.08, 0.1, 3.2, EX.woodWhite, x, 2.7, 0, g);
        scene.add(g);
        const v = []; for (let i = 0; i < 16; i++) v.push([cx + rr(-1.4, 1.4), cz + rr(-1.4, 1.4), rr(0.3, 0.45), pick([0x3f9142, 0x2e7d3a])]);
        const im = bushes(v, EX.bush, false); if (im) im.position.y = 2.5;
        bench(cx, cz + 0.6, Math.PI);
    }

    // ─── Build everything outside the building ─────────────
    const ZR = [   // rect exclusion zones for random trees
        [-12.3 - REC.D, -12.3, 12.3, 12.3], [8.4, -9.4, 34.5, 9.4], [11, 3, 14, 13.4], [14, -24.5, 30, -4],
        [20, 4, 24, 12], [18.8, 8.8, 25.2, 11.8], [-18.5 - REC.D, -2.5, -10 - REC.D, 2.5], [-2.5, -19, 2.5, -10], [-33, 11, 19, 17.4],
    ];
    const ZC = [[22, 0, 5.4], [22, -18, 4.8], [0, -18.5, 4.4], [-19 - REC.D, 0, 3.8], [22.5, 15, 5.6]];
    function treeFree(x, z, pad) {
        for (const r of ZR) if (x > r[0] - pad && x < r[2] + pad && z > r[1] - pad && z < r[3] + pad) return false;
        for (const c of ZC) if (Math.hypot(x - c[0], z - c[1]) < c[2] + pad) return false;
        return true;
    }

    function buildExterior() {
        scene.fog = new THREE.Fog(0xcfe6f7, 90, 230);
        const sky = new THREE.Mesh(new THREE.SphereGeometry(260, 32, 16), new THREE.MeshBasicMaterial({ map: textures.sky, side: THREE.BackSide, fog: false, depthWrite: false }));
        sky.renderOrder = -10; scene.add(sky);
        for (let i = 0; i < 10; i++) {
            const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: textures.cloud, transparent: true, opacity: 0.9, fog: false, depthWrite: false }));
            sp.scale.set(rr(40, 70), rr(14, 22), 1);
            const a = rand() * 6.28, r = rr(110, 200); sp.position.set(Math.cos(a) * r, rr(55, 90), Math.sin(a) * r);
            scene.add(sp); cloudSprites.push(sp);
        }

        // lawn + mowing stripes
        flat(520, 520, 0, 0, GY, tiledMat(textures.grass, 520, 520, 4, 1));
        const st = tiledMat(textures.stripes, 74, 74, 6, 1); st.transparent = true; st.depthWrite = false;
        flat(74, 74, 0, 0, GY + 0.01, st, true);

        // paths & plazas
        const ring = [[-10.1 - REC.D, -10.1, 10.1, -8.6], [-10.1 - REC.D, 8.6, 10.1, 10.1], [-10.1 - REC.D, -8.6, -8.6 - REC.D, 8.6], [8.6, -8.6, 10.1, 8.6]];
        ring.forEach(r => paved(r[0], r[1], r[2], r[3], -0.05));
        paved(8.6, -3.6, 13.6, 3.6, -0.04);
        paved(13.6, -1.5, 34, 1.5, -0.05);
        pavedCircle(22, 0, 4.2, -0.035);
        paved(20.8, -17.5, 23.2, -4.2, -0.05); pavedCircle(22, -18, 3.4, -0.035);
        paved(20.8, 4.2, 23.2, 10.2, -0.05); paved(19.2, 9.2, 24.8, 11.4, -0.04);
        paved(11.6, 3.6, 13.4, 12.0, -0.05);
        paved(-17.5 - REC.D, -1.2, -10.1 - REC.D, 1.2, -0.05); pavedCircle(-19 - REC.D, 0, 2.8, -0.04);
        paved(-1.2, -16.5, 1.2, -10.1, -0.05); pavedCircle(0, -18.5, 3.0, -0.04);

        // road + ambulance bay
        flat(50.5, 4.6, -6.75, 14.2, -0.06, EX.asphalt);
        [11.9, 16.5].forEach(z => B(50.5, 0.12, 0.18, EX.stone, -6.75, GY + 0.02, z, scene, false));
        for (let x = -30; x < 17; x += 3) { const d = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.14), EX.line); d.rotation.x = -Math.PI / 2; d.position.set(x, -0.055, 14.2); scene.add(d); }
        const rt = canvasTex(512, 128, (c, w, h) => { c.clearRect(0, 0, w, h); c.fillStyle = '#f3f4f6'; c.font = 'bold 96px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('EMERGENCY', w / 2, h / 2); });
        const rtm = new THREE.Mesh(new THREE.PlaneGeometry(5, 1.25), new THREE.MeshBasicMaterial({ map: rt, transparent: true, depthWrite: false })); rtm.rotation.x = -Math.PI / 2; rtm.position.set(-1, -0.05, 15.3); scene.add(rtm);
        buildAmbulance(7, 13.2, Math.PI);
        buildCar(-5, 15.2, 0, 0x2563eb); buildCar(-12, 13.2, Math.PI, 0xe5e7eb);
        for (let i = 0; i < 3; i++) B(0.1, 1.0, 0.1, EX.metal, 17.5, GY + 0.5, 12.5 + i * 1.6, scene);
        B(0.12, 0.12, 5, MAT.red, 17.5, GY + 1.05, 14.2, scene, false);

        // hedges around the building (gaps for paths)
        const hl = [];
        const gapN = (x, z) => Math.abs(x) < 1.8, gapW = (x, z) => Math.abs(z) < 1.8;
        hedgeLine(hl, -10.9 - REC.D, -10.9, 10.9, -10.9, 0.5, gapN);
        hedgeLine(hl, -10.9 - REC.D, 10.9, 10.9, 10.9, 0.5);
        hedgeLine(hl, -10.9 - REC.D, -10.9, -10.9 - REC.D, 10.9, 0.5, gapW);
        hedgeLine(hl, 10.9, -10.6, 10.9, -8.4, 0.5); hedgeLine(hl, 10.9, 8.4, 10.9, 10.6, 0.5);
        bushes(hl, EX.bush, false);

        // flower beds
        [[10.4, -8.6, 13.4, -4.5], [14.4, -8.6, 19.0, -4.2], [14.4, 4.2, 19.0, 8.4],
        [15.5, -15.5, 19.5, -10.5], [24.5, -15.5, 28.5, -10.5], [15.5, -23, 19.5, -19], [24.5, -23, 28.5, -19]]
            .forEach(b => bedRect(b[0], b[1], b[2], b[3]));
        flushFlowers();

        // lawn wildflowers
        const wf = new THREE.InstancedMesh(new THREE.SphereGeometry(0.05, 5, 4), std(0xffffff, { roughness: 0.9 }), 300);
        const m4 = new THREE.Matrix4(), cc = new THREE.Color();
        for (let i = 0, n = 0; n < 300 && i < 3000; i++) {
            const x = rr(-34, 34), z = rr(-34, 34); if (!treeFree(x, z, 0.5)) continue;
            wf.setMatrixAt(n, m4.makeTranslation(x, GY + 0.08, z)); wf.setColorAt(n, cc.setHex(pick([0xffffff, 0xfde047, 0xfbcfe8]))); n++;
        }
        wf.instanceMatrix.needsUpdate = true; if (wf.instanceColor) wf.instanceColor.needsUpdate = true; scene.add(wf);

        // features
        buildFountain(22, 0); buildPond(22.5, 15); buildPergola(22, -18); buildEntrance(); buildSignTotem(15.2, -3.4, -Math.PI / 2 + 0.25);
        pictureTable(0, -19.2, 0.3); bench(1.8, -15, -Math.PI / 2); bench(-1.8, -15, Math.PI / 2);
        bench(-19 - REC.D, 2.0, Math.PI); bench(-21.2 - REC.D, 0, Math.PI / 2);
        [0, 1, 2, 3].forEach(i => { const a = i * Math.PI / 2 + Math.PI / 4; bench(22 + Math.cos(a) * 3.4, Math.sin(a) * 3.4, -a - Math.PI / 2); });
        bench(21, 12.2, Math.PI);
        // birdbath
        const bb = new THREE.Group(); bb.position.set(-19 - REC.D, GY, 0);
        mesh(new THREE.CylinderGeometry(0.15, 0.25, 0.8, 12), EX.stone, 0, 0.4, 0, bb); mesh(new THREE.CylinderGeometry(0.5, 0.2, 0.18, 16), EX.stone, 0, 0.88, 0, bb);
        const bw = new THREE.Mesh(new THREE.CircleGeometry(0.42, 16), EX.water); bw.rotation.x = -Math.PI / 2; bw.position.y = 0.97; bb.add(bw); scene.add(bb);
        // lamps
        [[13, -2.2], [13, 2.2], [17, -2.2], [17, 2.2], [27, -2.2], [27, 2.2], [31, 2.2], [31, -2.2], [22, -5.5], [22, 5.5], [17.8, -2.2], [26.2, 2.2], [-12 - REC.D, 2.2], [-12 - REC.D, -2.2], [2.2, -12], [-2.2, -12], [12.5, 11], [-8, 10.9], [8, 10.9]].forEach(p => lamp(p[0], p[1]));

        // trees: hand-placed, random, boundary
        [[-22.5 - REC.D, -3, 'cherry', 1.2], [-22 - REC.D, 3.3, 'cherry', 1.1], [-16.5 - REC.D, -3.6, 'cherry', 1.15], [-16.5 - REC.D, 3.8, 'cherry', 1.1],
        [26, 11, 'leaf', 1.5], [19, 19, 'leaf', 1.6], [-4, -22.5, 'birch', 1.2], [4, -22.5, 'birch', 1.2], [-8, -15.5, 'leaf', 1.3], [8, -15.5, 'leaf', 1.3],
        [30, -7, 'autumn', 1.3], [30, 7, 'cherry', 1.2]].forEach(t => tree(t[2], t[0], t[1], t[3]));
        for (let i = 0, n = 0; n < 34 && i < 800; i++) {
            const x = rr(-33, 33), z = rr(-33, 33);
            if (!treeFree(x, z, 2.5)) continue;
            const k = rand(), kind = k < 0.5 ? 'leaf' : k < 0.7 ? 'pine' : k < 0.85 ? 'birch' : k < 0.93 ? 'cherry' : 'autumn';
            tree(kind, x, z, rr(1.0, 1.7), Math.abs(x) < 17 && Math.abs(z) < 17); n++;
        }
        for (let i = -42; i <= 42; i += 3.5) [[i, -40], [i, 40], [-40, i], [40, i]].forEach(p => {
            if (Math.abs(p[0]) > 34 && Math.abs(p[1]) > 34 && false) return;
            tree(rand() < 0.4 ? 'pine' : 'leaf', p[0] + rr(-1, 1), p[1] + rr(-1, 1), rr(1.4, 2.2), false, true);
        });

        // boundary fence with a gate opening on the main path
        const fp = [], FZ = 34;
        for (let t = -FZ; t <= FZ; t += 2) { fp.push([t, -FZ], [t, FZ]); if (Math.abs(t) > 2 && Math.abs(t) < FZ) fp.push([-FZ, t]); if (Math.abs(t) > 2) fp.push([FZ, t]); }
        const posts = new THREE.InstancedMesh(new THREE.BoxGeometry(0.12, 1.2, 0.12), EX.woodWhite, fp.length);
        fp.forEach((p, i) => posts.setMatrixAt(i, m4.makeTranslation(p[0], GY + 0.6, p[1]))); posts.castShadow = false; scene.add(posts);
        [0.4, 0.95].forEach(y => {
            B(2 * FZ, 0.07, 0.05, EX.woodWhite, 0, GY + y, -FZ, scene, false); B(2 * FZ, 0.07, 0.05, EX.woodWhite, 0, GY + y, FZ, scene, false);
            B(0.05, 0.07, 2 * FZ, EX.woodWhite, -FZ, GY + y, 0, scene, false);
            B(0.05, 0.07, FZ - 2, EX.woodWhite, FZ, GY + y, (FZ + 2) / 2, scene, false); B(0.05, 0.07, FZ - 2, EX.woodWhite, FZ, GY + y, -(FZ + 2) / 2, scene, false);
        });
        [-2, 2].forEach(z => { B(0.5, 1.8, 0.5, EX.stone, FZ, GY + 0.9, z, scene); B(0.6, 0.1, 0.6, EX.metal, FZ, GY + 1.85, z, scene); });
    }

    function animateExterior(t, dt) {
        swayers.forEach(s => { s.g.rotation.z = Math.sin(t * 0.8 + s.ph) * s.amp; s.g.rotation.x = Math.cos(t * 0.6 + s.ph) * s.amp * 0.7; });
        cloudSprites.forEach(c => { c.position.x += dt * 0.8; if (c.position.x > 220) c.position.x = -220; });
        if (fountainAnim) fountainAnim(t);
        const on = Math.floor(t * 3) % 2 === 0;
        blinkers.forEach(b => { b.a.color.setHex(on ? 0xff2d2d : 0x551111); b.b.color.setHex(on ? 0x112255 : 0x2d6bff); });
    }

    // ═══ Clinic interior details ═══════════════════════════
    function plantPot(parent, x, z, s = 1) {
        const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(s);
        mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.4, 16), MAT.white, 0, 0.2, 0, g);
        C(0.18, 0.02, EX.soil, 0, 0.4, 0, g, 12);
        C(0.02, 0.5, EX.bark, 0, 0.65, 0, g, 6);
        for (let i = 0; i < 6; i++) { const a = i / 6 * 6.28; mesh(new THREE.IcosahedronGeometry(0.2, 0), EX.leaves[i % 3], Math.cos(a) * 0.14, 0.9 + (i % 3) * 0.16, Math.sin(a) * 0.14, g); }
        parent.add(g); return g;
    }
    function calendarTex(w, h, draw) { return canvasTex(w, h, draw); }
    function wallPlane(parent, tex, w, h, x, y, z, rotY) {
        const p = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex }));
        p.position.set(x, y, z); p.rotation.y = rotY; parent.add(p); return p;
    }

    function buildRoomDetails(room, id, topRow) {
        // guard rail along the left wall
        B(0.06, 0.12, 5.8, MAT.accent, -3.93, 0.95, 0, room, false);
        B(0.04, 0.04, 5.8, MAT.railWood, -3.89, 0.95, 0, room, false);

        // sink unit on the right wall
        const sk = new THREE.Group(); sk.position.set(3.67, 0, 1.55); room.add(sk);
        B(0.5, 0.78, 0.6, MAT.white, 0, 0.39, 0, sk);
        [-0.15, 0.15].forEach(dz => B(0.02, 0.6, 0.26, MAT.accent, -0.26, 0.4, dz, sk, false));
        B(0.54, 0.04, 0.64, MAT.white, 0, 0.8, 0, sk);
        C(0.19, 0.05, MAT.steel, -0.02, 0.83, 0, sk, 20);
        tube(0.22, 0.012, 'y', MAT.steel, 0.17, 0.92, 0, sk); tube(0.14, 0.012, 'x', MAT.steel, 0.1, 1.03, 0, sk);
        B(0.03, 0.75, 0.55, MAT.mirror, 0.235, 1.55, 0, sk, false);
        B(0.06, 0.16, 0.08, MAT.white, 0.21, 1.15, 0.38, sk); B(0.04, 0.04, 0.04, MAT.accent, 0.17, 1.2, 0.38, sk, false);
        // hand sanitiser by the door
        B(0.1, 0.26, 0.1, MAT.white, 3.86, 1.2, 2.7, room); B(0.04, 0.05, 0.08, MAT.accent, 3.78, 1.28, 2.7, room, false);

        // wall TV (left wall, faces the room)
        const tv = new THREE.Group(); tv.position.set(-3.9, 1.95, -0.7); tv.rotation.y = Math.PI / 2; room.add(tv);
        B(1.0, 0.58, 0.05, MAT.screenFrame, 0, 0, 0, tv);
        const tvTex = canvasTex(256, 144, (c, w, h) => {
            const gr = c.createLinearGradient(0, 0, w, h); gr.addColorStop(0, '#0e3a6b'); gr.addColorStop(1, '#2d8fe5');
            c.fillStyle = gr; c.fillRect(0, 0, w, h); c.fillStyle = 'rgba(255,255,255,0.9)';
            c.font = 'bold 22px sans-serif'; c.textAlign = 'center'; c.fillText('Welcome to HackCure', w / 2, 60);
            c.font = '14px sans-serif'; c.fillText('Relax · Rest · Recover', w / 2, 90);
        });
        const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.94, 0.52), new THREE.MeshBasicMaterial({ map: tvTex })); scr.position.z = 0.03; tv.add(scr);

        // whiteboard care plan
        const wb = new THREE.Group(); wb.position.set(-3.9, 1.6, 1.6); wb.rotation.y = Math.PI / 2; room.add(wb);
        B(0.96, 0.66, 0.03, MAT.steel, 0, 0, 0, wb);
        const wbTex = canvasTex(256, 176, (c, w, h) => {
            c.fillStyle = '#ffffff'; c.fillRect(0, 0, w, h);
            c.fillStyle = '#1f6fb8'; c.font = 'bold 18px sans-serif'; c.fillText('CARE PLAN · ROOM ' + id, 10, 24);
            c.strokeStyle = '#cbd5e1'; c.lineWidth = 1;
            ['Nurse', 'Diet', 'Allergies', 'Mobility', 'Next check'].forEach((t, i) => { c.fillStyle = '#334155'; c.font = '13px sans-serif'; c.fillText(t + ':', 10, 54 + i * 24); c.beginPath(); c.moveTo(90, 56 + i * 24); c.lineTo(240, 56 + i * 24); c.stroke(); });
        });
        const wbp = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.6), new THREE.MeshBasicMaterial({ map: wbTex })); wbp.position.z = 0.02; wb.add(wbp);

        // clock
        const clk = new THREE.Group(); clk.position.set(-3.9, 2.4, 2.35); clk.rotation.y = Math.PI / 2; room.add(clk);
        const clkTex = canvasTex(128, 128, (c) => {
            c.fillStyle = '#ffffff'; c.beginPath(); c.arc(64, 64, 60, 0, 6.28); c.fill();
            c.strokeStyle = '#1f2937'; c.lineWidth = 3; c.stroke();
            for (let i = 0; i < 12; i++) { const a = i / 12 * 6.28; c.beginPath(); c.moveTo(64 + Math.sin(a) * 50, 64 - Math.cos(a) * 50); c.lineTo(64 + Math.sin(a) * 56, 64 - Math.cos(a) * 56); c.stroke(); }
            c.lineWidth = 4; c.beginPath(); c.moveTo(64, 64); c.lineTo(64 - 20, 64 - 12); c.stroke();
            c.lineWidth = 3; c.beginPath(); c.moveTo(64, 64); c.lineTo(64 + 30, 64 - 38); c.stroke();
        });
        const cp = new THREE.Mesh(new THREE.CircleGeometry(0.2, 24), new THREE.MeshBasicMaterial({ map: clkTex })); cp.position.z = 0.02; clk.add(cp);
        C(0.21, 0.03, MAT.dark, 0, 0, 0.005, clk, 24).rotation.x = Math.PI / 2;

        // framed landscape
        const art = new THREE.Group(); art.position.set(-3.9, 1.75, -2.05); art.rotation.y = Math.PI / 2; room.add(art);
        B(0.85, 0.58, 0.04, MAT.wood, 0, 0, 0, art);
        const artTex = canvasTex(256, 176, (c, w, h) => {
            const gr = c.createLinearGradient(0, 0, 0, h * 0.6); gr.addColorStop(0, '#7ec8f2'); gr.addColorStop(1, '#e6f4ff'); c.fillStyle = gr; c.fillRect(0, 0, w, h);
            c.fillStyle = '#6fb15a'; c.beginPath(); c.moveTo(0, 110); c.quadraticCurveTo(80, 70, 160, 105); c.quadraticCurveTo(210, 85, 256, 100); c.lineTo(256, 176); c.lineTo(0, 176); c.fill();
            c.fillStyle = '#4a9441'; c.beginPath(); c.moveTo(0, 140); c.quadraticCurveTo(120, 110, 256, 140); c.lineTo(256, 176); c.lineTo(0, 176); c.fill();
            c.fillStyle = '#fde68a'; c.beginPath(); c.arc(200, 40, 18, 0, 6.28); c.fill();
        });
        const ap = new THREE.Mesh(new THREE.PlaneGeometry(0.75, 0.48), new THREE.MeshBasicMaterial({ map: artTex })); ap.position.z = 0.025; art.add(ap);

        plantPot(room, -3.45, 2.4, 1.0);
        B(0.9, 0.012, 1.4, std(0xd9e8f5, { roughness: 1 }), BED.x - 0.0, 0.006, BED.z + 2.5, room, false);   // bedside floor mat
    }

    function chairRow(parent, x0, z, n, rotY) {
        const g = new THREE.Group(); g.position.set(x0, 0, z); g.rotation.y = rotY;
        const len = n * 0.55;
        B(len, 0.06, 0.08, MAT.steel, len / 2 - 0.27, 0.34, 0, g);
        [0.05, len - 0.05].forEach(x => B(0.05, 0.34, 0.5, MAT.steel, x - 0.27, 0.17, 0, g));
        for (let i = 0; i < n; i++) {
            const x = i * 0.55;
            B(0.5, 0.07, 0.48, MAT.chairBlue, x, 0.43, 0.04, g); B(0.5, 0.42, 0.06, MAT.chairBlue, x, 0.72, -0.2, g);
        }
        parent.add(g);
    }

    function buildCorridorDetails() {
        // handrails (gaps at the doors)
        const rail = (a, b, z) => {
            const len = b - a, cx = (a + b) / 2;
            tube(len, 0.026, 'x', MAT.railWood, cx, 0.92, z, scene);
            for (let x = a + 0.3; x < b; x += 1.2) B(0.04, 0.04, 0.08, MAT.steel, x, 0.92, z + (z < 0 ? -0.05 : 0.05), scene, false);
        };
        [[-7.9, -2.15], [-0.65, 5.85]].forEach(r => rail(r[0], r[1], -1.76));
        [[-5.85, 0.65], [2.15, 7.9]].forEach(r => rail(r[0], r[1], 1.76));

        // waiting area (north glass wall)
        chairRow(scene, 0.55, -1.52, 4, 0);
        const tb = new THREE.Group(); tb.position.set(3.6, 0, -1.4); scene.add(tb);
        C(0.28, 0.04, MAT.white, 0, 0.5, 0, tb, 20); C(0.03, 0.5, MAT.steel, 0, 0.25, 0, tb, 8); C(0.2, 0.02, MAT.dark, 0, 0.01, 0, tb, 14);
        [0xdc2626, 0x2563eb, 0xeab308].forEach((c, i) => { const m = B(0.22, 0.012, 0.3, std(c), (i - 1) * 0.04, 0.53 + i * 0.012, 0, tb, false); m.rotation.y = i * 0.5; });
        plantPot(scene, 4.8, -1.45, 1.1);

        // reception desk (south wall)
        const rd = new THREE.Group(); rd.position.set(5.1, 0, 1.15); scene.add(rd);
        B(3.0, 1.0, 0.5, MAT.white, 0, 0.5, 0, rd);
        B(2.9, 0.8, 0.02, MAT.accent, 0, 0.5, -0.26, rd, false);
        B(3.2, 0.05, 0.7, MAT.wood, 0, 1.025, -0.05, rd);
        B(0.5, 0.32, 0.03, MAT.screenFrame, -0.7, 1.26, 0.05, rd);
        tube(0.12, 0.015, 'y', MAT.steel, -0.7, 1.08, 0.05, rd);
        const rsTex = canvasTex(128, 80, (c, w, h) => { c.fillStyle = '#e6f1fb'; c.fillRect(0, 0, w, h); c.fillStyle = '#1f6fb8'; c.fillRect(0, 0, w, 14); c.fillStyle = '#334155'; for (let i = 0; i < 5; i++) c.fillRect(8, 24 + i * 11, 70 + (i % 2) * 30, 5); });
        const rs = new THREE.Mesh(new THREE.PlaneGeometry(0.46, 0.28), new THREE.MeshBasicMaterial({ map: rsTex })); rs.position.set(-0.7, 1.26, 0.07); rs.rotation.y = 0; rd.add(rs);
        B(0.4, 0.015, 0.14, MAT.dark, -0.7, 1.06, -0.15, rd, false);
        B(0.16, 0.06, 0.12, MAT.dark, 0.5, 1.08, -0.1, rd, false);
        plantPot(rd, 1.3, -0.05, 0.5).position.y = 1.05;
        const ch = new THREE.Group(); ch.position.set(-0.7, 0, 0.75); rd.add(ch);
        C(0.22, 0.06, MAT.dark, 0, 0.5, 0, ch, 16); C(0.025, 0.4, MAT.steel, 0, 0.27, 0, ch, 8); B(0.4, 0.4, 0.06, MAT.dark, 0, 0.8, 0.2, ch);
        // sign above reception
        const recTex = canvasTex(256, 64, (c, w, h) => { c.fillStyle = '#1f6fb8'; c.fillRect(0, 0, w, h); c.fillStyle = '#ffffff'; c.font = 'bold 34px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('RECEPTION', w / 2, h / 2 + 2); });
        wallPlane(scene, recTex, 1.6, 0.4, 5.1, 2.3, 1.835, Math.PI);

        // posters & directory (south wall)
        const post = (title, sub, col) => canvasTex(160, 220, (c, w, h) => {
            c.fillStyle = '#ffffff'; c.fillRect(0, 0, w, h); c.fillStyle = col; c.fillRect(0, 0, w, 44);
            c.fillStyle = '#ffffff'; c.font = 'bold 20px sans-serif'; c.textAlign = 'center'; c.fillText(title, w / 2, 29);
            c.fillStyle = col; c.beginPath(); c.arc(w / 2, 110, 36, 0, 6.28); c.fill();
            c.fillStyle = '#fff'; c.fillRect(w / 2 - 6, 88, 12, 44); c.fillRect(w / 2 - 22, 104, 44, 12);
            c.fillStyle = '#334155'; c.font = '15px sans-serif'; c.fillText(sub, w / 2, 180);
        });
        wallPlane(scene, post('WASH HANDS', '20 seconds', '#2d8fe5'), 0.5, 0.69, -2.4, 1.7, 1.835, Math.PI);
        wallPlane(scene, post('QUIET ZONE', 'Patients resting', '#16a34a'), 0.5, 0.69, -1.6, 1.7, 1.835, Math.PI);
        const dirTex = canvasTex(256, 160, (c, w, h) => {
            c.fillStyle = '#1f6fb8'; c.fillRect(0, 0, w, h); c.fillStyle = '#fff'; c.font = 'bold 24px sans-serif'; c.fillText('DIRECTORY', 14, 32);
            c.font = '20px sans-serif';['Rooms 101 · 102  ↑', 'Rooms 103 · 104  ↓', 'Reception  ←', 'Garden  →'].forEach((t, i) => c.fillText(t, 14, 66 + i * 24));
        });
        wallPlane(scene, dirTex, 0.9, 0.56, 3.0, 1.7, 1.835, Math.PI);

        // entrance: mat, water cooler, sanitiser stand
        const matTex = canvasTex(256, 128, (c, w, h) => { c.fillStyle = '#3b4551'; c.fillRect(0, 0, w, h); c.strokeStyle = '#94a3b8'; c.lineWidth = 4; c.strokeRect(6, 6, w - 12, h - 12); c.fillStyle = '#e2e8f0'; c.font = 'bold 40px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('WELCOME', w / 2, h / 2); });
        const mat = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 2.0), new THREE.MeshBasicMaterial({ map: matTex })); mat.rotation.x = -Math.PI / 2; mat.rotation.z = Math.PI / 2; mat.position.set(7.3, 0.012, 0); scene.add(mat);
        const wcool = new THREE.Group(); wcool.position.set(7.5, 0, 1.55); scene.add(wcool);
        B(0.32, 0.95, 0.32, MAT.white, 0, 0.475, 0, wcool); C(0.14, 0.4, MAT.bag, 0, 1.15, 0, wcool, 16); B(0.06, 0.05, 0.05, MAT.accent, 0, 0.8, -0.17, wcool, false);
        const ss = new THREE.Group(); ss.position.set(7.6, 0, -1.5); scene.add(ss);
        C(0.18, 0.03, MAT.steel, 0, 0.015, 0, ss, 16); C(0.025, 1.0, MAT.steel, 0, 0.5, 0, ss, 8); B(0.12, 0.22, 0.1, MAT.white, 0, 1.1, 0, ss); B(0.05, 0.05, 0.08, MAT.accent, 0, 1.2, -0.08, ss, false);

        // west end: bench (the archway to the reception wing is right beside it)
        chairRow(scene, -7.0, -1.52, 2, 0);
        const bin = new THREE.Group(); bin.position.set(-0.2, 0, 1.55); scene.add(bin);
        C(0.17, 0.5, MAT.steel, 0, 0.25, 0, bin, 14); C(0.18, 0.04, MAT.dark, 0, 0.52, 0, bin, 14);
    }

    // ─── Reception wing (west end of the corridor) ─────────
    // Local frame of the hall group (placed at the hall's centre):
    //   x: -H..+H = west (feature) wall .. corridor wall      z: -8..+8 = north .. south wall
    // Visitors come in through the archway on the +x side and walk west to the counter.
    function buildReception() {
        const H = REC.D / 2, Z = 8, EW = H + WALL_T / 2;      // EW = centre line of the shared corridor wall
        const rec = new THREE.Group(); rec.position.set(REC.cx, 0, 0); scene.add(rec);

        // base slab (extends the diorama base) + floor
        B(REC.D, 0.3, 17.6, MAT.concrete, -8.8 - REC.D / 2, -0.16, 0, scene, false);
        const fw = REC.D + 0.24;
        const floor = new THREE.Mesh(new THREE.PlaneGeometry(fw, 16.16), tiledMat(textures.lobby, fw, 16.16, 1.2, 0.22));
        floor.rotation.x = -Math.PI / 2; floor.position.set(0.04, 0, 0); floor.receiveShadow = true; rec.add(floor);

        // ── walls: glass north & south, solid feature wall west (the east wall is the corridor's) ──
        const WX = H + 0.16;
        buildWallX(rec, -WX, WX, -Z - WALL_T / 2, [], true, 1);
        buildWallX(rec, -WX, WX, Z + WALL_T / 2, [], true, -1);
        const west = new THREE.Group(); west.position.set(-H - WALL_T / 2, 0, 0); west.rotation.y = Math.PI / 2; rec.add(west);
        buildWallX(west, -(Z + WALL_T), Z + WALL_T, 0, [], false, 1);
        // skirting on the hall side of the corridor wall + archway frame
        [[-Z, -1.5], [1.5, Z]].forEach(([a, b]) => B(0.02, 0.12, b - a, MAT.base, H - 0.01, 0.06, (a + b) / 2, rec, false));
        [-1.55, 1.55].forEach(z => B(WALL_T + 0.06, 2.5, 0.1, MAT.accentDark, EW, 1.25, z, rec));
        B(WALL_T + 0.06, 0.1, 3.2, MAT.accentDark, EW, 2.55, 0, rec);

        // ── signage ──
        const bar = (txt, sub) => canvasTex(768, 128, (c, w, h) => {
            const gr = c.createLinearGradient(0, 0, w, 0); gr.addColorStop(0, '#1f6fb8'); gr.addColorStop(1, '#2d8fe5');
            c.fillStyle = gr; c.fillRect(0, 0, w, h);
            c.fillStyle = '#ffffff'; c.textAlign = 'center'; c.textBaseline = 'middle';
            c.font = 'bold 60px sans-serif'; c.fillText(txt, w / 2, sub ? 46 : 64);
            if (sub) { c.font = '28px sans-serif'; c.fillText(sub, w / 2, 98); }
        });
        wallPlane(rec, bar('RECEPTION', 'Registration · Information'), 2.4, 0.4, EW + WALL_T / 2 + 0.012, 2.8, 0, Math.PI / 2);   // corridor side
        wallPlane(rec, bar('WARDS 101 – 104  →'), 2.4, 0.4, EW - WALL_T / 2 - 0.012, 2.8, 0, -Math.PI / 2);                       // hall side
        const brand = canvasTex(1024, 192, (c, w, h) => {
            const gr = c.createLinearGradient(0, 0, w, 0); gr.addColorStop(0, '#1f6fb8'); gr.addColorStop(1, '#2d8fe5');
            c.fillStyle = gr; c.fillRect(0, 0, w, h);
            c.fillStyle = '#ffffff'; c.fillRect(76, 36, 28, 120); c.fillRect(30, 82, 120, 28);
            c.textBaseline = 'middle'; c.textAlign = 'left';
            c.font = 'bold 84px sans-serif'; c.fillText('HACKCURE CLINIC', 190, 84);
            c.font = '38px sans-serif'; c.fillText('Reception · Admission · Information', 192, 150);
        });
        wallPlane(rec, brand, 6.0, 1.125, -H + 0.012, 2.1, 0, Math.PI / 2);

        const wallScreen = (x, y, z, rotY, w, h, tex) => {
            const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = rotY; rec.add(g);
            B(w + 0.06, h + 0.06, 0.05, MAT.screenFrame, 0, 0, 0, g);
            const s = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex })); s.position.z = 0.03; g.add(s);
        };
        const queue = canvasTex(256, 144, (c, w, h) => {
            c.fillStyle = '#0b2a4a'; c.fillRect(0, 0, w, h); c.textAlign = 'center';
            c.fillStyle = '#7dd3fc'; c.font = '16px sans-serif'; c.fillText('NOW SERVING', w / 2, 30);
            c.fillStyle = '#ffffff'; c.font = 'bold 54px sans-serif'; c.fillText('A-017', w / 2, 84);
            c.fillStyle = '#7dd3fc'; c.font = '16px sans-serif'; c.fillText('Counter 2', w / 2, 120);
        });
        [-5.4, 5.4].forEach(z => wallScreen(-H + 0.04, 1.9, z, Math.PI / 2, 1.3, 0.73, queue));
        const tvTex = canvasTex(256, 144, (c, w, h) => {
            const gr = c.createLinearGradient(0, 0, w, h); gr.addColorStop(0, '#0e3a6b'); gr.addColorStop(1, '#2d8fe5');
            c.fillStyle = gr; c.fillRect(0, 0, w, h); c.fillStyle = 'rgba(255,255,255,0.92)'; c.textAlign = 'center';
            c.font = 'bold 22px sans-serif'; c.fillText('Welcome to HackCure', w / 2, 60);
            c.font = '13px sans-serif'; c.fillText('Please check in at a kiosk or the counter', w / 2, 90);
        });
        wallScreen(H - 0.04, 1.85, -5.6, -Math.PI / 2, 1.7, 0.96, tvTex);
        const dirTex = canvasTex(256, 160, (c, w, h) => {
            c.fillStyle = '#1f6fb8'; c.fillRect(0, 0, w, h); c.fillStyle = '#ffffff'; c.font = 'bold 24px sans-serif'; c.fillText('DIRECTORY', 14, 32);
            c.font = '19px sans-serif';['Rooms 101 · 102  (north)', 'Rooms 103 · 104  (south)', 'Corridor / Wards  →', 'Exit  →'].forEach((t, i) => c.fillText(t, 14, 66 + i * 24));
        });
        wallPlane(rec, dirTex, 0.9, 0.56, H - 0.012, 1.7, 3.6, -Math.PI / 2);

        // floor medallion on the walkway
        const medTex = canvasTex(256, 256, (c) => {
            c.fillStyle = '#e3eefa'; c.beginPath(); c.arc(128, 128, 126, 0, 6.283); c.fill();
            c.strokeStyle = '#2d8fe5'; c.lineWidth = 10; c.beginPath(); c.arc(128, 128, 112, 0, 6.283); c.stroke();
            c.fillStyle = '#2d8fe5'; c.fillRect(108, 58, 40, 140); c.fillRect(58, 108, 140, 40);
        });
        const med = new THREE.Mesh(new THREE.CircleGeometry(1.5, 48), new THREE.MeshBasicMaterial({ map: medTex, transparent: true, depthWrite: false }));
        med.rotation.x = -Math.PI / 2; med.position.set(1.0, 0.012, 0); rec.add(med);

        // ── reception counter (U-shaped) + staff side ──
        const dx = -H + 2.4;
        B(0.7, 1.0, 6.4, MAT.white, dx, 0.5, 0, rec);
        B(0.02, 0.8, 6.3, MAT.accent, dx + 0.36, 0.5, 0, rec, false);
        B(1.0, 0.05, 6.6, MAT.wood, dx + 0.05, 1.025, 0, rec);
        [-1, 1].forEach(s => { B(1.4, 0.72, 0.6, MAT.white, dx - 1.0, 0.36, s * 2.8, rec); B(1.5, 0.04, 0.7, MAT.wood, dx - 1.0, 0.74, s * 2.8, rec); });
        const rsTex = canvasTex(128, 80, (c, w, h) => { c.fillStyle = '#e6f1fb'; c.fillRect(0, 0, w, h); c.fillStyle = '#1f6fb8'; c.fillRect(0, 0, w, 14); c.fillStyle = '#334155'; for (let i = 0; i < 5; i++) c.fillRect(8, 24 + i * 11, 70 + (i % 2) * 30, 5); });
        [-1.7, 0, 1.7].forEach(z => {
            B(0.03, 0.34, 0.52, MAT.screenFrame, dx, 1.28, z, rec);
            tube(0.15, 0.015, 'y', MAT.steel, dx, 1.12, z, rec);
            const s = new THREE.Mesh(new THREE.PlaneGeometry(0.46, 0.28), new THREE.MeshBasicMaterial({ map: rsTex }));
            s.position.set(dx - 0.025, 1.28, z); s.rotation.y = -Math.PI / 2; rec.add(s);
            B(0.14, 0.015, 0.38, MAT.dark, dx - 0.28, 1.06, z, rec, false);
            const ch = new THREE.Group(); ch.position.set(dx - 0.95, 0, z); rec.add(ch);
            C(0.22, 0.06, MAT.dark, 0, 0.58, 0, ch, 16); C(0.025, 0.45, MAT.steel, 0, 0.3, 0, ch, 8); C(0.26, 0.03, MAT.steel, 0, 0.03, 0, ch, 5);
            B(0.06, 0.42, 0.4, MAT.dark, -0.2, 0.88, 0, ch);
        });
        C(0.06, 0.03, MAT.steel, dx + 0.3, 1.065, 1.0, rec, 14);                                    // service bell
        C(0.07, 0.24, MAT.white, dx + 0.3, 1.17, -2.7, rec, 14);                                    // flower vase
        [0xf472b6, 0xfacc15, 0xf8fafc, 0xa855f7].forEach((c, i) => mesh(new THREE.SphereGeometry(0.07, 8, 6), std(c, { roughness: 0.8 }), dx + 0.3 + Math.cos(i * 1.6) * 0.06, 1.37 + (i % 2) * 0.05, -2.7 + Math.sin(i * 1.6) * 0.06, rec, false));
        B(0.1, 0.26, 0.1, MAT.white, dx + 0.3, 1.18, 2.7, rec); B(0.04, 0.05, 0.08, MAT.accent, dx + 0.25, 1.26, 2.7, rec, false);   // sanitiser
        // storage wall behind the counter
        for (let i = -2; i <= 2; i++) {
            const z = i * 1.08;
            B(0.5, 0.9, 1.04, MAT.white, -H + 0.3, 0.45, z, rec);
            [0.27, 0.62].forEach(y => { B(0.02, 0.28, 0.9, MAT.accent, -H + 0.56, y, z, rec, false); B(0.02, 0.03, 0.2, MAT.steel, -H + 0.575, y + 0.08, z, rec, false); });
        }
        B(0.56, 0.04, 5.5, MAT.wood, -H + 0.3, 0.92, 0, rec);
        B(0.4, 0.22, 0.38, MAT.dark, -H + 0.3, 1.05, -1.4, rec);                                     // printer

        // ── north lounge ──
        const sofa = (x, z, rotY, len) => {
            const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; rec.add(g);
            B(len, 0.22, 0.85, MAT.dark, 0, 0.11, 0, g);
            B(len - 0.3, 0.16, 0.7, MAT.chairBlue, 0, 0.3, 0.06, g);
            B(len, 0.5, 0.18, MAT.chairBlue, 0, 0.6, -0.34, g);
            [-1, 1].forEach(s => B(0.16, 0.42, 0.85, MAT.chairBlue, s * (len / 2 - 0.08), 0.43, 0, g));
        };
        B(3.8, 0.012, 3.6, std(0xcfe3f5, { roughness: 1 }), 1.2, 0.006, -5.65, rec, false);       // rug
        sofa(1.2, -7.0, 0, 2.1); sofa(1.2, -4.3, Math.PI, 2.1);
        sofa(-0.45, -5.65, Math.PI / 2, 1.0); sofa(2.85, -5.65, -Math.PI / 2, 1.0);
        C(0.45, 0.04, MAT.white, 1.2, 0.42, -5.65, rec, 28); C(0.04, 0.4, MAT.steel, 1.2, 0.2, -5.65, rec, 8); C(0.3, 0.02, MAT.dark, 1.2, 0.01, -5.65, rec, 20);
        [0xdc2626, 0x2563eb, 0xeab308].forEach((c, i) => { const m = B(0.22, 0.012, 0.3, std(c), 1.2 + (i - 1) * 0.1, 0.45 + i * 0.012, -5.65, rec, false); m.rotation.y = i * 0.6; });

        // ── south waiting rows (facing the counter) + kids' corner ──
        [0.6, 2.4].forEach(x => chairRow(rec, x, 3.7, 5, -Math.PI / 2));
        B(2.8, 0.012, 2.4, std(0xfde68a, { roughness: 1 }), -1.8, 0.006, 5.6, rec, false);
        [[0xef4444, -2.6, 5.2], [0x3b82f6, -2.2, 6.1], [0x22c55e, -1.2, 5.0], [0xeab308, -1.0, 6.2]].forEach(([c, x, z], i) => { const b = B(0.34, 0.34, 0.34, std(c, { roughness: 0.7 }), x, 0.17, z, rec); b.rotation.y = i * 0.7; });
        B(0.9, 0.4, 0.6, MAT.wood, -1.8, 0.2, 5.6, rec);

        // ── check-in kiosks flanking the walkway ──
        const kioskTex = canvasTex(160, 112, (c, w, h) => {
            c.fillStyle = '#e6f1fb'; c.fillRect(0, 0, w, h); c.fillStyle = '#1f6fb8'; c.fillRect(0, 0, w, 26);
            c.fillStyle = '#ffffff'; c.font = 'bold 16px sans-serif'; c.textAlign = 'center'; c.fillText('CHECK-IN', w / 2, 19);
            c.fillStyle = '#2d8fe5'; c.fillRect(26, 48, 108, 34); c.fillStyle = '#ffffff'; c.font = '15px sans-serif'; c.fillText('Tap to start', w / 2, 70);
        });
        [-2.7, 2.7].forEach(z => {
            const k = new THREE.Group(); k.position.set(H - 2.1, 0, z); k.rotation.y = Math.PI / 2; rec.add(k);
            C(0.24, 0.03, MAT.dark, 0, 0.015, 0, k, 18); B(0.12, 1.0, 0.1, MAT.white, 0, 0.53, 0, k);
            const head = B(0.56, 0.42, 0.06, MAT.screenFrame, 0, 1.2, 0.02, k); head.rotation.x = -0.25;
            const s = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.36), new THREE.MeshBasicMaterial({ map: kioskTex })); s.position.z = 0.032; head.add(s);
        });

        // ── east wall: vending machine, water cooler ──
        const vm = new THREE.Group(); vm.position.set(H - 0.42, 0, 6.2); vm.rotation.y = -Math.PI / 2; rec.add(vm);
        B(1.0, 1.85, 0.8, MAT.accentDark, 0, 0.925, 0, vm);
        const vg = B(0.62, 1.3, 0.02, MAT.glass, -0.14, 1.05, 0.41, vm, false); vg.renderOrder = 2;
        [0xef4444, 0xfacc15, 0x22c55e, 0x3b82f6, 0xf97316].forEach((c, i) => B(0.5, 0.07, 0.03, std(c), -0.14, 1.55 - i * 0.22, 0.395, vm, false));
        B(0.2, 0.55, 0.02, MAT.dark, 0.33, 1.15, 0.41, vm, false); B(0.5, 0.14, 0.02, MAT.dark, -0.14, 0.2, 0.41, vm, false);
        const wc = new THREE.Group(); wc.position.set(H - 0.22, 0, 4.9); rec.add(wc);
        B(0.32, 0.95, 0.32, MAT.white, 0, 0.475, 0, wc); C(0.14, 0.4, MAT.bag, 0, 1.15, 0, wc, 16); B(0.05, 0.05, 0.06, MAT.accent, -0.17, 0.8, 0, wc, false);

        // ── plants along the glass ──
        plantPot(rec, H - 0.8, -7.2, 1.3); plantPot(rec, -H + 1.2, -7.2, 1.2);
        plantPot(rec, H - 0.8, 7.2, 1.3); plantPot(rec, -H + 1.2, 7.2, 1.2);

        // ── lighting ──
        [[-2.2, 0, 0.3], [2.5, -5.5, 0.22], [2.5, 5.5, 0.22]].forEach(([x, z, i]) => {
            const l = new THREE.PointLight(0xfff4e0, i, 11); l.position.set(x, 2.7, z); rec.add(l);
        });
    }

    function zoomToReception() {
        moveCameraTo(new THREE.Vector3(REC.cx + REC.D / 2 - 0.8, 2.6, 7.2), new THREE.Vector3(REC.cx - 1.5, 0.8, -1.0), 0.8, 66);
        const ov = document.getElementById('cctv-overlay'); if (ov) ov.classList.add('cctv-hidden');
    }

    function init() {
        try {
            container = document.getElementById('three-container');
            if (!container) return;
            buildMaterials(); buildTextures(); buildGardenMaterials(); buildGardenTextures();

            scene = new THREE.Scene();
            scene.background = new THREE.Color(0xbfe0f7);

            const cp = CAMERA_POSITIONS.overview;
            camera = new THREE.PerspectiveCamera(cp.fov, container.clientWidth / container.clientHeight, 0.3, 400);
            camera.position.set(...cp.pos); camera.lookAt(...cp.target);
            window._hackcureCamera = camera;   // used by app.js click-picking

            renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
            renderer.setSize(container.clientWidth, container.clientHeight);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            renderer.shadowMap.enabled = true;
            renderer.shadowMap.type = THREE.PCFSoftShadowMap;
            renderer.outputEncoding = THREE.sRGBEncoding;
            renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15;
            container.appendChild(renderer.domElement);

            controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true; controls.dampingFactor = 0.06;
            controls.maxPolarAngle = Math.PI / 2.05;
            controls.minDistance = 1; controls.maxDistance = 60;
            controls.target.set(...cp.target);

            createLighting();
            buildShell();
            buildExterior();
            Object.keys(ROOMS).forEach(id => buildRoom(id, ROOMS[id]));

            window.addEventListener('resize', onResize);
            renderer.domElement.addEventListener('dblclick', onDoubleClick);
            addRoomButtons();
            animate();
        } catch (err) {
            console.error('SCENE INIT ERROR:', err);
            if (container) container.innerHTML = `<div style="color:#f87171;padding:20px;font-family:monospace"><h3>3D SCENE ERROR</h3>${err.message}<pre>${err.stack}</pre></div>`;
        }
    }

    function animate() {
        animationId = requestAnimationFrame(animate);
        const now = performance.now();
        stepTween(now);
        controls.update();

        if (now - lastVitalsSync > 500) { lastVitalsSync = now; syncVitals(); }
        if (now - lastMonitorDraw > 66) {
            lastMonitorDraw = now;
            monitors.forEach(m => { m.hr += (m.targetHr - m.hr) * 0.08; drawMonitor(m, now / 1000); m.tex.needsUpdate = true; });
        }
        const dt = Math.min((now - (animate.last || now)) / 1000, 0.1); animate.last = now;
        animateExterior(now / 1000, dt);
        if (typeof AvatarManager !== 'undefined') AvatarManager.update(dt);
        renderer.render(scene, camera);
    }

    function onResize() {
        if (!container || !camera || !renderer) return;
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
    }

    // ─── Camera ────────────────────────────────────────────
    function moveCameraTo(pos, target, duration = 1.0, fov = 45) {
        camTween = {
            t0: performance.now(), dur: duration * 1000,
            p0: camera.position.clone(), p1: pos.clone(),
            c0: controls.target.clone(), c1: target.clone(),
            f0: camera.fov, f1: fov,
        };
    }
    function stepTween(now) {
        if (!camTween) return;
        const k = Math.min((now - camTween.t0) / camTween.dur, 1);
        const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        camera.position.lerpVectors(camTween.p0, camTween.p1, e);
        controls.target.lerpVectors(camTween.c0, camTween.c1, e);
        camera.fov = camTween.f0 + (camTween.f1 - camTween.f0) * e;
        camera.updateProjectionMatrix();
        if (k >= 1) camTween = null;
    }

    function focusOnPatient(patientId) {
        const patient = PatientStateManager.getPatient(patientId);
        const room = patient && roomGroups[patient.room];
        if (!room) return;
        room.updateMatrixWorld(true);
        const pos = room.localToWorld(new THREE.Vector3(CCTV_LOCAL.x, CCTV_LOCAL.y - 0.1, CCTV_LOCAL.z - 0.1));
        const target = room.localToWorld(new THREE.Vector3(BED.x + 0.35, 0.6, BED.z + 0.25));
        moveCameraTo(pos, target, 0.7, 62);
    }
    // Wide view from inside the room's corner, then orbit/scroll freely
    function zoomToRoom(roomId) {
        const room = roomGroups[roomId]; if (!room) return;
        room.updateMatrixWorld(true);
        const pos = room.localToWorld(new THREE.Vector3(0.0, 2.6, 2.7));
        const target = room.localToWorld(new THREE.Vector3(-1.2, 0.7, -1.6));
        moveCameraTo(pos, target, 0.8, 66);
        const ov = document.getElementById('cctv-overlay'); if (ov) ov.classList.add('cctv-hidden');
    }

    // Double-click anything (bed, monitor, curtain, patient...) to fly in close to it
    const _ray = new THREE.Raycaster(), _m = new THREE.Vector2();
    function onDoubleClick(ev) {
        const r = renderer.domElement.getBoundingClientRect();
        _m.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
        _ray.setFromCamera(_m, camera);
        const hit = _ray.intersectObjects(scene.children, true).find(h =>
            h.object.isMesh && h.object.geometry.type !== 'RingGeometry' &&
            !(h.object.material.transparent && h.object.material.opacity < 0.9));
        if (!hit) return;
        const p = hit.point.clone();
        const dir = camera.position.clone().sub(p).normalize();
        const pos = p.clone().add(dir.multiplyScalar(2.4));
        pos.y = Math.max(pos.y, 0.8);
        moveCameraTo(pos, p, 0.7, 50);
        const ov = document.getElementById('cctv-overlay'); if (ov) ov.classList.add('cctv-hidden');
    }

    function addRoomButtons() {
        const bar = document.getElementById('camera-controls');
        if (!bar || bar.dataset.rooms) return;
        bar.dataset.rooms = '1';
        Object.keys(ROOMS).forEach(id => {
            const b = document.createElement('button');
            b.className = 'cam-btn'; b.title = 'Zoom to room ' + id; b.textContent = id;
            b.style.cssText = 'font-size:11px;font-weight:700;width:auto;padding:0 8px';
            b.addEventListener('click', () => zoomToRoom(id));
            bar.appendChild(b);
        });
        const rb = document.createElement('button');
        rb.className = 'cam-btn'; rb.title = 'Zoom to reception'; rb.textContent = 'REC';
        rb.style.cssText = 'font-size:11px;font-weight:700;width:auto;padding:0 8px';
        rb.addEventListener('click', zoomToReception);
        bar.appendChild(rb);
    }

    const V = (a) => new THREE.Vector3(a[0], a[1], a[2]);
    function resetCamera() { const c = CAMERA_POSITIONS.overview; moveCameraTo(V(c.pos), V(c.target), 0.8, c.fov); }
    function topDownView() { const c = CAMERA_POSITIONS.topdown; moveCameraTo(V(c.pos), V(c.target), 0.8, c.fov); }

    // ─── Public helpers (used by avatars.js) ───────────────
    function getScene() { return scene; }
    function getCamera() { return camera; }
    function getBedParts(roomId) { return bedParts[roomId] || null; }
    function getBedWorldPosition(roomId) {
        const r = ROOMS[roomId]; if (!r) return { x: 0, z: 0, rotY: 0 };
        const c = Math.cos(r.rotY), s = Math.sin(r.rotY);
        return { x: r.x + BED.x * c + BED.z * s, z: r.z - BED.x * s + BED.z * c, rotY: r.rotY };
    }
    function dispose() {
        cancelAnimationFrame(animationId);
        window.removeEventListener('resize', onResize);
        renderer.dispose();
    }

    return { init, getScene, getCamera, getBedParts, getBedWorldPosition, focusOnPatient, zoomToRoom, zoomToReception, resetCamera, topDownView, dispose, BED };
})();