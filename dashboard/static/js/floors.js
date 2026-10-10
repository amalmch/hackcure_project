/**
 * HackCure — Étage 1, salles spécialisées, machines médicales, vues isolées & visite à pied
 * ==========================================================================================
 * Ce module s'appuie sur scene.js (qui lui passe ses outils via HospitalFloors.init(api)).
 *
 *  RDC      : les 4 chambres + couloir + réception existants (inchangés)
 *  ÉTAGE 1  : RAD (Radiologie : IRM + table RX)   DIA (Dialyse : 3 postes)
 *             PHA (Pharmacie)                      EQP (Salle des machines : ECG, tension,
 *                                                  sérum, température, nutrition, déchets)
 *
 *  Interface (panneau en bas à gauche) :
 *    RDC / Étage 1 / Tout / Éclaté   -> choisir l'étage affiché
 *    puces de salles                 -> isole UNE salle (les autres disparaissent) + caméra
 *    Intérieur / Marcher ici         -> entrer dans la salle isolée
 *    Visite à pied                   -> ZQSD / WASD, glisser = regarder, Maj = courir,
 *                                       E = ascenseur (RDC <-> étage), Échap = quitter
 *
 *  Repère local d'une salle (identique à scene.js) : x -4..4, z -3..3,
 *  -z = mur du fond, +z = côté couloir (porte en x = 2.6).
 */

