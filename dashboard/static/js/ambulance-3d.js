/**
 * HackCure — ambulances dans le jumeau 3D (V2, extension additive).
 *  - étiquette « Réservée — arrivée dans X min » au-dessus du lit de la chambre réservée (room_state.reservation) ;
 *  - à l'arrivée (ETA à zéro) : l'ambulance du parking fait son entrée (gyrophare), puis un brancard avec le
 *    patient va de l'entrée jusqu'à la chambre réservée ; le patient est ensuite installé au lit (admission).
 */
const Ambulance3D = (() => {
    'use strict';
    const labels = {};     // room -> sprite
    let anim = null;       // animation d'arrivée en cours
    let raf = null;

    const ready = () => typeof HospitalScene !== 'undefined' && HospitalScene.getScene();

    function label(room) {
        if (labels[room]) return labels[room];
        const bp = HospitalScene.getBedWorldPosition(room); if (!bp) return null;
        const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 96;
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false }));
        sprite.scale.set(3.4, 0.64, 1); sprite.position.set(bp.x, 2.9, bp.z); sprite.renderOrder = 14; sprite.visible = false;
        sprite.userData = { canvas, text: '' };
        HospitalScene.getScene().add(sprite);
        return (labels[room] = sprite);
    }

    function setReservation(room, res) {
        if (!ready()) return;
        const s = label(room); if (!s) return;
        if (!res) { s.visible = false; return; }
        const text = `🚑 ${res.label}`;
        if (s.userData.text !== text) {
            s.userData.text = text;
            const c = s.userData.canvas, g = c.getContext('2d');
            g.clearRect(0, 0, c.width, c.height);
            g.fillStyle = 'rgba(127,29,29,0.92)'; g.fillRect(0, 0, c.width, c.height);
            g.strokeStyle = '#fca5a5'; g.lineWidth = 4; g.strokeRect(2, 2, c.width - 4, c.height - 4);
            g.fillStyle = '#fff'; g.font = 'bold 34px Inter, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
            g.fillText(text, c.width / 2, c.height / 2 + 2);
            s.material.map.needsUpdate = true;
        }
        s.visible = true;
    }

    function stretcher() {
        const g = new THREE.Group();
        const mk = (geo, color, x, y, z) => { const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color, roughness: 0.6 })); m.position.set(x, y, z); g.add(m); return m; };
        mk(new THREE.BoxGeometry(1.9, 0.08, 0.62), 0xe2e8f0, 0, 0.78, 0);                                   // plateau
        mk(new THREE.BoxGeometry(1.7, 0.1, 0.52), 0x38bdf8, 0, 0.87, 0);                                    // matelas
        [[-0.8, -0.25], [-0.8, 0.25], [0.8, -0.25], [0.8, 0.25]].forEach(([x, z]) => { mk(new THREE.CylinderGeometry(0.02, 0.02, 0.7, 6), 0x94a3b8, x, 0.4, z); mk(new THREE.SphereGeometry(0.06, 8, 6), 0x1f2937, x, 0.06, z); });
        mk(new THREE.CylinderGeometry(0.17, 0.17, 1.2, 10), 0x9ac7f2, -0.1, 1.05, 0).rotation.z = Math.PI / 2;   // patient allongé
        mk(new THREE.SphereGeometry(0.13, 14, 10), 0xe8bca1, 0.72, 1.07, 0);                                 // tête
        mk(new THREE.BoxGeometry(0.34, 0.9, 0.3), 0xf97316, -1.25, 0.95, 0);                                 // ambulancier
        mk(new THREE.SphereGeometry(0.13, 14, 10), 0xd9a98a, -1.25, 1.55, 0);
        return g;
    }

    function start(mission, installSeconds) {
        if (!ready() || anim) return;
        const scene = HospitalScene.getScene(), amb = scene.userData.ambulance, bed = HospitalScene.getBedWorldPosition(mission.reserved_room);
        if (!bed) return;
        const home = amb ? amb.position.clone() : null;
        const from = amb ? home.clone().add(new THREE.Vector3(26, 0, 0)) : null;       // l'ambulance arrive par la route, côté est
        if (amb) amb.position.copy(from);
        const cart = stretcher(); cart.visible = false; scene.add(cart);
        const door = home ? new THREE.Vector3(home.x - 4, 0, home.z - 3) : new THREE.Vector3(0, 0, 9);
        const corridor = new THREE.Vector3(bed.x > 0 ? 2.5 : -2.5, 0, 0), target = new THREE.Vector3(bed.x + (bed.x > 0 ? -1.4 : 1.4), 0, bed.z);
        const path = [door, new THREE.Vector3(0, 0, door.z - 3), new THREE.Vector3(0, 0, 0.5), corridor, target];
        anim = { t0: performance.now(), drive: 5000, walk: Math.max(6000, (installSeconds || 20) * 1000 - 6000), amb, home, from, cart, path, room: mission.reserved_room };
        if (HospitalScene.resetCamera && !document.body.classList.contains('view-open')) HospitalScene.resetCamera();
        tick();
    }

    function along(path, f) {
        const segs = path.slice(1).map((p, i) => p.distanceTo(path[i])), total = segs.reduce((a, b) => a + b, 0);
        let d = f * total;
        for (let i = 0; i < segs.length; i++) { if (d <= segs[i] || i === segs.length - 1) { const k = segs[i] ? Math.min(1, d / segs[i]) : 1; return { pos: path[i].clone().lerp(path[i + 1], k), dir: path[i + 1].clone().sub(path[i]) }; } d -= segs[i]; }
        return { pos: path[path.length - 1].clone(), dir: new THREE.Vector3(1, 0, 0) };
    }

    function tick() {
        if (!anim) return;
        const now = performance.now() - anim.t0, ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
        if (anim.amb) anim.amb.position.lerpVectors(anim.from, anim.home, ease(now / anim.drive));
        if (now > anim.drive) {
            anim.cart.visible = true;
            const { pos, dir } = along(anim.path, Math.min(1, (now - anim.drive) / anim.walk));
            anim.cart.position.copy(pos); anim.cart.rotation.y = Math.atan2(-dir.z, dir.x);
        }
        raf = requestAnimationFrame(tick);
    }

    function finish() {
        if (!anim) return;
        cancelAnimationFrame(raf);
        if (anim.amb) anim.amb.position.copy(anim.home);
        HospitalScene.getScene().remove(anim.cart);
        anim = null;
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'room_state' && m.room) setReservation(m.room, m.reservation);
        else if (m.type === 'init' && m.room_states) Object.values(m.room_states).forEach(rs => setReservation(rs.room, rs.reservation));
        else if (m.type === 'ambulance' && m.mission) {
            if (m.event === 'arrived') start(m.mission, m.install_seconds);
            else if (m.event === 'admitted' || m.event === 'cancelled') { finish(); setReservation(m.mission.reserved_room, null); }
            else if (m.event === 'position' && m.mission.reserved_room && ready()) {
                const s = m.mission.eta_seconds; setReservation(m.mission.reserved_room, { label: `Réservée — arrivée dans ${s >= 90 ? Math.round(s / 60) + ' min' : s + ' s'}` });
            }
        } else if (m.type === 'patients_changed') {
            // nouveau patient inconnu de la scène : la liste des patients 3D est chargée à l'ouverture de la page
            if (typeof PatientStateManager !== 'undefined' && !PatientStateManager.getPatientList().some(p => p.patient_id === m.patient_id)) setTimeout(() => location.reload(), 2500);
        }
    });
    return { setReservation, start, finish, isAnimating: () => !!anim };
})();
window.Ambulance3D = Ambulance3D;
