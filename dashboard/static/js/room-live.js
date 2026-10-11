/**
 * HackCure — liaison temps réel chambre → 3D (extension additive).
 * Abonné aux messages WS `room_state` (et `init.room_states`) : pilote les poses supplémentaires,
 * l'expression, le halo thermique, les avatars du personnel, les équipements animés, les étiquettes
 * de valeurs, les moniteurs (vraies constantes) et le liseré de risque.
 */
const RoomLive = (() => {
    'use strict';
    const states = {};
    let sceneReady = false;
    let loopHooked = false;

    function ready() { return sceneReady && typeof HospitalScene !== 'undefined' && HospitalScene.getScene(); }

    function apply(rs) {
        if (!rs || !rs.room) return;
        states[rs.room] = rs;
        if (!ready()) return;
        const pid = rs.patient_id || (PatientStateManager.getPatientList().find(p => p.room === rs.room) || {}).patient_id;
        if (pid && typeof AvatarManager.setPosture === 'function') {
            if (AvatarManager.getPosture(pid) !== rs.posture || rs.posture === 'absent') AvatarManager.setPosture(pid, rs.posture, rs.activity);
            AvatarManager.setExpression(pid, rs.expression);
            AvatarManager.setSkinTemp(pid, rs.skinTempC);
        }
        StaffAvatars.setPresent(rs.room, !!rs.staffPresent || (rs.persons || 0) > 1, rs.persons, rs.staffRole);
        Equipment.setState(rs.room, rs.equipment);
        const v = rs.vitals || {};
        Equipment.setIV(rs.room, v.ivVolumeLeftMl, (rs.devices && rs.devices[rs.room + '-iv_pump'] || {}).metrics?.rateMlH, v.ivOcclusion);
        Equipment.setMonitor(rs.room, v);
        if (v.hr != null) {
            HospitalScene.setMonitorVitals(rs.room, {
                hr: v.hr, spo2: v.spo2, bp: (v.sys != null && v.dia != null) ? `${Math.round(v.sys)}/${Math.round(v.dia)}` : undefined,
                alarm: rs.riskLevel === 'critical' || rs.riskLevel === 'high' || v.hr > 120 || (v.spo2 != null && v.spo2 < 90),
            });
        }
        HospitalScene.setRoomRiskColor(rs.room, rs.riskLevel || 'none');
    }

    function hookLoop() {
        if (loopHooked) return; loopHooked = true;
        // Les extensions s'animent dans la boucle existante via AvatarManager.update (appelé par scene.js)
        const orig = AvatarManager.update;
        AvatarManager.update = function (delta) {
            orig(delta);
            try { StaffAvatars.update(delta); Equipment.update(delta); } catch (e) { console.error('[RoomLive] update', e); }
        };
    }

    window.addEventListener('hackcure:ws', (e) => {
        const m = e.detail;
        if (m.type === 'init') {
            sceneReady = true; hookLoop();
            Object.values(m.room_states || {}).forEach(apply);
        } else if (m.type === 'room_state') {
            apply(m);
        } else if (m.type === 'reset') {
            Object.keys(states).forEach(r => HospitalScene.setRoomRiskColor(r, 'none'));
        }
    });

    return { apply, get: (room) => states[room], all: () => states };
})();

window.RoomLive = RoomLive;
