/**
 * HackCure — Articulated Avatar Manager
 * ======================================
 * Patients are placed in BED-LOCAL coordinates (head = -z, foot = +z), the same
 * frame scene.js uses for the bed, so they always sit on the mattress:
 *   normal -> semi-reclined (head of bed raised, like the reference render)
 *   pain   -> sitting up, knees raised, hands clutching the abdomen
 *   fall   -> on the floor beside the bed (auto-grounded)
 * Poses blend smoothly instead of snapping.
 */

const AvatarManager = (() => {
    const avatars = {};
    const COLORS = {
        normal: 0x22c55e, fall: 0xef4444, pain: 0xf97316, fall_pain: 0xef4444,
        skin: 0xe8bca1, gown: 0x9ac7f2, pants: 0x6fa8dc, hair: 0xe5e7eb,
    };
    const BED = () => HospitalScene.BED;

    // Poses: joint -> [x,y,z]. Rotations are Euler radians, positions metres.
    function poses(b) {
        const lie = b.backAngle;           // 30 deg backrest
        const sit = 0.96;                  // ~55 deg
        const padY = b.deckY + 0.105;      // pelvis centre on the mattress
        const armsLie = { 'aR.s': [0, 0, -0.06], 'aR.e': [-0.15, 0, 0], 'aL.s': [0, 0, 0.06], 'aL.e': [-0.15, 0, 0] };
        return {
            normal: Object.assign({
                'body.pos': [0, 0, 0], 'body.rot': [0, 0, 0],
                'pelvis.pos': [0, padY, -0.05], 'pelvis.rot': [-Math.PI / 2, 0, 0],
                'torso.rot': [lie, 0, 0], 'neck.rot': [0.4, 0, 0],
                'lR.h': [0, 0, -0.04], 'lR.k': [0, 0, 0], 'lL.h': [0, 0, 0.04], 'lL.k': [0, 0, 0],
                backrest: lie, blanket: 1,
                ring: [0, 0, 1, 1.55], label: [0, 1.95, -0.2],
            }, armsLie),
            pain: {
                'body.pos': [0, 0, 0], 'body.rot': [0, 0, 0],
                'pelvis.pos': [0, padY, -0.05], 'pelvis.rot': [-Math.PI / 2, 0, 0],
                'torso.rot': [sit, 0, 0], 'neck.rot': [0.4, 0, 0],
                'aR.s': [-0.5, 0, 0], 'aR.e': [0, 0, 1.4], 'aL.s': [-0.5, 0, 0], 'aL.e': [0, 0, -1.4],
                'lR.h': [-1.05, 0, -0.12], 'lR.k': [1.83, 0, 0], 'lL.h': [-1.05, 0, 0.12], 'lL.k': [1.83, 0, 0],
                backrest: sit, blanket: 0.3,
                ring: [0, 0, 1, 1.55], label: [0, 2.0, -0.2],
            },
            fall: {
                'body.pos': [1.25, 0, 0.35], 'body.rot': [0, -0.35, 0],
                'pelvis.pos': [0, 0.2, 0], 'pelvis.rot': [-Math.PI / 2, 1.2, 0],
                'torso.rot': [0.5, 0.25, 0], 'neck.rot': [-0.4, 0.5, 0],
                'aR.s': [-1.1, 0, -0.5], 'aR.e': [-1.2, 0, 0], 'aL.s': [-0.5, 0, 0.3], 'aL.e': [-0.9, 0, 0],
                'lR.h': [-0.8, 0, -0.1], 'lR.k': [1.4, 0, 0], 'lL.h': [-0.35, 0, 0.1], 'lL.k': [0.8, 0, 0],
                backrest: lie, blanket: 0.3,
                ring: [1.25, 0.35, 0.75, 1.3], label: [1.25, 1.1, 0.35],
            },
        };
    }

    const JOINT = {
        'body.pos': a => a.body.position, 'body.rot': a => a.body.rotation,
        'pelvis.pos': a => a.pelvis.position, 'pelvis.rot': a => a.pelvis.rotation,
        'torso.rot': a => a.torso.rotation, 'neck.rot': a => a.neck.rotation,
        'aR.s': a => a.arms.R.shoulder.rotation, 'aR.e': a => a.arms.R.elbow.rotation,
        'aL.s': a => a.arms.L.shoulder.rotation, 'aL.e': a => a.arms.L.elbow.rotation,
        'lR.h': a => a.legs.R.hip.rotation, 'lR.k': a => a.legs.R.knee.rotation,
        'lL.h': a => a.legs.L.hip.rotation, 'lL.k': a => a.legs.L.knee.rotation,
    };

    function applyNow(a, pose) {
        Object.keys(JOINT).forEach(k => { const o = JOINT[k](a), v = pose[k]; o.x = v[0]; o.y = v[1]; o.z = v[2]; });
    }
    function snapshot(a) {
        const s = {};
        Object.keys(JOINT).forEach(k => { const o = JOINT[k](a); s[k] = [o.x, o.y, o.z]; });
        return s;
    }
    // Lower the fallen body so its lowest point touches the floor
    function groundPose(a, pose) {
        const saved = snapshot(a);
        applyNow(a, pose);
        a.group.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(a.body);
        const dy = 0.03 - box.min.y;
        pose['body.pos'][1] += dy;
        applyNow(a, saved);
    }

    function init() {
        Object.values(PatientStateManager.getAllPatients()).forEach(createAvatar);
        PatientStateManager.subscribe((type, data) => {
            if (type === 'update' && data) updateAvatarState(data.patient);
            else if (type === 'reset') resetAll();
        });
    }

    function createAvatar(patient) {
        const scene = HospitalScene.getScene();
        if (!scene) return;
        const bp = HospitalScene.getBedWorldPosition(patient.room || '101');

        const group = new THREE.Group();
        group.position.set(bp.x, 0, bp.z);
        group.rotation.y = bp.rotY;
        group.userData = { patientId: patient.patient_id };

        const skin = new THREE.MeshStandardMaterial({ color: COLORS.skin, roughness: 0.6 });
        const gown = new THREE.MeshStandardMaterial({ color: COLORS.gown, roughness: 0.85 });
        const pants = new THREE.MeshStandardMaterial({ color: COLORS.pants, roughness: 0.9 });
        const hairM = new THREE.MeshStandardMaterial({ color: COLORS.hair, roughness: 0.9 });
        const dark = new THREE.MeshBasicMaterial({ color: 0x1f2937 });
        const mk = (geo, m, parent, x, y, z) => { const o = new THREE.Mesh(geo, m); o.position.set(x || 0, y || 0, z || 0); o.castShadow = true; parent.add(o); return o; };

        const body = new THREE.Group(); group.add(body);
        const pelvis = mk(new THREE.BoxGeometry(0.36, 0.2, 0.2), pants, body);

        const torso = new THREE.Group(); torso.position.y = 0.1; pelvis.add(torso);
        const chest = mk(new THREE.CylinderGeometry(0.22, 0.19, 0.6, 20), gown, torso, 0, 0.3, 0);
        chest.scale.z = 0.62;

        const neck = new THREE.Group(); neck.position.y = 0.6; torso.add(neck);
        mk(new THREE.CylinderGeometry(0.05, 0.06, 0.1, 10), skin, neck, 0, 0.03, 0);
        const head = mk(new THREE.SphereGeometry(0.14, 24, 16), skin, neck, 0, 0.18, 0.01);
        const hair = mk(new THREE.SphereGeometry(0.15, 24, 12, 0, Math.PI * 2, 0, Math.PI * 0.55), hairM, neck, 0, 0.2, -0.01);
        hair.rotation.x = -0.25;
        [-0.05, 0.05].forEach(x => mk(new THREE.SphereGeometry(0.014, 8, 6), dark, neck, x, 0.2, 0.135));

        const arms = {};
        [-1, 1].forEach(side => {
            const key = side === -1 ? 'R' : 'L';
            const sh = new THREE.Group(); sh.position.set(side * 0.25, 0.52, 0); torso.add(sh);
            mk(new THREE.CylinderGeometry(0.06, 0.05, 0.35, 12), gown, sh, 0, -0.175, 0);
            const el = new THREE.Group(); el.position.y = -0.35; sh.add(el);
            mk(new THREE.CylinderGeometry(0.05, 0.04, 0.33, 12), skin, el, 0, -0.165, 0);
            mk(new THREE.SphereGeometry(0.045, 10, 8), skin, el, 0, -0.35, 0);
            arms[key] = { shoulder: sh, elbow: el };
        });

        const legs = {};
        [-1, 1].forEach(side => {
            const key = side === -1 ? 'R' : 'L';
            const hip = new THREE.Group(); hip.position.set(side * 0.12, -0.1, 0); pelvis.add(hip);
            mk(new THREE.CylinderGeometry(0.09, 0.07, 0.45, 12), pants, hip, 0, -0.225, 0);
            const knee = new THREE.Group(); knee.position.y = -0.45; hip.add(knee);
            mk(new THREE.CylinderGeometry(0.07, 0.05, 0.45, 12), skin, knee, 0, -0.225, 0);
            mk(new THREE.BoxGeometry(0.11, 0.07, 0.2), skin, knee, 0, -0.46, 0.05);
            legs[key] = { hip, knee };
        });

        // status ring (stretched so it surrounds the bed)
        const ringMat = new THREE.MeshBasicMaterial({ color: COLORS.normal, side: THREE.DoubleSide, transparent: true, opacity: 0.5 });
        const ring = new THREE.Mesh(new THREE.RingGeometry(0.72, 0.82, 40), ringMat);
        ring.rotation.x = -Math.PI / 2; ring.position.y = 0.03; group.add(ring);

        const label = createLabel(patient.name || patient.patient_id);
        group.add(label);

        const painMat = new THREE.MeshBasicMaterial({ color: 0xff0000, transparent: true, opacity: 0 });
        const painIndicator = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 8), painMat);
        group.add(painIndicator);

        scene.add(group);

        const a = {
            group, body, pelvis, torso, neck, arms, legs, ring, ringMat, painIndicator, painMat, label, head,
            room: patient.room, state: 'normal', pose: null, poses: null,
            bed: HospitalScene.getBedParts(patient.room),
        };
        a.poses = poses(BED());
        groundPose(a, a.poses.fall);
        a.pose = a.poses.normal;
        applyNow(a, a.pose);
        syncExtras(a, true);

        group.traverse(c => { if (c.isMesh) c.userData.patientId = patient.patient_id; });
        avatars[patient.patient_id] = a;
    }

    function createLabel(text) {
        const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 64;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'rgba(15,23,42,0.85)'; ctx.fillRect(0, 0, 256, 64);
        ctx.strokeStyle = 'rgba(59,130,246,0.6)'; ctx.lineWidth = 2; ctx.strokeRect(0, 0, 256, 64);
        ctx.fillStyle = '#f1f5f9'; ctx.font = 'bold 24px Inter, sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, 128, 32);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true }));
        sprite.scale.set(1.3, 0.325, 1); sprite.renderOrder = 10;
        return sprite;
    }

    function poseKey(p) {
        if (p.fall_detected) return 'fall';
        if (p.pain_detected) return 'pain';
        return 'normal';
    }

    // ring / label / bed backrest / blanket targets
    function syncExtras(a, instant) {
        const p = a.pose;
        a.ring.position.x = p.ring[0]; a.ring.position.z = p.ring[1];
        a.ring.scale.set(p.ring[2], p.ring[3], 1);
        a.label.position.set(p.label[0], p.label[1], p.label[2]);
        if (a.bed && instant) { a.bed.backrest.rotation.x = p.backrest; a.bed.blanket.scale.z = p.blanket; }
    }

    function updateAvatarState(patient) {
        const a = avatars[patient.patient_id];
        if (!a) return;
        const { ringMat, painMat } = a;

        if (patient.fall_detected && patient.pain_detected) { ringMat.color.setHex(COLORS.fall_pain); ringMat.opacity = 0.9; }
        else if (patient.fall_detected) { ringMat.color.setHex(COLORS.fall); ringMat.opacity = 0.9; }
        else if (patient.pain_detected) { ringMat.color.setHex(COLORS.pain); ringMat.opacity = 0.8; }
        else { ringMat.color.setHex(COLORS.normal); ringMat.opacity = 0.5; }
        painMat.opacity = patient.pain_detected ? 0.9 : 0;

        a.pose = a.poses[poseKey(patient)];
        a.state = patient.state;
        syncExtras(a, false);
    }

    function resetAll() {
        Object.keys(avatars).forEach(id => {
            const p = PatientStateManager.getPatient(id);
            updateAvatarState(p || { patient_id: id, state: 'normal', fall_detected: false, pain_detected: false });
        });
    }

    const _v = new THREE.Vector3();
    function update(delta) {
        const time = Date.now() * 0.001;
        const k = 1 - Math.exp(-6 * Math.min(delta, 0.1));
        Object.values(avatars).forEach(a => {
            // blend joints toward the target pose
            Object.keys(JOINT).forEach(key => {
                const o = JOINT[key](a), v = a.pose[key];
                o.x += (v[0] - o.x) * k; o.y += (v[1] - o.y) * k; o.z += (v[2] - o.z) * k;
            });
            if (a.bed) {
                a.bed.backrest.rotation.x += (a.pose.backrest - a.bed.backrest.rotation.x) * k;
                a.bed.blanket.scale.z += (a.pose.blanket - a.bed.blanket.scale.z) * k;
            }
            const pr = a.pose.ring;
            a.ring.position.x += (pr[0] - a.ring.position.x) * k; a.ring.position.z += (pr[1] - a.ring.position.z) * k;
            a.ring.scale.x += (pr[2] - a.ring.scale.x) * k; a.ring.scale.y += (pr[3] - a.ring.scale.y) * k;
            const lp = a.pose.label;
            a.label.position.x += (lp[0] - a.label.position.x) * k; a.label.position.y += (lp[1] - a.label.position.y) * k; a.label.position.z += (lp[2] - a.label.position.z) * k;

            if (a.state !== 'normal') a.ringMat.opacity = 0.6 + 0.3 * Math.sin(time * 4);
            if (a.painMat.opacity > 0) {
                a.painMat.opacity = 0.5 + 0.5 * Math.sin(time * 6);
                a.head.getWorldPosition(_v);
                a.group.worldToLocal(_v);
                a.painIndicator.position.copy(_v).add(new THREE.Vector3(0, 0.4, 0));
            }
        });
    }

    function getAvatarAtPosition(raycaster) {
        const scene = HospitalScene.getScene();
        if (!scene) return null;
        for (const hit of raycaster.intersectObjects(scene.children, true)) {
            if (hit.object.userData.patientId) return hit.object.userData.patientId;
        }
        return null;
    }

    return { init, update, getAvatarAtPosition };
})();