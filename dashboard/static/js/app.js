/**
 * HackCure — Main Application Entry
 * ====================================
 * Initializes WebSocket, all modules, and handles
 * mode switching and click interactions.
 */

(function () {
    'use strict';

    let ws = null;
    let reconnectTimer = null;
    let currentMode = 'demo';
    let initialized = false;
    let pingTimer = null;

    // ── WebSocket ─────────────────────────────────────────
    function connectWebSocket() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/ws`;

        ws = new WebSocket(url);

        ws.onopen = () => {
            console.log('[WS] Connected');
            updateConnectionStatus(true);
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                handleMessage(msg);
            } catch (e) {
                console.error('[WS] Parse error:', e);
            }
        };

        ws.onclose = () => {
            console.log('[WS] Disconnected');
            updateConnectionStatus(false);
            scheduleReconnect();
        };

        ws.onerror = (err) => {
            console.error('[WS] Error:', err);
        };

        // Keepalive ping (one timer only)
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    }

    function scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            console.log('[WS] Reconnecting...');
            connectWebSocket();
        }, 3000);
    }

    function updateConnectionStatus(connected) {
        const el = document.getElementById('connection-status');
        const text = el?.querySelector('.status-text');
        if (el) {
            el.className = connected ? 'status-connected' : 'status-disconnected';
        }
        if (text) {
            text.textContent = connected ? 'Connected' : 'Disconnected';
        }
    }

    // ── Message Handler ───────────────────────────────────
    function handleMessage(msg) {
        switch (msg.type) {
            case 'init':
                if (initialized) {            // reconnect: just resync state, keep the scene
                    currentMode = msg.mode || 'demo';
                    PatientStateManager.resetAll(msg.patients);
                    DemoController.updateVisibility(currentMode);
                    updateModeButtons(currentMode);
                    break;
                }
                initialized = true;
                PatientStateManager.init(msg.patients);
                currentMode = msg.mode || 'demo';
                // Load event history
                if (msg.event_history) {
                    msg.event_history.reverse().forEach(evt => {
                        DashboardUI.addEventToLog(evt);
                    });
                }
                // Init 3D scene after state is ready
                HospitalScene.init();
                AvatarManager.init();
                DashboardUI.init();
                DemoController.init(currentMode);
                setupModeButtons();
                setupClickInteraction();
                break;

            case 'patient_event':
                PatientStateManager.updatePatient(msg);
                break;

            case 'reset':
                PatientStateManager.resetAll(msg.patients);
                break;

            case 'mode_change':
                currentMode = msg.mode;
                DemoController.updateVisibility(msg.mode);
                updateModeButtons(msg.mode);
                break;

            case 'pong':
                break;

            default:
                // Nouveaux types (room_state, agent_log, risk, notification...) : traités par les extensions
                break;
        }
        // Extensions (room-live.js, agents-panel.js, kpi-bar.js...) : écoute globale de tous les messages
        try { window.dispatchEvent(new CustomEvent('hackcure:ws', { detail: msg })); } catch (e) { console.error(e); }
    }

    // ── Mode Switching ────────────────────────────────────
    function setupModeButtons() {
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const mode = btn.dataset.mode;
                if (mode === currentMode) return;

                try {
                    await fetch('/api/mode', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ mode }),
                    });
                } catch (e) {
                    console.error('Mode switch error:', e);
                }
            });
        });
    }

    function updateModeButtons(mode) {
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
    }

    // ── Click Interaction (3D) ────────────────────────────
    function setupClickInteraction() {
        const container = document.getElementById('three-container');
        if (!container) return;

        const raycaster = new THREE.Raycaster();
        const mouse = new THREE.Vector2();

        container.addEventListener('click', (event) => {
            const rect = container.getBoundingClientRect();
            mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

            // Get camera from scene
            const scene = HospitalScene.getScene();
            if (!scene) return;

            // Find camera in the scene's parent
            const camera = scene.parent?.camera || null;

            // Use the renderer's camera instead
            raycaster.setFromCamera(mouse, window._hackcureCamera || raycaster.camera);

            const patientId = AvatarManager.getAvatarAtPosition(raycaster);
            if (patientId) {
                DashboardUI.selectPatient(patientId);
            }
        });
    }

    // ── Bootstrap ─────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        console.log('HackCure Patient Monitoring — Starting...');
        connectWebSocket();
    });
})();