const HospitalFloors = (() => {
    'use strict';

    // ─── Constantes ───────────────────────────────────────
    const FY = 3.36;                         // altitude du plancher de l'étage (dalle 0,30 m sur les murs du RDC)
    const EYE = 1.62, RADIUS = 0.3;
    const DOOR = { x: 2.6, w: 1.3, h: 2.1 };
    const WINDOW = { x0: 1.6, x1: 3.2, sill: 0.95, top: 2.35 };
    const SLOTS = {
        NW: { x: -4, z: -5, rotY: 0 }, NE: { x: 4, z: -5, rotY: 0 },
        SW: { x: -4, z: 5, rotY: Math.PI }, SE: { x: 4, z: 5, rotY: Math.PI },
    };
    const LIFT = { x: -7.0, z: 0, yaw: -Math.PI / 2 };   // hall de l'ascenseur (extrémité ouest du couloir)

    let A = null;
    let B, C, tube, rbox, std, MAT, WT, WH;
    let upper, slab, roof, shell, headlamp;
    const regs = {};            // id -> { id, name, floor, group, cfg }
    const screens = [];         // écrans animés (canvas)
    const anims = [];           // (t, dt) => void
    const hidden = [];

    // ─── Petits outils ────────────────────────────────────
    const V3 = (x, y, z) => new THREE.Vector3(x, y, z);
    const basic = (c, o = {}) => new THREE.MeshBasicMaterial(Object.assign({ color: c }, o));
    const glassM = (c = 0xd7efff, op = 0.3) => new THREE.MeshStandardMaterial({ color: c, transparent: true, opacity: op, roughness: 0.05, depthWrite: false });
    const vis = (o) => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
    const gauss = (p, mu, s, a) => a * Math.exp(-Math.pow((p - mu) / s, 2));
    const cyc = (t, hr) => { const per = 60 / hr; return (((t % per) + per) % per) / per; };
    const ecgW = (t, hr) => { const p = cyc(t, hr); return gauss(p, .12, .035, .12) + gauss(p, .2, .012, -.12) + gauss(p, .22, .014, 1) + gauss(p, .25, .014, -.25) + gauss(p, .42, .05, .22); };
    const plethW = (t, hr) => { const p = cyc(t, hr); return gauss(p, .2, .09, .9) + gauss(p, .5, .1, .3) - .25; };
    const ease = (k) => k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    const rnd = (() => { let s = 9173; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); })();

    function put(parent, g, x, y, z, ry) { g.position.set(x || 0, y || 0, z || 0); if (ry) g.rotation.y = ry; parent.add(g); return g; }
    function T(c, s, x, y, size, col, bold, align) { c.fillStyle = col; c.font = (bold ? 'bold ' : '') + size + 'px sans-serif'; c.textAlign = align || 'left'; c.textBaseline = 'middle'; c.fillText(s, x, y); }
    function noCollide(o) { o.userData.noCollide = true; return o; }

    // Écran animé : draw(ctx, W, H, t) rappelé ~12 fps tant que l'écran est visible
    function addScreen(parent, w, h, x, y, z, draw, opt = {}) {
        const pw = opt.pw || 256, ph = opt.ph || Math.round(pw * h / w);
        const canvas = document.createElement('canvas'); canvas.width = pw; canvas.height = ph;
        const g = canvas.getContext('2d');
        const tex = new THREE.CanvasTexture(canvas); tex.encoding = THREE.sRGBEncoding;
        const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex }));
        m.position.set(x, y, z); if (opt.ry) m.rotation.y = opt.ry; if (opt.rx) m.rotation.x = opt.rx;
        noCollide(m); parent.add(m);
        const s = { g, tex, draw, w: pw, h: ph, every: opt.every || 90, last: -1e9, mesh: m };
        draw(g, pw, ph, 0); tex.needsUpdate = true;
        screens.push(s);
        return m;
    }

    function signTex(title, sub, bg, w = 384, h = 128) {
        return A.canvasTex(w, h, (g) => {
            g.fillStyle = bg; g.fillRect(0, 0, w, h);
            g.fillStyle = 'rgba(255,255,255,0.2)'; g.fillRect(0, h - 8, w, 8);
            g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = '#fff';
            g.font = 'bold ' + (sub ? 44 : 52) + 'px sans-serif'; g.fillText(title, w / 2, sub ? h * 0.4 : h / 2);
            if (sub) { g.font = '24px sans-serif'; g.fillStyle = 'rgba(255,255,255,0.88)'; g.fillText(sub, w / 2, h * 0.76); }
        });
    }
    function sign(parent, tex, w, h, x, y, z, ry, rx) {
        const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex }));
        m.position.set(x, y, z); m.rotation.y = ry || 0; if (rx) m.rotation.x = rx; noCollide(m); parent.add(m); return m;
    }
    function hose(parent, pts, color, r = 0.008) {
        const curve = new THREE.CatmullRomCurve3(pts.map(p => V3(p[0], p[1], p[2])));
        const m = new THREE.Mesh(new THREE.TubeGeometry(curve, 28, r, 6, false), std(color, { roughness: 0.35 }));
        m.castShadow = false; noCollide(m); parent.add(m); return m;
    }
    function wheels(g, hx, hz, y = 0.045) {
        [[-hx, -hz], [hx, -hz], [-hx, hz], [hx, hz]].forEach(([x, z]) => { const w = C(0.045, 0.04, MAT.dark, x, y, z, g, 10); w.rotation.z = Math.PI / 2; });
    }
    function starBase(g, r = 0.3) {
        B(0.08, 0.05, 0.08, MAT.steel, 0, 0.08, 0, g);
        for (let i = 0; i < 5; i++) { const a = i * Math.PI * 2 / 5; const l = B(r, 0.025, 0.04, MAT.steel, Math.cos(a) * r / 2, 0.07, Math.sin(a) * r / 2, g); l.rotation.y = -a; C(0.03, 0.04, MAT.dark, Math.cos(a) * r, 0.03, Math.sin(a) * r, g, 8); }
    }
    // Boîte à niveau de liquide ancrée en bas (scale.y = remplissage)
    function liquid(parent, geo, color, x, y, z, op = 0.9) {
        geo.translate(0, geo.parameters.height / 2, 0);
        const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color, transparent: true, opacity: op, roughness: 0.2 }));
        m.position.set(x, y, z); noCollide(m); parent.add(m); return m;
    }

    // ═══════════════════════════════════════════════════════
    //  MACHINES MÉDICALES (origine au sol, face visible vers +z)
    // ═══════════════════════════════════════════════════════

    // ── 1. Cardiologie : moniteur ECG sur chariot ──
    function drawECG(c, W, H, t) {
        c.fillStyle = '#03101a'; c.fillRect(0, 0, W, H);
        c.fillStyle = '#0e3a52'; c.fillRect(0, 0, W, 20);
        T(c, 'CARDIOLOGIE  ·  ECG', 8, 10, 12, '#fff', true);
        const hr = 72 + 6 * Math.sin(t * 0.35), plotW = W * 0.68;
        [['II', 0.36, '#22ff7a', 21, ecgW], ['V1', 0.62, '#38bdf8', 15, (tt, h) => ecgW(tt, h) * 0.7 - 0.05], ['SpO2', 0.87, '#facc15', 10, plethW]].forEach(([n, fy, col, amp, f]) => {
            const y0 = H * fy;
            T(c, n, 4, y0 - amp - 3, 9, col, true);
            c.strokeStyle = col; c.lineWidth = 2; c.beginPath();
            for (let x = 0; x <= plotW; x += 2) { const y = y0 - f(t - (plotW - x) / 55, hr) * amp; x === 0 ? c.moveTo(x, y) : c.lineTo(x, y); }
            c.stroke();
        });
        T(c, String(Math.round(hr)), W * 0.72, H * 0.34, 38, '#22ff7a', true);
        T(c, 'bpm', W * 0.72, H * 0.52, 12, '#9fb3c8');
        T(c, 'SpO2 ' + Math.round(97 + Math.sin(t * 0.2)) + '%', W * 0.72, H * 0.68, 15, '#38bdf8', true);
        T(c, 'PR 160 ms', W * 0.72, H * 0.82, 11, '#9fb3c8');
        T(c, 'QRS 90 ms', W * 0.72, H * 0.92, 11, '#9fb3c8');
    }
    function machineECG() {
        const g = new THREE.Group();
        B(0.6, 0.05, 0.6, MAT.steel, 0, 0.1, 0, g); wheels(g, 0.28, 0.28);
        C(0.035, 1.0, MAT.steel, 0, 0.62, 0, g, 10);
        B(0.56, 0.4, 0.09, MAT.white, 0, 1.3, 0, g);
        B(0.5, 0.34, 0.012, MAT.screenFrame, 0, 1.3, 0.05, g, false);
        addScreen(g, 0.46, 0.3, 0, 1.3, 0.058, drawECG, { pw: 256, every: 70 });
        B(0.36, 0.12, 0.26, MAT.white, 0, 0.82, 0.03, g);           // imprimante
        B(0.28, 0.01, 0.1, basic(0xffffff), 0, 0.885, 0.12, g, false);
        B(0.3, 0.02, 0.2, MAT.accent, 0, 0.74, 0.03, g, false);
        // câbles patient (5 dérivations)
        [0xdc2626, 0xeab308, 0x16a34a, 0x111827, 0xf8fafc].forEach((col, i) => {
            hose(g, [[0.28, 1.2, 0.0], [0.4 + i * 0.03, 0.9, 0.1 + i * 0.04], [0.5 + i * 0.05, 0.55, 0.2 + i * 0.05], [0.55 + i * 0.07, 0.2, 0.3 + i * 0.05]], col, 0.007);
        });
        return g;
    }

    // ── 2. Tension artérielle : tensiomètre automatique + bras de démonstration ──
    function bpState(t) { const p = t % 24; return p < 9 ? { s: 0, pr: 170 * p / 9 } : p < 18 ? { s: 1, pr: 170 * (1 - (p - 9) / 9) } : { s: 2, pr: 0 }; }
    function drawBP(c, W, H, t) {
        c.fillStyle = '#04141f'; c.fillRect(0, 0, W, H);
        c.fillStyle = '#0e3a52'; c.fillRect(0, 0, W, 20);
        T(c, 'TENSION ARTÉRIELLE', 8, 10, 12, '#fff', true);
        const st = bpState(t), n = Math.floor(t / 24);
        const sys = 112 + (n * 7) % 14, dia = 70 + (n * 5) % 9, pul = 66 + (n * 3) % 10;
        if (st.s === 2) {
            T(c, 'SYS', 10, H * 0.34, 12, '#9fb3c8'); T(c, String(sys), 50, H * 0.36, 44, '#22ff7a', true);
            T(c, 'DIA', 10, H * 0.7, 12, '#9fb3c8'); T(c, String(dia), 50, H * 0.72, 44, '#38bdf8', true);
            T(c, 'mmHg', W - 60, H * 0.36, 13, '#9fb3c8'); T(c, '♥ ' + pul, W - 70, H * 0.72, 20, '#f87171', true);
        } else {
            T(c, st.s === 0 ? 'GONFLAGE…' : 'DÉGONFLAGE…', 10, H * 0.3, 14, '#facc15', true);
            T(c, String(Math.round(st.pr)), 14, H * 0.62, 52, '#e2e8f0', true); T(c, 'mmHg', W - 70, H * 0.62, 14, '#9fb3c8');
            c.fillStyle = '#16384d'; c.fillRect(10, H - 20, W - 20, 8); c.fillStyle = '#22c55e'; c.fillRect(10, H - 20, (W - 20) * st.pr / 180, 8);
        }
    }
    function machineBP() {
        const g = new THREE.Group();
        starBase(g, 0.3);
        C(0.025, 1.15, MAT.steel, 0, 0.65, 0, g, 8);
        B(0.5, 0.34, 0.16, MAT.white, 0, 1.3, 0, g);
        B(0.42, 0.26, 0.012, MAT.screenFrame, 0, 1.32, 0.085, g, false);
        addScreen(g, 0.38, 0.22, 0, 1.32, 0.093, drawBP, { pw: 256, every: 100 });
        [-0.15, 0, 0.15].forEach(x => B(0.06, 0.025, 0.012, x === 0 ? MAT.green : MAT.accent, x, 1.16, 0.085, g, false));
        // table + bras
        const tb = new THREE.Group(); tb.position.set(0.85, 0, 0.1); g.add(tb);
        B(0.6, 0.04, 0.42, MAT.white, 0, 0.78, 0, tb); C(0.03, 0.76, MAT.steel, 0, 0.38, 0, tb, 8); B(0.4, 0.03, 0.3, MAT.steel, 0, 0.02, 0, tb);
        const armG = new THREE.Group(); armG.position.set(0, 0.86, 0); tb.add(armG);
        const arm = C(0.045, 0.52, std(0xe8bca1), 0, 0, 0, armG, 14); arm.rotation.z = Math.PI / 2;
        const cuff = C(0.057, 0.17, MAT.accent, -0.02, 0, 0, armG, 20); cuff.rotation.z = Math.PI / 2;
        C(0.04, 0.17, MAT.accentDark, -0.02, 0, 0, armG, 12).rotation.z = Math.PI / 2;
        hose(g, [[0.82, 0.9, 0.1], [0.55, 0.95, 0.1], [0.3, 1.05, 0.06], [0.1, 1.2, 0.08]], 0x2a3440, 0.01);
        // tensiomètre manuel (cadran)
        const dial = C(0.05, 0.02, MAT.steel, 0.2, 0.815, 0.05, tb, 20); dial.rotation.x = Math.PI / 2;
        const face = new THREE.Mesh(new THREE.CircleGeometry(0.045, 20), basic(0xf8fafc)); face.position.set(0.2, 0.815, 0.062); noCollide(face); tb.add(face);
        const needle = B(0.003, 0.035, 0.002, MAT.red, 0.2, 0.815, 0.064, tb, false);
        anims.push((t) => {
            const st = bpState(t);
            const k = 1 + 0.26 * (st.pr / 170); cuff.scale.set(k, 1, k);
            needle.rotation.z = -st.pr / 170 * 4.2; needle.position.x = 0.2 + Math.sin(needle.rotation.z) * 0.0;
        });
        return g;
    }

    // ── 3. Sérum : pied à perfusion + pompe volumétrique ──
    function drawPump(c, W, H, t) {
        c.fillStyle = '#041a24'; c.fillRect(0, 0, W, H);
        c.fillStyle = '#0e3a52'; c.fillRect(0, 0, W, 22);
        T(c, 'PERFUSION', 8, 11, 13, '#fff', true);
        const lvl = 1 - ((t % 120) / 120) * 0.8, done = Math.round(1000 * (1 - lvl)), run = Math.floor(t * 2) % 2 === 0;
        T(c, '125', 10, H * 0.46, 44, '#22ff7a', true); T(c, 'mL/h', 108, H * 0.52, 14, '#9fb3c8');
        T(c, 'Volume perfusé : ' + done + ' mL', 10, H * 0.76, 13, '#e2e8f0');
        c.fillStyle = '#16384d'; c.fillRect(10, H - 18, W - 20, 8); c.fillStyle = '#38bdf8'; c.fillRect(10, H - 18, (W - 20) * (1 - lvl) / 0.8, 8);
        c.fillStyle = run ? '#22c55e' : '#14532d'; c.beginPath(); c.arc(W - 20, 11, 6, 0, 6.28); c.fill();
    }
    function machineIV() {
        const g = new THREE.Group();
        starBase(g, 0.32);
        C(0.015, 2.05, MAT.steel, 0, 1.05, 0, g, 8);
        B(0.56, 0.025, 0.025, MAT.steel, 0, 2.08, 0, g);
        const levels = [], drops = [];
        [[-0.22, 'NaCl 0,9 %', '#1f6fb8', 0xcfe8ff], [0.22, 'Glucose 5 %', '#b45309', 0xfff0c2]].forEach(([x, name, col, liq], i) => {
            C(0.008, 0.1, MAT.steel, x, 2.03, 0, g, 6);
            const bag = new THREE.Group(); bag.position.set(x, 1.78, 0); g.add(bag);
            rbox(0.19, 0.3, 0.05, 0.05, MAT.bag, 0, 0, 0, bag);
            const lv = liquid(bag, new THREE.BoxGeometry(0.16, 0.24, 0.035), liq, 0, -0.135, 0, 0.9); levels.push(lv);
            sign(bag, A.canvasTex(128, 96, (c, w, h) => { c.fillStyle = '#fff'; c.fillRect(0, 0, w, h); c.fillStyle = col; c.fillRect(0, 0, w, 20); T(c, 'SÉRUM', w / 2, 10, 14, '#fff', true, 'center'); T(c, name, w / 2, 52, 18, col, true, 'center'); T(c, '500 mL', w / 2, 78, 14, '#475569', false, 'center'); }), 0.14, 0.1, 0, 0.07, 0.03);
            C(0.012, 0.03, MAT.accent, x, 1.6, 0, g, 8);                                     // embout
            C(0.024, 0.1, glassM(), x, 1.52, 0, g, 12);                                        // chambre compte-gouttes
            const d = new THREE.Mesh(new THREE.SphereGeometry(0.008, 8, 6), basic(0x8fd3ff)); noCollide(d); d.position.set(x, 1.52, 0); g.add(d); drops.push(d);
            hose(g, [[x, 1.47, 0], [x * 0.6, 1.3, 0.03], [x * 0.2, 1.18, 0.08]], 0xe6f6ff, 0.006);
        });
        // pompe
        B(0.3, 0.24, 0.18, MAT.white, 0, 1.08, 0.1, g); B(0.08, 0.1, 0.1, MAT.steel, 0, 1.08, 0.0, g);
        B(0.26, 0.13, 0.012, MAT.screenFrame, 0, 1.12, 0.193, g, false);
        addScreen(g, 0.24, 0.115, 0, 1.12, 0.2, drawPump, { pw: 256, every: 200 });
        const leds = [-0.1, 0, 0.1].map(x => { const l = new THREE.Mesh(new THREE.SphereGeometry(0.01, 8, 6), basic(0x22c55e)); noCollide(l); l.position.set(x, 1.0, 0.195); g.add(l); return l; });
        hose(g, [[0, 1.0, 0.12], [0.1, 0.9, 0.3], [0.3, 0.85, 0.5], [0.55, 0.9, 0.62]], 0xe6f6ff, 0.006);
        anims.push((t) => {
            levels.forEach((lv, i) => lv.scale.y = Math.max(0.12, 1 - ((t % 120) / 120) * 0.8));
            drops.forEach((d, i) => { const k = (t * 1.5 + i * 0.5) % 1; d.position.y = 1.56 - k * 0.08; d.visible = k < 0.9; });
            leds.forEach((l, i) => l.material.color.setHex(Math.floor(t * 2 + i) % 3 === 0 ? 0x16a34a : 0x14532d));
        });
        return g;
    }

    // ── 4. Température : moniteur + thermomètre infrarouge ──
    const tempAt = (t) => 37.1 + 1.5 * Math.sin(t * 0.15);
    function drawTemp(c, W, H, t) {
        const T0 = tempAt(t);
        const col = T0 < 36 ? '#60a5fa' : T0 < 37.8 ? '#22ff7a' : T0 < 38.5 ? '#facc15' : '#f87171';
        const lab = T0 < 36 ? 'HYPOTHERMIE' : T0 < 37.8 ? 'NORMALE' : T0 < 38.5 ? 'FÉBRILE' : 'FIÈVRE';
        c.fillStyle = '#04141f'; c.fillRect(0, 0, W, H);
        c.fillStyle = '#0e3a52'; c.fillRect(0, 0, W, 20);
        T(c, 'TEMPÉRATURE', 8, 10, 12, '#fff', true); T(c, lab, W - 8, 10, 11, col, true, 'right');
        T(c, T0.toFixed(1), 10, H * 0.42, 54, col, true); T(c, '°C', 150, H * 0.34, 20, '#9fb3c8', true);
        c.strokeStyle = '#16384d'; c.lineWidth = 1; for (let i = 0; i < 3; i++) { c.beginPath(); c.moveTo(8, H * 0.7 + i * 10 - 10); c.lineTo(W - 8, H * 0.7 + i * 10 - 10); c.stroke(); }
        c.strokeStyle = col; c.lineWidth = 2; c.beginPath();
        for (let x = 0; x <= W - 16; x += 3) { const v = tempAt(t - (W - 16 - x) * 0.6); const y = H * 0.9 - (v - 35.5) / 3.2 * H * 0.35; x === 0 ? c.moveTo(8 + x, y) : c.lineTo(8 + x, y); }
        c.stroke();
        T(c, '24 h', 8, H - 6, 9, '#6b8196');
    }
    function machineTemp() {
        const g = new THREE.Group();
        starBase(g, 0.28); C(0.022, 1.0, MAT.steel, 0, 0.58, 0, g, 8);
        B(0.46, 0.3, 0.09, MAT.white, 0, 1.2, 0, g); B(0.4, 0.24, 0.01, MAT.screenFrame, 0, 1.2, 0.05, g, false);
        addScreen(g, 0.36, 0.22, 0, 1.2, 0.057, drawTemp, { pw: 256, every: 150 });
        // table + thermomètre frontal infrarouge sur son socle
        const tb = new THREE.Group(); tb.position.set(0.7, 0, 0.1); g.add(tb);
        B(0.5, 0.04, 0.4, MAT.white, 0, 0.78, 0, tb); C(0.03, 0.76, MAT.steel, 0, 0.38, 0, tb, 8); B(0.36, 0.03, 0.28, MAT.steel, 0, 0.02, 0, tb);
        B(0.14, 0.02, 0.12, MAT.dark, -0.1, 0.81, 0, tb);
        const ir = new THREE.Group(); ir.position.set(-0.1, 0.9, 0); ir.rotation.y = 0.5; tb.add(ir);
        B(0.045, 0.045, 0.16, MAT.white, 0, 0.03, 0, ir); B(0.04, 0.09, 0.04, MAT.white, 0, -0.03, -0.05, ir);
        B(0.03, 0.03, 0.03, MAT.accent, 0, 0.03, 0.095, ir);
        B(0.03, 0.02, 0.012, MAT.screenFrame, 0, 0.056, -0.02, ir, false);
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.008, 8, 6), basic(0xff2222)); noCollide(dot); dot.position.set(0, 0.03, 0.115); ir.add(dot);
        // sonde numérique
        tube(0.16, 0.006, 'x', MAT.steel, 0.12, 0.805, 0.05, tb); C(0.012, 0.03, MAT.accent, 0.21, 0.805, 0.05, tb, 8).rotation.z = Math.PI / 2;
        hose(g, [[0.82, 0.82, 0.15], [0.5, 0.8, 0.2], [0.25, 1.0, 0.1], [0.12, 1.1, 0.05]], 0x2a3440, 0.006);
        anims.push((t) => { dot.visible = Math.floor(t * 3) % 8 !== 0; });
        return g;
    }

    // ── 5. Distribution nutrition : eau / vitamines / nutrition ──
    const NUT = [{ n: 'EAU', c: 0x8fd0ff, s: '#2d8fe5' }, { n: 'VITAMINES', c: 0xffa63d, s: '#d97706' }, { n: 'NUTRITION', c: 0xfff0c9, s: '#16a34a' }];
    function drawNut(c, W, H, t) {
        const k = Math.floor((t / 5) % 3), loc = (t % 5) / 3;
        c.fillStyle = '#04141f'; c.fillRect(0, 0, W, H);
        c.fillStyle = '#0e3a52'; c.fillRect(0, 0, W, 22);
        T(c, 'DISTRIBUTION NUTRITION', 8, 11, 13, '#fff', true);
        NUT.forEach((n, i) => {
            const y = 32 + i * (H - 36) / 3, on = i === k && loc < 1;
            c.fillStyle = on ? n.s : '#16384d'; c.fillRect(8, y, W - 16, (H - 36) / 3 - 5);
            T(c, n.n + (on ? '  ▶ ' + Math.round(250 * loc) + ' mL' : '  prêt'), 16, y + (H - 36) / 6 - 3, 14, '#fff', true);
        });
    }
    function machineNutrition() {
        const g = new THREE.Group();
        B(0.98, 1.9, 0.5, MAT.white, 0, 0.95, 0, g);
        B(0.98, 0.1, 0.52, MAT.accent, 0, 1.87, 0, g); B(0.98, 0.08, 0.52, MAT.accent, 0, 0.04, 0, g);
        B(0.9, 0.3, 0.012, MAT.screenFrame, 0, 1.62, 0.256, g, false);
        addScreen(g, 0.86, 0.26, 0, 1.62, 0.264, drawNut, { pw: 384, every: 120 });
        B(0.9, 0.62, 0.012, MAT.screenFrame, 0, 1.12, 0.254, g, false);           // fond de la vitrine
        const lvls = [], streams = [], fills = [];
        NUT.forEach((n, i) => {
            const x = (i - 1) * 0.3;
            const tank = C(0.1, 0.5, glassM(0xdff1ff, 0.22), x, 1.12, 0.2, g, 20); noCollide(tank);
            lvls.push(liquid(g, new THREE.CylinderGeometry(0.092, 0.092, 0.46, 20), n.c, x, 0.89, 0.2, 0.92));
            sign(g, signTex(n.n, '', n.s, 160, 48), 0.22, 0.066, x, 1.43, 0.262);
            C(0.012, 0.07, MAT.steel, x, 0.83, 0.2, g, 8);
            const st = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 1, 6), basic(n.c)); noCollide(st); st.position.set(x, 0.8, 0.2); st.visible = false; g.add(st); streams.push(st);
            // gobelet
            C(0.045, 0.12, glassM(0xffffff, 0.25), x, 0.62, 0.2, g, 14);
            fills.push(liquid(g, new THREE.CylinderGeometry(0.04, 0.04, 0.1, 14), n.c, x, 0.565, 0.2, 0.95));
        });
        B(0.92, 0.03, 0.26, MAT.steel, 0, 0.545, 0.2, g);
        anims.push((t) => {
            const k = Math.floor((t / 5) % 3), loc = (t % 5) / 3;
            NUT.forEach((n, i) => {
                lvls[i].scale.y = 1 - (((t / 45) + i / 3) % 1) * 0.6;
                const on = i === k && loc < 1;
                streams[i].visible = on;
                if (on) { const len = 0.2 * Math.min(1, loc * 4); streams[i].scale.y = Math.max(0.01, len); streams[i].position.y = 0.8 - len / 2; }
                fills[i].scale.y = on ? Math.max(0.02, loc) : (i === k ? 1 : fills[i].scale.y > 0.02 ? fills[i].scale.y : 1);
                if (i === k && loc >= 1) fills[i].scale.y = 1;
            });
        });
        return g;
    }

    // ── 6. Déchets humains : poche à urine, diurèse, collecteurs DASRI ──
    function drawUro(c, W, H, t) {
        const lvl = 0.12 + 0.6 * ((t / 60) % 1), ml = Math.round(lvl * 1500);
        c.fillStyle = '#04141f'; c.fillRect(0, 0, W, H);
        c.fillStyle = '#0e3a52'; c.fillRect(0, 0, W, 20);
        T(c, 'DIURÈSE', 8, 10, 12, '#fff', true);
        T(c, String(ml), 10, H * 0.42, 40, '#facc15', true); T(c, 'mL', 130, H * 0.5, 14, '#9fb3c8');
        T(c, 'Débit : ' + (38 + Math.round(8 * Math.sin(t * 0.3))) + ' mL/h', 10, H * 0.74, 13, '#e2e8f0');
        T(c, 'Aspect : clair', 10, H * 0.9, 11, '#22ff7a');
    }
    function biohazardTex(bg) {
        return A.canvasTex(128, 128, (c, w, h) => {
            c.fillStyle = bg; c.fillRect(0, 0, w, h); c.strokeStyle = '#111'; c.fillStyle = '#111'; c.lineWidth = 7;
            for (let i = 0; i < 3; i++) { const a = i * Math.PI * 2 / 3 - Math.PI / 2; c.beginPath(); c.arc(64 + Math.cos(a) * 24, 64 + Math.sin(a) * 24, 20, 0, 6.28); c.stroke(); }
            c.beginPath(); c.arc(64, 64, 7, 0, 6.28); c.fill();
        });
    }
    function machineWaste() {
        const g = new THREE.Group();
        // lit (coupe) : le sac pend à la barrière
        const bed = new THREE.Group(); g.add(bed);
        B(0.7, 0.18, 1.6, MAT.white, 0, 0.3, 0, bed); B(1.0, 0.07, 2.1, MAT.steel, 0, 0.63, 0, bed);
        [[-0.38, -0.85], [0.38, -0.85], [-0.38, 0.85], [0.38, 0.85]].forEach(([x, z]) => { const w = C(0.07, 0.05, MAT.dark, x, 0.07, z, bed, 12); w.rotation.z = Math.PI / 2; });
        B(0.92, 0.16, 2.0, MAT.sheet, 0, 0.8, 0, bed);
        const bl = B(0.96, 0.14, 1.2, MAT.blanket, 0, 0.9, 0.35, bed);
        rbox(0.5, 0.08, 0.32, 0.035, MAT.white, 0, 0.92, -0.8, bed);
        rbox(1.04, 0.7, 0.07, 0.1, MAT.white, 0, 0.77, -1.08, bed); rbox(1.04, 0.5, 0.07, 0.1, MAT.white, 0, 0.67, 1.08, bed);
        [-0.54, 0.54].forEach(x => { tube(1.0, 0.025, 'z', MAT.white, x, 1.14, -0.2, bed); tube(1.0, 0.02, 'z', MAT.white, x, 0.92, -0.2, bed); C(0.03, 0.4, MAT.white, x, 1.0, -0.7, bed, 8); C(0.03, 0.4, MAT.white, x, 1.0, 0.3, bed, 8); });
        // poche collectrice
        const bag = new THREE.Group(); bag.position.set(0.62, 0.52, 0.1); bed.add(bag);
        B(0.03, 0.03, 0.03, MAT.steel, -0.04, 0.34, 0, bag); B(0.012, 0.2, 0.012, MAT.steel, -0.04, 0.24, 0, bag);
        B(0.04, 0.3, 0.2, MAT.bag, 0, 0, 0, bag);
        const lv = liquid(bag, new THREE.BoxGeometry(0.03, 0.25, 0.17), 0xf2c94c, 0, -0.14, 0, 0.92);
        sign(bag, A.canvasTex(64, 128, (c, w, h) => { c.fillStyle = 'rgba(255,255,255,0.0)'; c.fillRect(0, 0, w, h); c.strokeStyle = '#1f2937'; c.fillStyle = '#1f2937'; c.lineWidth = 2; c.font = '10px sans-serif'; for (let i = 0; i <= 6; i++) { const y = 112 - i * 16; c.beginPath(); c.moveTo(34, y); c.lineTo(i % 2 ? 50 : 58, y); c.stroke(); if (i % 2 === 0) c.fillText(String(i * 250), 6, y + 3); } }), 0.17, 0.28, 0.022, 0, 0, Math.PI / 2);
        C(0.012, 0.04, MAT.accent, 0, -0.17, 0, bag, 8);
        hose(bed, [[0.3, 0.9, 0.1], [0.5, 0.72, 0.1], [0.6, 0.8, 0.1], [0.62, 0.84, 0.1]], 0xe6f6ff, 0.007);
        // moniteur de diurèse
        const p = new THREE.Group(); p.position.set(1.0, 0, 0.1); g.add(p);
        starBase(p, 0.25); C(0.02, 1.0, MAT.steel, 0, 0.58, 0, p, 8); B(0.38, 0.26, 0.08, MAT.white, 0, 1.15, 0, p); B(0.33, 0.2, 0.01, MAT.screenFrame, 0, 1.15, 0.045, p, false);
        addScreen(p, 0.3, 0.17, 0, 1.15, 0.052, drawUro, { pw: 256, every: 300 });
        // collecteurs DASRI
        const bin = new THREE.Group(); bin.position.set(1.0, 0, -0.9); g.add(bin);
        B(0.42, 0.62, 0.38, MAT.yellow, 0, 0.31, 0, bin); B(0.44, 0.06, 0.4, MAT.dark, 0, 0.65, 0, bin); B(0.18, 0.02, 0.04, MAT.black, 0, 0.69, 0, bin, false);
        sign(bin, biohazardTex('#facc15'), 0.26, 0.26, 0, 0.35, 0.196);
        const bin2 = new THREE.Group(); bin2.position.set(1.0, 0, -1.4); g.add(bin2);
        C(0.17, 0.5, MAT.red, 0, 0.25, 0, bin2, 18); C(0.18, 0.05, MAT.dark, 0, 0.52, 0, bin2, 18);
        const fl = new THREE.Mesh(new THREE.PlaneGeometry(0.22, 0.22), new THREE.MeshBasicMaterial({ map: biohazardTex('#dc2626') })); fl.position.set(0, 0.28, 0.173); noCollide(fl); bin2.add(fl);
        // collecteur d'aiguilles murale
        B(0.16, 0.22, 0.12, MAT.yellow, 1.35, 1.1, -1.2, g); B(0.12, 0.03, 0.09, MAT.red, 1.35, 1.23, -1.2, g);
        anims.push((t) => { lv.scale.y = 0.12 + 0.6 * ((t / 60) % 1); });
        return g;
    }

    const MACHINES = { ecg: machineECG, bp: machineBP, iv: machineIV, temp: machineTemp, nutrition: machineNutrition, waste: machineWaste };

    // ═══════════════════════════════════════════════════════
    //  DIALYSE
    // ═══════════════════════════════════════════════════════
    function drawDialysis(c, W, H, t) {
        const total = 4 * 3600, left = total - ((t * 40) % total);
        const hh = Math.floor(left / 3600), mm = Math.floor((left % 3600) / 60);
        c.fillStyle = '#041a24'; c.fillRect(0, 0, W, H);
        c.fillStyle = '#0e5a52'; c.fillRect(0, 0, W, 22);
        T(c, 'HÉMODIALYSE', 8, 11, 13, '#fff', true);
        c.fillStyle = Math.floor(t * 1.5) % 2 ? '#22c55e' : '#14532d'; c.beginPath(); c.arc(W - 16, 11, 6, 0, 6.28); c.fill();
        T(c, hh + ':' + String(mm).padStart(2, '0'), 10, H * 0.37, 36, '#22ff7a', true); T(c, 'restant', 112, H * 0.4, 12, '#9fb3c8');
        const rows = [['Qb', '300 mL/min'], ['Qd', '500 mL/min'], ['UF', (2.1 * (1 - left / total)).toFixed(2) + ' / 2.1 L'], ['P art', Math.round(-170 + 6 * Math.sin(t * 2)) + ' mmHg'], ['P vein', Math.round(140 + 5 * Math.sin(t * 1.7)) + ' mmHg']];
        rows.forEach(([a, b], i) => { T(c, a, 10, H * 0.58 + i * 11, 10, '#9fb3c8'); T(c, b, 70, H * 0.58 + i * 11, 10, '#e2e8f0', true); });
        c.strokeStyle = '#ef4444'; c.lineWidth = 1.5; c.beginPath();
        for (let x = 0; x < 80; x += 2) { const y = H * 0.4 + Math.sin((t * 4 - x * 0.2)) * 6; x === 0 ? c.moveTo(W - 88 + x, y + 40) : c.lineTo(W - 88 + x, y + 40); }
        c.stroke();
    }
    function machineDialysis(armTarget) {
        const g = new THREE.Group();
        B(0.58, 0.82, 0.5, MAT.white, 0, 0.46, 0, g); wheels(g, 0.25, 0.2, 0.05);
        B(0.58, 0.05, 0.52, MAT.accent, 0, 0.9, 0, g);
        B(0.58, 0.55, 0.14, MAT.white, 0, 1.2, 0.18, g);                       // module sang
        B(0.5, 0.42, 0.01, std(0xe5eef7), 0, 1.2, 0.257, g, false);
        C(0.025, 0.4, MAT.steel, 0, 1.65, -0.05, g, 8);
        const mon = new THREE.Group(); mon.position.set(0, 1.85, -0.02); mon.rotation.x = -0.2; g.add(mon);
        B(0.48, 0.32, 0.06, MAT.white, 0, 0, 0, mon); B(0.42, 0.26, 0.01, MAT.screenFrame, 0, 0, 0.033, mon, false);
        addScreen(mon, 0.4, 0.24, 0, 0, 0.04, drawDialysis, { pw: 320, every: 160 });
        // pompe à sang (rotor rouge) + pompe à héparine
        const rotor = new THREE.Group(); rotor.position.set(-0.14, 1.28, 0.27); g.add(rotor);
        const hub = C(0.07, 0.03, MAT.red, 0, 0, 0, rotor, 16); hub.rotation.x = Math.PI / 2;
        [0, 1].forEach(i => { const r = B(0.14, 0.02, 0.02, MAT.steel, 0, 0, 0.02, rotor); r.rotation.z = i * Math.PI / 2; });
        B(0.3, 0.1, 0.04, MAT.steel, -0.14, 1.28, 0.265, g, false);
        C(0.016, 0.1, MAT.sheet, 0.12, 1.02, 0.28, g, 8).rotation.z = Math.PI / 2;
        // dialyseur + chambres
        C(0.04, 0.3, glassM(0xffffff, 0.45), 0.2, 1.22, 0.3, g, 16);
        C(0.044, 0.03, MAT.red, 0.2, 1.39, 0.3, g, 16); C(0.044, 0.03, MAT.accent, 0.2, 1.05, 0.3, g, 16);
        C(0.018, 0.08, glassM(), -0.02, 1.4, 0.29, g, 10); C(0.018, 0.08, glassM(), 0.02, 1.1, 0.29, g, 10);
        // circuit extracorporel : artère (rouge) / veine (bleu)
        hose(g, [[armTarget[0], armTarget[1], armTarget[2]], [armTarget[0] * 0.6, armTarget[1] - 0.12, armTarget[2] + 0.1], [-0.2, 1.0, 0.3], [-0.14, 1.28, 0.31], [0.1, 1.4, 0.3], [0.2, 1.4, 0.3]], 0xdc2626, 0.008);
        hose(g, [[0.2, 1.05, 0.3], [0.15, 0.95, 0.32], [armTarget[0] * 0.5, armTarget[1] - 0.15, armTarget[2] + 0.15], [armTarget[0], armTarget[1] + 0.01, armTarget[2] + 0.04]], 0x2563eb, 0.008);
        // bidons de dialysat
        B(0.18, 0.28, 0.14, glassM(0xffffff, 0.7), 0.37, 0.6, -0.02, g); C(0.03, 0.03, MAT.accent, 0.37, 0.76, -0.02, g, 10);
        B(0.18, 0.28, 0.14, glassM(0xffffff, 0.7), 0.37, 0.28, -0.02, g); C(0.03, 0.03, MAT.red, 0.37, 0.44, -0.02, g, 10);
        const ph = rnd() * 6;
        anims.push((t) => { rotor.rotation.z = -(t * 3 + ph); });
        return g;
    }
    function recliner() {
        const g = new THREE.Group(), vinyl = std(0x2d8fe5, { roughness: 0.7 });
        B(0.5, 0.22, 0.7, MAT.dark, 0, 0.12, 0, g); C(0.06, 0.28, MAT.steel, 0, 0.3, 0, g, 10);
        B(0.62, 0.12, 0.62, vinyl, 0, 0.5, 0, g);
        const back = new THREE.Group(); back.position.set(0, 0.52, -0.3); back.rotation.x = -0.82; g.add(back);
        B(0.62, 0.8, 0.12, vinyl, 0, 0.4, 0, back); B(0.34, 0.16, 0.1, vinyl, 0, 0.88, 0.0, back);
        const leg = new THREE.Group(); leg.position.set(0, 0.5, 0.31); leg.rotation.x = -1.1; g.add(leg);
        B(0.54, 0.5, 0.1, vinyl, 0, -0.26, 0, leg);
        [-0.38, 0.38].forEach(x => { B(0.08, 0.05, 0.5, vinyl, x, 0.68, -0.02, g); B(0.05, 0.2, 0.05, MAT.steel, x, 0.58, 0.18, g); });
        B(0.34, 0.03, 0.26, MAT.white, -0.55, 0.72, 0.1, g);               // tablette
        return g;
    }

    // ═══════════════════════════════════════════════════════
    //  RADIOLOGIE
    // ═══════════════════════════════════════════════════════
    function drawBrain(c, W, H, t) {
        c.fillStyle = '#000'; c.fillRect(0, 0, W, H);
        const cx = W * 0.5, cy = H * 0.52, rx = H * 0.36, ry = H * 0.42;
        c.strokeStyle = '#d8dde3'; c.lineWidth = 5; c.beginPath(); c.ellipse(cx, cy, rx, ry, 0, 0, 6.283); c.stroke();
        const gr = c.createRadialGradient(cx, cy, 4, cx, cy, rx); gr.addColorStop(0, '#a3acb6'); gr.addColorStop(1, '#4b5560');
        c.fillStyle = gr; c.beginPath(); c.ellipse(cx, cy, rx - 6, ry - 6, 0, 0, 6.283); c.fill();
        c.strokeStyle = 'rgba(20,25,30,0.55)'; c.lineWidth = 2;
        for (let i = 0; i < 16; i++) { const a = i * 0.9; c.beginPath(); c.arc(cx + Math.cos(a) * rx * 0.4, cy + Math.sin(a) * ry * 0.4, 6 + ((i * 13) % 9), a, a + 2.2); c.stroke(); }
        c.fillStyle = '#0c1218'; c.beginPath(); c.ellipse(cx - 8, cy - 4, 6, 14, 0.2, 0, 6.283); c.fill();
        c.beginPath(); c.ellipse(cx + 8, cy - 4, 6, 14, -0.2, 0, 6.283); c.fill();
        const k = (t * 0.4) % 1; c.fillStyle = 'rgba(56,189,248,0.28)'; c.fillRect(0, k * H - 2, W, 4);
        T(c, 'IRM CÉRÉBRALE · T2', 6, 10, 10, '#38bdf8', true); T(c, 'coupe ' + (1 + Math.floor(k * 32)) + '/32', 6, H - 8, 10, '#9fb3c8');
    }
    function drawChest(c, W, H, t) {
        c.fillStyle = '#000'; c.fillRect(0, 0, W, H);
        const cx = W * 0.5;
        c.fillStyle = '#2a2f36'; c.beginPath(); c.ellipse(cx - 34, H * 0.5, 30, 46, 0.1, 0, 6.283); c.fill();
        c.beginPath(); c.ellipse(cx + 34, H * 0.5, 30, 46, -0.1, 0, 6.283); c.fill();
        c.strokeStyle = 'rgba(230,235,240,0.7)'; c.lineWidth = 2;
        for (let i = 0; i < 7; i++) { const y = H * 0.22 + i * 11; c.beginPath(); c.moveTo(cx - 8, y); c.quadraticCurveTo(cx - 70, y - 14, cx - 74, y + 22); c.moveTo(cx + 8, y); c.quadraticCurveTo(cx + 70, y - 14, cx + 74, y + 22); c.stroke(); }
        c.strokeStyle = '#e5e7eb'; c.lineWidth = 7; c.beginPath(); c.moveTo(cx, H * 0.1); c.lineTo(cx, H * 0.9); c.stroke();
        c.fillStyle = 'rgba(190,198,206,0.8)'; c.beginPath(); c.ellipse(cx + 12, H * 0.58, 20, 24, 0.3, 0, 6.283); c.fill();
        T(c, 'RX THORAX F', 6, 10, 10, '#38bdf8', true); T(c, Math.floor(t * 2) % 2 ? 'ACQUISITION…' : '', 6, H - 8, 10, '#facc15', true);
    }
    function drawers(parent, x, z, w, ry) {
        const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = ry || 0; parent.add(g);
        B(w, 0.85, 0.5, MAT.white, 0, 0.425, 0, g); B(w, 0.04, 0.54, MAT.steel, 0, 0.87, 0, g);
        sign(g, A.canvasTex(512, 128, (c, ww, hh) => { c.fillStyle = '#eef3f8'; c.fillRect(0, 0, ww, hh); c.strokeStyle = '#9fb3c8'; c.lineWidth = 2; const n = Math.round(w / 0.55); for (let i = 0; i < n; i++) for (let j = 0; j < 3; j++) { c.strokeRect(i * ww / n + 3, j * hh / 3 + 3, ww / n - 6, hh / 3 - 6); c.fillStyle = '#7b8da0'; c.fillRect(i * ww / n + ww / n / 2 - 14, j * hh / 3 + hh / 6 - 2, 28, 4); } }), w - 0.04, 0.78, 0, 0.425, 0.256);
        return g;
    }
    function mriScanner() {
        const g = new THREE.Group();
        const W = 2.0, H = 2.15, r = 0.5, hw = W / 2, hh = H / 2, s = new THREE.Shape();
        s.moveTo(-hw + r, -hh); s.lineTo(hw - r, -hh); s.quadraticCurveTo(hw, -hh, hw, -hh + r); s.lineTo(hw, hh - r); s.quadraticCurveTo(hw, hh, hw - r, hh);
        s.lineTo(-hw + r, hh); s.quadraticCurveTo(-hw, hh, -hw, hh - r); s.lineTo(-hw, -hh + r); s.quadraticCurveTo(-hw, -hh, -hw + r, -hh);
        const hole = new THREE.Path(); hole.absarc(0, 0, 0.46, 0, Math.PI * 2, true); s.holes.push(hole);
        const geo = new THREE.ExtrudeGeometry(s, { depth: 1.3, bevelEnabled: false, curveSegments: 40 }); geo.translate(0, 0, -0.65);
        const body = new THREE.Mesh(geo, std(0xeef3f8, { roughness: 0.3 })); body.position.y = 1.1; body.castShadow = body.receiveShadow = true; g.add(body);
        const ringGeo = new THREE.RingGeometry(0.5, 0.78, 56);
        [0.652, -0.652].forEach(z => { const rg = new THREE.Mesh(ringGeo, MAT.accent); rg.position.set(0, 1.1, z); if (z < 0) rg.rotation.y = Math.PI; noCollide(rg); g.add(rg); });
        const glowMat = basic(0x9fe0ff, { transparent: true, opacity: 0.6 });
        const glow = new THREE.Mesh(new THREE.TorusGeometry(0.455, 0.014, 8, 56), glowMat); glow.position.set(0, 1.1, 0.64); noCollide(glow); g.add(glow);
        B(0.5, 0.2, 0.01, MAT.screenFrame, 0.6, 1.9, 0.655, g, false);
        B(1.7, 0.18, 1.2, MAT.dark, 0, 0.09, 0, g);
        // table : piédestal fixe + plateau coulissant + patient
        B(0.8, 0.5, 0.7, MAT.white, 0, 0.45, 1.5, g); B(0.9, 0.3, 0.8, MAT.dark, 0, 0.15, 1.5, g, false); B(0.82, 0.06, 0.72, MAT.accent, 0, 0.72, 1.5, g, false);
        const tbl = new THREE.Group(); g.add(tbl);
        B(0.56, 0.07, 1.7, MAT.white, 0, 0.8, 0.65, tbl); rbox(0.5, 0.05, 1.5, 0.02, MAT.chairBlue, 0, 0.86, 0.65, tbl).castShadow = false;
        const gown = std(0x9ac7f2, { roughness: 0.85 }), skin = std(0xe8bca1);
        const torso = C(0.17, 0.62, gown, 0, 0.98, 0.78, tbl, 16); torso.rotation.x = Math.PI / 2; torso.scale.x = 1.35;
        mesh3(new THREE.SphereGeometry(0.11, 16, 12), skin, 0, 0.99, 0.32, tbl);
        [-0.07, 0.07].forEach(x => { const l = C(0.07, 0.7, std(0x6fa8dc), x, 0.94, 1.4, tbl, 12); l.rotation.x = Math.PI / 2; });
        [-0.24, 0.24].forEach(x => { const a = C(0.045, 0.5, gown, x, 0.95, 0.8, tbl, 10); a.rotation.x = Math.PI / 2; });
        anims.push((t) => {
            const p = t % 26; let k = 0;
            if (p >= 3 && p < 7) k = ease((p - 3) / 4); else if (p >= 7 && p < 19) k = 1; else if (p >= 19 && p < 23) k = 1 - ease((p - 19) / 4);
            tbl.position.z = 1.0 - 1.35 * k;
            glowMat.opacity = k > 0.99 ? 0.55 + 0.4 * Math.sin(t * 9) : 0.45;
        });
        return g;
    }
    function mesh3(geo, m, x, y, z, parent) { const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.castShadow = true; parent.add(o); return o; }

    // ═══════════════════════════════════════════════════════
    //  PHARMACIE
    // ═══════════════════════════════════════════════════════
    const PILL = [0xf8fafc, 0x2d8fe5, 0x16a34a, 0xf59e0b, 0xdc2626, 0x14b8a6, 0xa855f7, 0xe5e7eb];
    function shelfUnit(parent, w, h, d, rows, x, z, ry) {
        const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = ry || 0; parent.add(g);
        B(0.04, h, d, MAT.white, -w / 2, h / 2, 0, g); B(0.04, h, d, MAT.white, w / 2, h / 2, 0, g);
        B(w, h, 0.02, std(0x2f6fb5, { roughness: 0.8 }), 0, h / 2, -d / 2 + 0.01, g, false);
        B(w, 0.1, d, MAT.white, 0, 0.05, 0, g);
        const boxes = [], bottles = [];
        for (let r = 0; r < rows; r++) {
            const y = 0.14 + r * (h - 0.2) / rows;
            B(w, 0.03, d, MAT.white, 0, y, 0, g, false);
            let x0 = -w / 2 + 0.08; const rh = (h - 0.2) / rows - 0.06;
            while (x0 < w / 2 - 0.1) {
                if (rnd() < 0.3) { const rr = 0.028 + rnd() * 0.012, hh2 = Math.min(rh, 0.1 + rnd() * 0.06); bottles.push([x0 + rr, y + 0.015 + hh2 / 2, rr, hh2, rnd()]); x0 += rr * 2 + 0.01; }
                else { const bw = 0.07 + rnd() * 0.07, bh = Math.min(rh, 0.08 + rnd() * 0.07); boxes.push([x0 + bw / 2, y + 0.015 + bh / 2, bw, bh, rnd()]); x0 += bw + 0.008; }
            }
        }
        const im = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ roughness: 0.6 }), boxes.length), dm = new THREE.Object3D();
        boxes.forEach((b, i) => { dm.position.set(b[0], b[1], -d / 2 + 0.03 + d * 0.3); dm.scale.set(b[2], b[3], d * 0.6); dm.updateMatrix(); im.setMatrixAt(i, dm.matrix); im.setColorAt(i, new THREE.Color(PILL[Math.floor(b[4] * PILL.length)])); });
        im.userData.noCollide = true; g.add(im);
        const cm = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 10), new THREE.MeshStandardMaterial({ roughness: 0.35 }), bottles.length);
        bottles.forEach((b, i) => { dm.position.set(b[0], b[1], -d / 2 + 0.05 + d * 0.28); dm.scale.set(b[2], b[3], b[2]); dm.updateMatrix(); cm.setMatrixAt(i, dm.matrix); cm.setColorAt(i, new THREE.Color(b[4] < 0.5 ? 0xf59e0b : 0xe5e7eb)); });
        cm.userData.noCollide = true; g.add(cm);
        return g;
    }
    function crossTex() {
        return A.canvasTex(128, 128, (c, w, h) => { c.fillStyle = '#0b3b1e'; c.fillRect(0, 0, w, h); c.fillStyle = '#22ff7a'; c.fillRect(w / 2 - 14, 18, 28, 92); c.fillRect(18, h / 2 - 14, 92, 28); });
    }

    // ═══════════════════════════════════════════════════════
    //  Salles de l'étage
    // ═══════════════════════════════════════════════════════
    function doorFor(room, name, color) {
        const x0 = DOOR.x - DOOR.w / 2, x1 = DOOR.x + DOOR.w / 2, zc = 3 + WT / 2;
        B(0.08, DOOR.h, WT + 0.06, MAT.accentDark, x0 - 0.04, DOOR.h / 2, zc, room); B(0.08, DOOR.h, WT + 0.06, MAT.accentDark, x1 + 0.04, DOOR.h / 2, zc, room);
        B(DOOR.w + 0.16, 0.08, WT + 0.06, MAT.accentDark, DOOR.x, DOOR.h + 0.04, zc, room);
        const hinge = new THREE.Group(); hinge.position.set(x1, 0, zc); hinge.rotation.y = 1.15; room.add(hinge);
        const L = DOOR.w - 0.03;
        B(L, DOOR.h - 0.03, 0.05, MAT.white, -L / 2, (DOOR.h - 0.03) / 2, 0, hinge); B(L * 0.7, 1.2, 0.055, MAT.accent, -L / 2, 0.85, 0, hinge, false);
        B(0.3, 0.6, 0.056, MAT.glass, -L / 2, 1.7, 0, hinge, false).renderOrder = 2; B(0.14, 0.03, 0.08, MAT.steel, -L + 0.12, 1.0, 0, hinge, false);
        sign(room, signTex(name, '', color, 384, 128), 1.2, 0.4, DOOR.x, 2.55, 3 + WT + 0.012);
    }

    function newRoom(def) {
        const cfg = SLOTS[def.slot], topRow = cfg.rotY === 0, room = new THREE.Group();
        const fl = new THREE.Mesh(new THREE.PlaneGeometry(8, 6), def.floor); fl.rotation.x = -Math.PI / 2; fl.position.y = 0.005; fl.receiveShadow = true; noCollide(fl); room.add(fl);
        const win = def.window !== false;
        A.buildWallX(room, -4, 4, -3 - WT / 2, win ? [{ x0: WINDOW.x0, x1: WINDOW.x1, sill: WINDOW.sill, top: WINDOW.top }] : [], !topRow, 1);
        A.buildWallX(room, -4, 4, 3 + WT / 2, [{ x0: DOOR.x - DOOR.w / 2, x1: DOOR.x + DOOR.w / 2, sill: 0, top: DOOR.h }], topRow, -1);
        if (win && topRow) {
            const cx = (WINDOW.x0 + WINDOW.x1) / 2, w = WINDOW.x1 - WINDOW.x0, h = WINDOW.top - WINDOW.sill, zc = -3 - WT / 2;
            B(w, h, 0.03, MAT.glass, cx, WINDOW.sill + h / 2, zc, room, false).renderOrder = 2;
            B(w + 0.12, 0.06, 0.2, MAT.white, cx, WINDOW.top + 0.03, zc, room); B(w + 0.12, 0.06, 0.2, MAT.white, cx, WINDOW.sill - 0.03, zc, room);
            B(0.06, h, 0.2, MAT.white, cx, WINDOW.sill + h / 2, zc, room);
        }
        doorFor(room, def.name.toUpperCase(), def.color);
        const light = new THREE.PointLight(0xfff4e0, 0.32, 10); light.position.set(-0.5, 2.7, -0.3); room.add(light);
        def.build(room);
        room.position.set(cfg.x, 0, cfg.z); room.rotation.y = cfg.rotY;
        upper.add(room);
        regs[def.id] = { id: def.id, name: def.name, floor: 1, group: room, cfg };
        return room;
    }

    function buildRadiology(room) {
        drawers(room, -1.6, -2.7, 4.6, 0);
        // table de radiographie + colonne du tube
        const tab = new THREE.Group(); tab.position.set(-1.7, 0, -0.2); room.add(tab);
        B(2.1, 0.1, 0.8, MAT.white, 0, 0.9, 0, tab); B(2.1, 0.04, 0.05, MAT.accent, 0, 0.95, 0.4, tab, false); B(2.1, 0.04, 0.05, MAT.accent, 0, 0.95, -0.4, tab, false);
        B(1.2, 0.62, 0.55, MAT.white, 0, 0.5, 0, tab); B(1.5, 0.12, 0.8, MAT.accent, 0, 0.06, 0, tab);
        [0.2, 0.35, 0.5].forEach(x => B(0.08, 0.04, 0.012, MAT.steel, x - 0.5, 0.6, 0.28, tab, false));
        const col = new THREE.Group(); col.position.set(-1.7, 0, -1.75); room.add(col);
        B(0.3, 2.7, 0.3, MAT.white, 0, 1.35, 0, col); B(0.1, 2.7, 0.012, MAT.accent, 0, 1.35, 0.16, col, false); B(0.7, 0.1, 0.7, MAT.accent, 0, 0.05, 0, col);
        B(0.14, 0.14, 1.45, MAT.white, 0, 2.15, 0.75, col);
        const head = new THREE.Group(); head.position.set(0, 1.95, 1.45); col.add(head);
        B(0.4, 0.34, 0.36, MAT.white, 0, 0, 0, head); B(0.3, 0.14, 0.3, MAT.dark, 0, -0.22, 0, head); B(0.2, 0.1, 0.012, MAT.screenFrame, 0, 0.02, 0.185, head, false);
        hose(col, [[0.1, 2.1, 0.2], [0.35, 1.7, 0.5], [0.3, 2.0, 1.0], [0.15, 2.0, 1.4]], 0xf1f5f9, 0.02);
        // potence murale + détecteur
        const wall = new THREE.Group(); wall.position.set(-3.7, 0, -1.0); wall.rotation.y = Math.PI / 2; room.add(wall);
        B(0.3, 2.5, 0.25, MAT.white, 0, 1.25, 0, wall); B(0.08, 2.5, 0.012, MAT.accent, 0, 1.25, 0.13, wall, false);
        B(0.55, 0.55, 0.08, MAT.white, 0.1, 1.2, 0.2, wall); B(0.48, 0.48, 0.01, MAT.dark, 0.1, 1.2, 0.25, wall, false); B(0.26, 0.26, 0.012, MAT.steel, 0.1, 1.2, 0.256, wall, false);
        // IRM
        const m = mriScanner(); put(room, m, 3.15, 0, -0.6, -Math.PI / 2);
        sign(room, A.canvasTex(256, 96, (c, w, h) => { c.fillStyle = '#facc15'; c.fillRect(0, 0, w, h); c.fillStyle = '#111'; c.fillRect(0, 0, w, 10); c.fillRect(0, h - 10, w, 10); T(c, 'ZONE IRM', w / 2, 34, 28, '#111', true, 'center'); T(c, 'CHAMP MAGNÉTIQUE', w / 2, 66, 17, '#111', true, 'center'); }), 1.5, 0.56, 1.1, 0.013, -0.6, 0, -Math.PI / 2);
        // poste de commande + écrans PACS
        const desk = new THREE.Group(); desk.position.set(-3.5, 0, 1.9); desk.rotation.y = Math.PI / 2; room.add(desk);
        B(1.5, 0.74, 0.7, MAT.white, 0, 0.37, 0, desk); B(1.6, 0.04, 0.76, MAT.wood, 0, 0.76, 0, desk);
        const scr1 = addScreen(desk, 0.5, 0.32, -0.36, 1.08, -0.12, drawBrain, { pw: 256, every: 80 }); B(0.54, 0.36, 0.03, MAT.screenFrame, -0.36, 1.08, -0.145, desk, false); scr1.position.z = -0.128;
        const scr2 = addScreen(desk, 0.5, 0.32, 0.3, 1.08, -0.12, drawChest, { pw: 256, every: 120 }); B(0.54, 0.36, 0.03, MAT.screenFrame, 0.3, 1.08, -0.145, desk, false); scr2.position.z = -0.128;
        [-0.36, 0.3].forEach(x => { B(0.05, 0.3, 0.05, MAT.dark, x, 0.93, -0.14, desk); });
        B(0.4, 0.015, 0.14, MAT.dark, 0, 0.785, 0.15, desk, false);
        const tv = new THREE.Group(); tv.position.set(-3.93, 1.75, -2.0); tv.rotation.y = Math.PI / 2; room.add(tv);
        B(1.2, 0.7, 0.05, MAT.screenFrame, 0, 0, 0, tv); addScreen(tv, 1.12, 0.62, 0, 0, 0.03, drawBrain, { pw: 320, every: 100 });
        // voyant « Rayons X » au-dessus de la porte
        addScreen(room, 0.8, 0.14, DOOR.x, 2.35, 2.92, (c, w, h, t) => { const on = Math.floor(t * 1.5) % 2; c.fillStyle = on ? '#b91c1c' : '#450a0a'; c.fillRect(0, 0, w, h); T(c, 'RAYONS X · ZONE CONTRÔLÉE', w / 2, h / 2, 17, '#fff', true, 'center'); }, { pw: 320, every: 350, ry: Math.PI });
        // tablier plombé
        B(0.5, 0.04, 0.04, MAT.steel, -3.55, 1.7, 2.9, room); B(0.36, 0.7, 0.03, std(0x3b82d6, { roughness: 0.9 }), -3.55, 1.32, 2.9, room);
    }

    function buildDialysis(room) {
        [-2.7, -0.4, 1.9].forEach((x, i) => {
            const ch = recliner(); put(room, ch, x, 0, -1.55);
            const arm = [-0.57, 0.74, 0.65];
            const mc = machineDialysis([arm[0] + 0.0, arm[1], arm[2] + 0.0]); put(room, mc, x + 0.95, 0, -2.2, 0);
            B(0.4, 0.55, 0.4, MAT.white, x - 0.85, 0.28, -2.3, room); B(0.36, 0.015, 0.36, MAT.accent, x - 0.85, 0.57, -2.3, room, false);
            C(0.012, 1.7, MAT.steel, x - 0.75, 0.85, -1.9, room, 8); B(0.44, 0.02, 0.02, MAT.steel, x - 0.75, 1.7, -1.9, room);
            rbox(0.16, 0.24, 0.04, 0.04, MAT.bag, x - 0.75, 1.52, -1.9, room);
            sign(room, signTex('POSTE ' + (i + 1), '', '#0d9488', 192, 64), 0.5, 0.17, x, 0.013, -0.9, 0, -Math.PI / 2);
        });
        const sk = new THREE.Group(); sk.position.set(-3.65, 0, 1.2); sk.rotation.y = Math.PI / 2; room.add(sk);
        B(0.7, 0.8, 0.5, MAT.white, 0, 0.4, 0, sk); B(0.74, 0.04, 0.54, MAT.steel, 0, 0.82, 0, sk); C(0.18, 0.06, MAT.steel, 0, 0.85, 0.02, sk, 20); tube(0.2, 0.012, 'y', MAT.steel, 0.2, 0.95, -0.12, sk); B(0.5, 0.6, 0.02, MAT.mirror, 0, 1.55, -0.24, sk, false);
        const cart = new THREE.Group(); cart.position.set(0.3, 0, 0.2); room.add(cart);
        B(0.7, 0.04, 0.45, MAT.steel, 0, 0.9, 0, cart); B(0.7, 0.04, 0.45, MAT.steel, 0, 0.35, 0, cart); [[-0.33, -0.2], [0.33, -0.2], [-0.33, 0.2], [0.33, 0.2]].forEach(([x, z]) => C(0.015, 0.9, MAT.steel, x, 0.45, z, cart, 6));
        [0xffffff, 0x2d8fe5, 0xdc2626].forEach((cc, i) => B(0.14, 0.1, 0.1, std(cc), -0.2 + i * 0.2, 0.97, 0, cart)); wheels(cart, 0.3, 0.17, 0.045);
        const sc = new THREE.Group(); sc.position.set(2.7, 0, 0.7); room.add(sc);
        B(0.5, 0.05, 0.5, MAT.steel, 0, 0.03, 0, sc); C(0.02, 1.0, MAT.steel, 0, 0.55, 0, sc, 8); B(0.2, 0.12, 0.05, MAT.white, 0, 1.08, 0, sc); B(0.15, 0.06, 0.01, basic(0x22ff7a), 0, 1.08, 0.03, sc, false);
        sign(room, signTex('HÉMODIALYSE', '3 postes', '#0d9488', 384, 128), 1.6, 0.53, -1.0, 2.5, -2.92, 0);
    }

    function buildPharmacy(room) {
        [-3.2, -1.6, 0, 1.6, 3.2].forEach(x => { shelfUnit(room, 1.55, 2.3, 0.34, 6, x, -2.8, 0); });
        [-1.9, -0.4, 1.1].forEach(z => { shelfUnit(room, 1.4, 2.3, 0.34, 6, -3.78, z, Math.PI / 2); });
        // enseigne : croix verte + « PHARMACIE »
        sign(room, signTex('PHARMACIE', 'Ordonnances · Conseil', '#16a34a', 512, 128), 2.8, 0.7, 0, 2.62, -2.95, 0);
        const cr = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.5), basic(0xffffff, { map: crossTex() })); cr.position.set(-2.0, 2.62, -2.94); noCollide(cr); room.add(cr);
        // comptoir
        const cn = new THREE.Group(); cn.position.set(-1.1, 0, 0.2); room.add(cn);
        B(4.4, 1.0, 0.65, MAT.white, 0, 0.5, 0, cn); B(4.3, 0.8, 0.02, MAT.accent, 0, 0.5, 0.34, cn, false); B(4.6, 0.05, 0.85, MAT.wood, 0, 1.025, 0.02, cn);
        const cx = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.5), basic(0xffffff, { map: crossTex() })); cx.position.set(0, 0.5, 0.352); noCollide(cx); cn.add(cx);
        [-1.6, 0.4].forEach(x => {
            const pos = addScreen(cn, 0.46, 0.3, x, 1.3, 0.0, (c, w, h) => { c.fillStyle = '#e6f1fb'; c.fillRect(0, 0, w, h); c.fillStyle = '#16a34a'; c.fillRect(0, 0, w, 22); T(c, 'DÉLIVRANCE', 8, 11, 13, '#fff', true); for (let i = 0; i < 6; i++) { c.fillStyle = '#334155'; c.fillRect(8, 34 + i * 16, 90 + (i % 3) * 40, 6); c.fillStyle = '#16a34a'; c.fillRect(w - 50, 34 + i * 16, 36, 6); } }, { pw: 256, every: 1e9, ry: Math.PI });
            B(0.5, 0.34, 0.03, MAT.screenFrame, x, 1.3, 0.016, cn, false); pos.position.z = -0.002;
            B(0.05, 0.28, 0.05, MAT.dark, x, 1.15, 0.03, cn); B(0.4, 0.015, 0.14, MAT.dark, x, 1.06, -0.1, cn, false);
        });
        B(0.3, 0.1, 0.22, MAT.dark, 1.7, 1.1, 0, cn);
        // réfrigérateur à médicaments + chariot
        const fr = new THREE.Group(); fr.position.set(3.45, 0, -2.4); room.add(fr);
        B(0.75, 1.85, 0.65, MAT.white, 0, 0.93, 0, fr); B(0.6, 1.6, 0.02, glassM(0xcfe8ff, 0.25), 0, 0.93, 0.34, fr, false);
        [0.35, 0.7, 1.05, 1.4].forEach(y => { B(0.62, 0.015, 0.5, MAT.steel, 0, y, 0, fr, false); for (let i = 0; i < 5; i++) C(0.025, 0.1, std(0x7dd3fc, { transparent: true, opacity: 0.8 }), -0.2 + i * 0.1, y + 0.06, 0.05, fr, 8); });
        B(0.08, 0.03, 0.03, MAT.green, 0, 1.85, 0.34, fr, false);
        const tr = new THREE.Group(); tr.position.set(1.8, 0, -1.6); room.add(tr);
        B(0.8, 0.04, 0.45, MAT.steel, 0, 0.85, 0, tr); B(0.8, 0.04, 0.45, MAT.steel, 0, 0.3, 0, tr); [[-0.38, -0.2], [0.38, -0.2], [-0.38, 0.2], [0.38, 0.2]].forEach(([x, z]) => C(0.014, 0.85, MAT.steel, x, 0.43, z, tr, 6));
        for (let i = 0; i < 6; i++) B(0.12, 0.1 + rnd() * 0.05, 0.1, std(PILL[i]), -0.3 + i * 0.12, 0.93, 0, tr); wheels(tr, 0.35, 0.18, 0.045);
        sign(room, A.canvasTex(160, 220, (c, w, h) => { c.fillStyle = '#fff'; c.fillRect(0, 0, w, h); c.fillStyle = '#2d8fe5'; c.fillRect(0, 0, w, 40); T(c, 'CONSEIL', w / 2, 20, 22, '#fff', true, 'center'); c.fillStyle = '#16a34a'; c.fillRect(w / 2 - 8, 70, 16, 70); c.fillRect(w / 2 - 35, 97, 70, 16); T(c, 'Demandez à', w / 2, 175, 15, '#334155', false, 'center'); T(c, 'votre pharmacien', w / 2, 195, 15, '#334155', false, 'center'); }), 0.6, 0.82, 3.93, 1.5, 0.4, -Math.PI / 2);
    }

    function buildEquipment(room) {
        // dos au mur nord : 4 postes ; mur ouest : nutrition ; mur est : élimination
        const st = [['ecg', -3.0, 'CARDIOLOGIE', 'ECG · rythme · SpO2', '#dc2626'], ['bp', -1.35, 'TENSION', 'Tensiomètre automatique', '#2563eb'], ['iv', 0.25, 'SÉRUM', 'Perfusion · pompe', '#0891b2'], ['temp', 1.35, 'TEMPÉRATURE', 'Moniteur · infrarouge', '#d97706']];
        st.forEach(([k, x, n, sub, col], i) => {
            const m = MACHINES[k](); put(room, m, x, 0, -1.95 + (k === 'temp' ? 0.1 : 0), 0);
            sign(room, signTex(n, sub, col, 384, 128), 1.25, 0.42, x + (k === 'bp' || k === 'temp' ? 0.4 : 0), 2.45, -2.93, 0);
            sign(room, signTex('0' + (i + 1) + ' · ' + n, '', col, 256, 64), 0.9, 0.22, x + (k === 'bp' || k === 'temp' ? 0.4 : 0), 0.013, -0.95, 0, -Math.PI / 2);
        });
        const nu = machineNutrition(); put(room, nu, -3.62, 0, 0.5, Math.PI / 2);
        sign(room, signTex('NUTRITION', 'Eau · Vitamines · Repas', '#16a34a', 384, 128), 1.25, 0.42, -3.93, 2.45, 0.5, Math.PI / 2);
        sign(room, signTex('05 · NUTRITION', '', '#16a34a', 256, 64), 0.9, 0.22, -2.7, 0.013, 0.5, 0, -Math.PI / 2);
        const ws = machineWaste(); put(room, ws, 2.55, 0, -0.1, 0);
        sign(room, signTex('ÉLIMINATION', 'Urine · Déchets DASRI', '#7c3aed', 384, 128), 1.25, 0.42, 3.93, 2.45, -0.1, -Math.PI / 2);
        sign(room, signTex('06 · ÉLIMINATION', '', '#7c3aed', 256, 64), 0.9, 0.22, 1.5, 0.013, 1.55, 0, -Math.PI / 2);
        sign(room, signTex('SALLE DES ÉQUIPEMENTS', '', '#1f6fb8', 512, 96), 2.4, 0.45, 0, 2.62, 2.92, Math.PI);
    }

    // ═══════════════════════════════════════════════════════
    //  Structure de l'étage : dalle, couloir, murs, ascenseur, toit (visite à pied)
    // ═══════════════════════════════════════════════════════
    const FLOORS_DEF = [
        { id: 'RAD', name: 'Radiologie', slot: 'NW', color: '#7c3aed', floor: () => new THREE.MeshStandardMaterial({ color: 0xe9f1fa, roughness: 0.12, metalness: 0.15 }), build: buildRadiology },
        { id: 'DIA', name: 'Dialyse', slot: 'NE', color: '#0d9488', floor: () => A.tiledMat(A.textures.room, 8, 6, 1.2, 0.3), build: buildDialysis },
        { id: 'PHA', name: 'Pharmacie', slot: 'SW', color: '#16a34a', floor: () => A.tiledMat(A.textures.lobby, 8, 6, 1.2, 0.22), build: buildPharmacy, window: false },
        { id: 'EQP', name: 'Équipements', slot: 'SE', color: '#2563eb', floor: () => A.tiledMat(A.textures.room, 8, 6, 1.2, 0.3), build: buildEquipment },
    ];

    function buildUpper() {
        upper = new THREE.Group(); upper.position.y = FY; A.scene.add(upper);

        // dalle (le dessous sert de plafond au RDC) + luminaires du plafond du RDC
        slab = new THREE.Group(); upper.add(slab);
        B(16.6, 0.3, 16.6, MAT.concrete, 0, -0.15, 0, slab);
        const panelGeo = new THREE.PlaneGeometry(1.4, 0.5), panelMat = basic(0xfffbe8);
        [-5, 0, 5].forEach(z => [-6, -2, 2, 6].forEach(x => { const p = new THREE.Mesh(panelGeo, panelMat); p.rotation.x = Math.PI / 2; p.position.set(x, -0.305, z); noCollide(p); slab.add(p); }));

        // couloir + cloisons
        shell = new THREE.Group(); upper.add(shell);
        const cor = new THREE.Mesh(new THREE.PlaneGeometry(16, 3.84), A.tiledMat(A.textures.corridor, 16, 3.84, 1.2, 0.25));
        cor.rotation.x = -Math.PI / 2; cor.position.y = 0.005; cor.receiveShadow = true; noCollide(cor); shell.add(cor);
        [-0.9, 0.9].forEach(z => { const s = new THREE.Mesh(new THREE.PlaneGeometry(16, 0.1), basic(0x7fbaf0)); s.rotation.x = -Math.PI / 2; s.position.set(0, 0.01, z); noCollide(s); shell.add(s); });
        [-5, 5].forEach(zc => B(WT, WH, 6.32, MAT.wall, 0, WH / 2, zc, shell));
        B(WT, 0.12, 6.32, MAT.base, 0, 0.06, -5, shell, false); B(WT, 0.12, 6.32, MAT.base, 0, 0.06, 5, shell, false);
        // murs de bout : fenêtre sur le couloir (est) ; mur plein + ascenseur (ouest)
        const east = new THREE.Group(); east.position.set(8 + WT / 2, 0, 0); east.rotation.y = Math.PI / 2; shell.add(east);
        A.buildWallX(east, -8.16, 8.16, 0, [{ x0: -1.2, x1: 1.2, sill: 0.9, top: 2.3 }], false, -1);
        B(2.4, 1.4, 0.03, MAT.glass, 0, 1.6, 0, east, false).renderOrder = 2;
        B(2.5, 0.06, 0.2, MAT.white, 0, 0.9, 0, east); B(0.06, 1.4, 0.2, MAT.white, 0, 1.6, 0, east);
        const west = new THREE.Group(); west.position.set(-(8 + WT / 2), 0, 0); west.rotation.y = Math.PI / 2; shell.add(west);
        A.buildWallX(west, -8.16, 8.16, 0, [], false, 1);
        // portes d'ascenseur (face intérieure du mur ouest)
        const lx = -8.08 + 0.04;
        B(0.08, 2.5, 1.9, MAT.accentDark, lx - 0.02, 1.25, 0, shell); B(0.05, 2.3, 0.8, MAT.steel, lx + 0.03, 1.15, -0.41, shell); B(0.05, 2.3, 0.8, MAT.steel, lx + 0.03, 1.15, 0.41, shell);
        B(0.02, 2.2, 0.01, MAT.dark, lx + 0.06, 1.15, 0, shell, false);
        B(0.04, 0.16, 0.1, MAT.white, lx + 0.03, 1.1, 1.15, shell); B(0.02, 0.04, 0.04, MAT.green, lx + 0.06, 1.14, 1.15, shell, false);
        sign(shell, signTex('ASCENSEUR', 'RDC ⇅ Étage 1', '#1f6fb8', 384, 128), 1.2, 0.4, -8.07, 2.75, 0, Math.PI / 2);
        // panneau d'orientation (mur est)
        sign(shell, A.canvasTex(256, 320, (c, w, h) => {
            c.fillStyle = '#1f6fb8'; c.fillRect(0, 0, w, h); T(c, 'ÉTAGE 1', 16, 34, 30, '#fff', true);
            [['Radiologie', '#c4b5fd'], ['Dialyse', '#5eead4'], ['Pharmacie', '#86efac'], ['Équipements', '#93c5fd']].forEach(([n, col], i) => { c.fillStyle = col; c.fillRect(16, 74 + i * 56, 14, 14); T(c, n, 42, 82 + i * 56, 24, '#fff', true); });
            T(c, '↑ Nord   ↓ Sud', 16, 300, 18, '#cfe3f5');
        }), 0.6, 0.75, 8.06, 1.7, -1.55, -Math.PI / 2);
        // lumières du couloir
        [-4, 4].forEach(x => { const l = new THREE.PointLight(0xffffff, 0.22, 10); l.position.set(x, 2.8, 0); shell.add(l); });

        // toit + plafonds lumineux : visibles seulement pendant la visite à pied
        roof = new THREE.Group(); upper.add(roof);
        B(16.6, 0.2, 16.6, MAT.concrete, 0, WH + 0.15, 0, roof);
        [-5, 0, 5].forEach(z => [-6, -2, 2, 6].forEach(x => { const p = new THREE.Mesh(panelGeo, panelMat); p.rotation.x = Math.PI / 2; p.position.set(x, WH + 0.04, z); noCollide(p); roof.add(p); }));
        roof.visible = false;

        headlamp = new THREE.PointLight(0xffffff, 0, 9); A.scene.add(headlamp);
    }

    // ═══════════════════════════════════════════════════════
    //  Visibilité : étage affiché / salle isolée
    // ═══════════════════════════════════════════════════════
    let mode = 'rdc', exploded = false, explodeTarget = 0, isolated = null;
    let walking = false, level = 0, uiRefs = {};

    function refresh() {
        const iso = isolated && regs[isolated];
        let upVis = mode !== 'rdc', gndRooms = mode !== 'etage';
        if (walking) { upVis = true; gndRooms = true; }
        Object.values(regs).forEach(r => { r.group.visible = r.floor === 1 ? true : gndRooms; });
        shell.visible = true; slab.visible = true;
        if (iso && !walking) {
            upVis = iso.floor === 1;
            Object.values(regs).forEach(r => { r.group.visible = r === iso; });
            shell.visible = false;
        }
        upper.visible = upVis;
        roof.visible = walking && !iso;
        const ov = document.getElementById('cctv-overlay'); if (ov && (iso || mode !== 'rdc' || walking)) ov.classList.add('cctv-hidden');
        updateUI();
    }

    function flyOverview() {
        const cx = -A.REC.D / 2, F = (p, t, fov) => A.moveCameraTo(V3(...p), V3(...t), 0.35, fov || 45);
        if (mode === 'rdc') A.resetCamera();
        else if (mode === 'etage') F([cx, FY + 27, 19.5], [cx, FY, 0]);
        else if (exploded) F([cx, 38, 29], [cx, 3.8, 0]);
        else F([cx, 31, 22], [cx, 1.8, 0]);
    }
    function setMode(m, fly = true) {
        if (walking) return;
        mode = m; isolated = null;
        if (m === 'rdc') exploded = false;
        explodeTarget = exploded ? 6.5 : 0;
        refresh(); if (fly) flyOverview();
    }
    function toggleExplode() {
        if (walking) return;
        exploded = !exploded; if (exploded) mode = 'all';
        isolated = null; explodeTarget = exploded ? 6.5 : 0;
        refresh(); flyOverview();
    }
    function showAll() { if (walking) return; isolated = null; refresh(); flyOverview(); }

    function roomView(r, kind) {
        upper.position.y = FY; explodeTarget = 0; exploded = false;
        A.scene.updateMatrixWorld(true);
        const g = r.group;
        if (kind === 'inside') {
            if (r.floor === 0) { A.zoomToRoom(r.id); return; }
            A.moveCameraTo(g.localToWorld(V3(3.3, 2.25, 2.55)), g.localToWorld(V3(-1.0, 0.95, -1.2)), 0.35, 66);
        } else {
            A.moveCameraTo(g.localToWorld(V3(0, 9.4, 6.2)), g.localToWorld(V3(0, 0.5, -0.5)), 0.35, 45);
        }
    }
    function isolate(id, kind) {
        const r = regs[id]; if (!r) return;
        if (walking) stopWalk(false);
        isolated = id; refresh(); roomView(r, kind || 'doll');
    }

    // ═══════════════════════════════════════════════════════
    //  Visite à pied
    // ═══════════════════════════════════════════════════════
    const keys = {}, vk = {}, colliders = [], near = [];
    let yaw = 0, pitch = 0, px = 0, pz = 0, lastNear = { x: 1e9, z: 1e9, l: -1 }, drag = null, dragDist = 0, hudT = 0;
    const ray = new THREE.Raycaster();
    const levelY = () => level === 1 ? FY : 0;

    function collect() {
        colliders.length = 0;
        A.scene.updateMatrixWorld(true);
        A.scene.traverse(o => {
            if (!o.isMesh || o.userData.noCollide || !vis(o)) return;
            const gt = o.geometry.type;
            if (gt === 'PlaneGeometry' || gt === 'RingGeometry' || gt === 'CircleGeometry' || gt === 'TubeGeometry') return;
            const mat = o.material; if (!mat || Array.isArray(mat)) return;
            if (mat.transparent && mat !== MAT.glass) return;
            if (!o.geometry.boundingSphere) o.geometry.computeBoundingSphere();
            const bs = o.geometry.boundingSphere, r = bs.radius * o.matrixWorld.getMaxScaleOnAxis();
            if (r > 40 || r < 0.03) return;
            o.userData._c = bs.center.clone().applyMatrix4(o.matrixWorld); o.userData._r = r; colliders.push(o);
        });
        lastNear = { x: 1e9, z: 1e9, l: -1 };
    }
    function refreshNear() {
        if (Math.hypot(px - lastNear.x, pz - lastNear.z) < 1 && lastNear.l === level) return;
        lastNear = { x: px, z: pz, l: level }; near.length = 0;
        const y0 = levelY();
        colliders.forEach(o => { const c = o.userData._c, r = o.userData._r; if (Math.hypot(c.x - px, c.z - pz) < r + 6 && c.y + r > y0 && c.y - r < y0 + 2.2) near.push(o); });
    }
    function blocked(dx, dz) {
        const d = Math.hypot(dx, dz); if (!d) return false;
        const dir = V3(dx / d, 0, dz / d); ray.near = 0; ray.far = d + RADIUS;
        for (const h of [0.35, 1.2]) { ray.set(V3(px, levelY() + h, pz), dir); if (ray.intersectObjects(near, false).length) return true; }
        return false;
    }
    function walkStep(dt) {
        const f = ((keys.w || keys.z || keys.arrowup || vk.f) ? 1 : 0) - ((keys.s || keys.arrowdown || vk.b) ? 1 : 0);
        const s = (keys.d ? 1 : 0) - ((keys.a || keys.q) ? 1 : 0);
        const tr = ((keys.arrowleft || vk.tl) ? 1 : 0) - ((keys.arrowright || vk.tr) ? 1 : 0);
        yaw += tr * 3.5 * dt;
        refreshNear();
        if (f || s) {
            const sp = (keys.shift ? 12.0 : 6.0) * dt;
            let dx = -Math.sin(yaw) * f + Math.cos(yaw) * s, dz = -Math.cos(yaw) * f - Math.sin(yaw) * s;
            const l = Math.hypot(dx, dz) || 1; dx = dx / l * sp; dz = dz / l * sp;
            if (!blocked(dx, 0)) px += dx;
            if (!blocked(0, dz)) pz += dz;
            px = Math.max(-45, Math.min(45, px)); pz = Math.max(-45, Math.min(45, pz));
        }
        A.camera.position.set(px, levelY() + EYE, pz);
        A.camera.rotation.set(pitch, yaw, 0);
        headlamp.position.set(px, levelY() + 2.2, pz);
    }

    function placeOf() {
        if (px < -8.2) return 'Réception';
        const inRoom = Object.values(regs).find(r => r.floor === level && Math.abs(px - r.cfg.x) < 4 && Math.abs(pz - r.cfg.z) < 3);
        if (inRoom) return inRoom.name + (inRoom.floor === 0 ? '' : '');
        if (Math.abs(px) < 8.2 && Math.abs(pz) < 1.92) return 'Couloir';
        return Math.abs(px) < 8.2 && Math.abs(pz) < 8.2 ? 'Bâtiment' : 'Extérieur';
    }
    function startWalk(opt) {
        if (!walking) {
            walking = true; isolated = null; mode = 'all'; exploded = false; explodeTarget = 0; upper.position.y = FY;
            A.cancelTween(); A.controls.enabled = false;
            A.camera.near = 0.08; A.camera.fov = 72; A.camera.updateProjectionMatrix(); A.camera.rotation.order = 'YXZ';
            headlamp.intensity = 0.45; refresh(); collect();
            uiRefs.hud.style.display = 'block'; uiRefs.panel.classList.add('hf-walking');
        }
        level = opt.level; px = opt.x; pz = opt.z; yaw = opt.yaw; pitch = opt.pitch || 0; lastNear.l = -1;
        hudT = 0;
    }
    function stopWalk(fly = true) {
        if (!walking) return;
        walking = false; Object.keys(keys).forEach(k => keys[k] = false); Object.keys(vk).forEach(k => vk[k] = false);
        A.camera.near = 0.3; A.camera.fov = 45; A.camera.updateProjectionMatrix(); A.camera.rotation.order = 'XYZ';
        A.controls.enabled = true; headlamp.intensity = 0;
        uiRefs.hud.style.display = 'none'; uiRefs.panel.classList.remove('hf-walking');
        mode = level === 1 ? 'etage' : 'rdc'; refresh();
        if (fly) flyOverview();
    }
    function walkAt(id) {
        const r = id && regs[id];
        if (r) {
            A.scene.updateMatrixWorld(true);
            const p = r.group.localToWorld(V3(2.6, 0, 2.25)), t = r.group.localToWorld(V3(-1, 0, -1));
            startWalk({ level: r.floor, x: p.x, z: p.z, yaw: Math.atan2(-(t.x - p.x), -(t.z - p.z)), pitch: -0.08 });
        } else {
            const l = (mode === 'etage' && !walking) ? 1 : (walking ? level : 0);
            startWalk({ level: l, x: 6.2, z: 0, yaw: Math.PI / 2, pitch: -0.05 });
        }
    }
    function lift() {
        if (!walking) return;
        const f = uiRefs.fade; f.style.opacity = 1;
        setTimeout(() => {
            level = level === 1 ? 0 : 1; px = LIFT.x + 1.2; pz = LIFT.z; yaw = LIFT.yaw; pitch = 0; lastNear.l = -1;
            setTimeout(() => { f.style.opacity = 0; }, 150);
        }, 260);
    }

    function onKey(e, down) {
        if (!walking) return;
        const tag = (e.target && e.target.tagName) || ''; if (/INPUT|TEXTAREA|SELECT/.test(tag)) return;
        const k = e.key.toLowerCase();
        if (k === 'escape') { if (down) stopWalk(); return; }
        if (down && k === 'e') { lift(); return; }
        if (['w', 'z', 'a', 'q', 's', 'd', 'shift', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(k)) { keys[k] = down; e.preventDefault(); }
    }

    // ═══════════════════════════════════════════════════════
    //  Interface
    // ═══════════════════════════════════════════════════════
    function buildUI() {
        const container = A.container;
        if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
        const st = document.createElement('style');
        st.textContent = `
        #hf-panel{position:absolute;left:12px;bottom:12px;z-index:25;width:236px;background:rgba(15,23,42,.9);border:1px solid rgba(59,130,246,.45);border-radius:10px;padding:8px 10px;font:12px Inter,system-ui,sans-serif;color:#e2e8f0;backdrop-filter:blur(6px)}
        #hf-panel .hf-t{display:flex;justify-content:space-between;align-items:center;font-weight:700;letter-spacing:.06em;font-size:11px;color:#93c5fd;margin-bottom:6px}
        #hf-panel .hf-r{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}
        #hf-panel .hf-s{font-size:10px;color:#94a3b8;margin-top:6px;text-transform:uppercase;letter-spacing:.05em}
        #hf-panel button,#hf-hud button{background:#1e293b;color:#cbd5e1;border:1px solid #334155;padding:4px 8px;border-radius:6px;cursor:pointer;font:600 11px Inter,system-ui,sans-serif}
        #hf-panel button:hover,#hf-hud button:hover{background:#2b3a52}
        #hf-panel button.on{background:#2563eb;color:#fff;border-color:#60a5fa}
        #hf-panel button.wide{flex:1}
        #hf-panel.hf-collapsed .hf-body{display:none}
        #hf-panel.hf-walking .hf-body{display:none}
        #hf-hud{position:absolute;inset:0;z-index:24;display:none;pointer-events:none;font:12px Inter,system-ui,sans-serif;color:#fff}
        #hf-hud .hf-top{position:absolute;top:12px;left:50%;transform:translateX(-50%);background:rgba(15,23,42,.85);padding:6px 12px;border-radius:8px;text-align:center;pointer-events:auto}
        #hf-hud .hf-help{position:absolute;bottom:10px;left:50%;transform:translateX(-50%);background:rgba(15,23,42,.7);padding:4px 10px;border-radius:6px;font-size:11px;color:#cbd5e1;white-space:nowrap}
        #hf-hud .hf-pad{position:absolute;right:14px;bottom:14px;display:grid;grid-template-columns:repeat(3,38px);gap:4px;pointer-events:auto}
        #hf-hud .hf-pad button{height:38px;font-size:16px;touch-action:none}
        #hf-hud .hf-fade{position:absolute;inset:0;background:#000;opacity:0;transition:opacity .25s}
        #hf-hud .hf-x{position:absolute;top:12px;right:12px;pointer-events:auto}
        #hf-hud .hf-ch{position:absolute;left:50%;top:50%;width:6px;height:6px;margin:-3px;border-radius:50%;background:rgba(255,255,255,.55)}`;
        document.head.appendChild(st);

        const panel = document.createElement('div'); panel.id = 'hf-panel';
        const btn = (txt, fn, cls) => { const b = document.createElement('button'); b.textContent = txt; if (cls) b.className = cls; b.addEventListener('click', fn); return b; };
        const row = () => { const r = document.createElement('div'); r.className = 'hf-r'; return r; };
        const title = document.createElement('div'); title.className = 'hf-t'; title.innerHTML = '<span>ÉTAGES &amp; SALLES</span>';
        const col = btn('–', () => panel.classList.toggle('hf-collapsed')); col.style.padding = '0 7px'; title.appendChild(col);
        const body = document.createElement('div'); body.className = 'hf-body';
        const modes = row(); uiRefs.modes = {};
        [['rdc', 'RDC'], ['etage', 'Étage 1'], ['all', 'Tout']].forEach(([m, n]) => { const b = btn(n, () => setMode(m)); uiRefs.modes[m] = b; modes.appendChild(b); });
        uiRefs.expl = btn('⇕ Éclaté', toggleExplode); modes.appendChild(uiRefs.expl);
        const s1 = document.createElement('div'); s1.className = 'hf-s'; s1.textContent = 'RDC — voir une salle seule';
        const g0 = row(); uiRefs.chips = {};
        ['101', '102', '103', '104'].forEach(id => { const b = btn(id, () => isolate(id)); uiRefs.chips[id] = b; g0.appendChild(b); });
        g0.appendChild(btn('Réception', () => { if (walking) stopWalk(false); isolated = null; mode = 'rdc'; refresh(); A.zoomToReception(); }));
        const s2 = document.createElement('div'); s2.className = 'hf-s'; s2.textContent = 'Étage 1';
        const g1 = row();
        FLOORS_DEF.forEach(d => { const b = btn(d.name, () => isolate(d.id)); uiRefs.chips[d.id] = b; g1.appendChild(b); });
        const g2 = row();
        g2.appendChild(btn('👁 Intérieur', () => { if (isolated) { refresh(); roomView(regs[isolated], 'inside'); } }, 'wide'));
        g2.appendChild(btn('🚶 Marcher ici', () => walkAt(isolated), 'wide'));
        const g3 = row();
        g3.appendChild(btn('Tout afficher', showAll, 'wide'));
        g3.appendChild(btn('🚶 Visite à pied', () => walkAt(null), 'wide'));
        [modes, s1, g0, s2, g1, g2, g3].forEach(e => body.appendChild(e));
        panel.appendChild(title); panel.appendChild(body); container.appendChild(panel);

        const hud = document.createElement('div'); hud.id = 'hf-hud';
        hud.innerHTML = '<div class="hf-ch"></div><div class="hf-top"><b id="hf-place">Couloir</b> · <span id="hf-level">RDC</span></div><div class="hf-help">ZQSD / WASD : marcher · glisser : regarder · Maj : courir · E : ascenseur · Échap : quitter</div>';
        const x = btn('✕ Quitter', () => stopWalk()); x.className = 'hf-x'; hud.appendChild(x);
        const pad = document.createElement('div'); pad.className = 'hf-pad';
        const pb = (t, k) => { const b = document.createElement('button'); b.textContent = t; ['pointerdown'].forEach(ev => b.addEventListener(ev, e => { vk[k] = true; e.preventDefault(); })); ['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => b.addEventListener(ev, () => { vk[k] = false; })); return b; };
        const lb = btn('⇅', lift); lb.title = 'Ascenseur';
        [lb, pb('▲', 'f'), document.createElement('span'), pb('◀', 'tl'), pb('▼', 'b'), pb('▶', 'tr')].forEach(e => pad.appendChild(e));
        hud.appendChild(pad);
        const fade = document.createElement('div'); fade.className = 'hf-fade'; hud.appendChild(fade);
        container.appendChild(hud);
        uiRefs.panel = panel; uiRefs.hud = hud; uiRefs.fade = fade; uiRefs.place = hud.querySelector('#hf-place'); uiRefs.lvl = hud.querySelector('#hf-level');

        window.addEventListener('keydown', e => onKey(e, true));
        window.addEventListener('keyup', e => onKey(e, false));
        const cv = A.renderer.domElement;
        cv.addEventListener('pointerdown', e => { if (!walking) return; drag = { x: e.clientX, y: e.clientY }; dragDist = 0; try { cv.setPointerCapture(e.pointerId); } catch (_) { } });
        cv.addEventListener('pointermove', e => { if (!walking || !drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag = { x: e.clientX, y: e.clientY }; dragDist += Math.abs(dx) + Math.abs(dy); yaw -= dx * 0.0042; pitch = Math.max(-1.3, Math.min(1.3, pitch - dy * 0.0042)); });
        const up = () => { drag = null; };
        cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
        cv.addEventListener('click', e => { if (walking && dragDist > 4) { e.stopImmediatePropagation(); e.stopPropagation(); } }, true);
        updateUI();
    }
    function updateUI() {
        if (!uiRefs.panel) return;
        Object.keys(uiRefs.modes).forEach(m => uiRefs.modes[m].classList.toggle('on', !isolated && mode === m && !walking));
        uiRefs.expl.classList.toggle('on', exploded);
        Object.keys(uiRefs.chips).forEach(id => uiRefs.chips[id].classList.toggle('on', isolated === id));
    }

    // ═══════════════════════════════════════════════════════
    //  Init / boucle / API
    // ═══════════════════════════════════════════════════════
    function init(api) {
        A = api; ({ B, C, tube, rbox, std, MAT } = A); WT = A.WALL_T; WH = A.WALL_H;
        buildUpper();
        FLOORS_DEF.forEach(d => newRoom({ id: d.id, name: d.name, slot: d.slot, color: d.color, floor: d.floor(), build: d.build, window: d.window }));
        Object.keys(A.ROOMS).forEach(id => { if (A.roomGroups[id]) regs[id] = { id, name: 'Chambre ' + id, floor: 0, group: A.roomGroups[id], cfg: A.ROOMS[id] }; });
        buildUI();
        refresh();
        console.log('[Floors] étage 1 prêt : RAD, DIA, PHA, EQP');
    }

    function update(dt, t) {
        if (!upper) return;
        const k = 1 - Math.exp(-4 * Math.min(dt, 0.1));
        upper.position.y += (FY + explodeTarget - upper.position.y) * k;
        if (upper.visible) {
            const now = performance.now();
            for (let i = 0; i < screens.length; i++) {
                const s = screens[i];
                if (now - s.last > s.every && vis(s.mesh)) { s.last = now; s.draw(s.g, s.w, s.h, now / 1000); s.tex.needsUpdate = true; }
            }
            for (let i = 0; i < anims.length; i++) anims[i](t, dt);
        }
        if (walking) {
            walkStep(Math.min(dt, 0.1));
            hudT -= dt;
            if (hudT <= 0) { hudT = 0.25; uiRefs.place.textContent = placeOf(); uiRefs.lvl.textContent = level === 1 ? 'Étage 1' : 'RDC'; }
        }
    }

    // Ajouter une machine dans n'importe quelle salle : HospitalFloors.addMachine('101','ecg', 2.5, -1, 0)
    function addMachine(roomId, type, x, z, ry) {
        const r = regs[roomId], f = MACHINES[type]; if (!r || !f) return null;
        return put(r.group, f(), x, 0, z, ry || 0);
    }

    return { init, update, isWalking: () => walking, setMode, isolate, showAll, walk: walkAt, stopWalk, addMachine, machines: MACHINES, regs };
})();
