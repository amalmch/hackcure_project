"""
Moteur de simulation (chambres virtuelles + appareils médicaux de toutes les chambres).

Indépendant du transport : le moteur produit des couples `(topic, payload)` conformes aux
contrats (`contracts/schemas`) via un callback `publish`. Il est utilisé :
- embarqué dans le serveur (`dashboard/app/sim/embedded.py`, transport direct) ;
- en processus autonome (`simulator/sim.py`, transport HTTP ou MQTT).

Chambres : 102–104 sont des avatars virtuels complets (vision, env, appareils). La 101 est la
chambre réelle : ses appareils sont simulés ; sa vision/thermique le sont aussi **tant qu'aucun
edge réel n'a parlé** (`engine.set_room_virtual("101", False)` pour couper).
"""

from __future__ import annotations

import logging
import math
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger("hackcure.sim")

# Intégrité des trames (V3) : primitives partagées `contracts/integrity.py` (bibliothèque standard uniquement).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    from contracts.integrity import Signer  # noqa: E402
except Exception:  # dossier `contracts/` absent : pas de signature
    Signer = None  # type: ignore

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
DEVICE_TYPES = ["iv_pump", "nutrition_pump", "transfusion", "bp", "ecg", "oxygen", "spo2", "thermometer", "glucometer"]
Publish = Callable[[str, dict[str, Any]], Any]


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Profile:
    """Profil physiologique de base d'un patient (valeurs de repos)."""

    hr: float = 72
    spo2: float = 97
    sys: float = 125
    dia: float = 78
    temp: float = 36.8
    rr: float = 16
    glucose: float = 0.95  # glycémie capillaire (g/L)
    variability: float = 1.0
    rhythm: str = "sinus"
    oxygen_flow: float = 0.0
    iv_rate: float = 80
    nutrition_rate: float = 0.0
    transfusion_rate: float = 0.0


DEFAULT_PROFILES: dict[str, Profile] = {
    "101": Profile(glucose=1.45, hr=78, spo2=96, sys=138, dia=82, temp=37.1, rr=18, oxygen_flow=1.0, iv_rate=83),  # pneumopathie, diabète
    "102": Profile(hr=84, spo2=97, sys=112, dia=70, temp=36.7, rr=18, rhythm="afib", iv_rate=42, variability=1.4),  # insuff. cardiaque
    "103": Profile(hr=86, spo2=91, sys=130, dia=76, temp=36.9, rr=19, oxygen_flow=2.0, iv_rate=63, nutrition_rate=60),  # BPCO
    "104": Profile(hr=76, spo2=97, sys=118, dia=72, temp=37.0, rr=16, iv_rate=100, transfusion_rate=120),  # post-op hanche
}


@dataclass
class Trend:
    target: float
    remaining: float  # secondes
    hold: float = 0.0  # maintien après atteinte (0 = permanent)


@dataclass
class VirtualRoom:
    room: str
    profile: Profile
    virtual_vision: bool = True  # False si un edge réel alimente la vision/thermique
    autonomous: bool = True  # petits comportements aléatoires (réveil, toilettes...)

    posture: str = "lying_bed"
    activity: str = "awake_bed"
    zone: str = "bed"
    confidence: float = 0.9
    expression: str = "neutral"
    expression_conf: float = 0.6
    persons: int = 1
    staff_inside: bool = False
    staff_role: Optional[str] = None  # nurse | duty_doctor | psychiatrist… (avatar affiché dans la 3D)
    occupied: bool = True  # False : chambre libre, rien n'est publié
    seizure_motion: float = 0.0  # 0..1 : mouvements rythmiques anormaux vus par la caméra (variance des keypoints)
    staff_since: Optional[float] = None
    patient_track: int = 1
    last_zone_before_absent: str = "bed"
    still_since: float = field(default_factory=time.time)

    skin_temp: float = 36.6
    thermal_calibrated: bool = False
    env_temp: float = 22.5
    env_offset: float = 0.0  # source de chaleur ou de froid dans la chambre (soleil, radiateur bloqué…) en °C
    outdoor_temp: float = 18.0
    env_hum: float = 45.0
    door_open: bool = False
    motion: bool = False
    equipment: dict[str, str] = field(default_factory=lambda: {"window": "closed", "heater": "off", "ac": "off", "light": "off"})

    vitals: dict[str, float] = field(default_factory=dict)
    trends: dict[str, Trend] = field(default_factory=dict)
    iv_volume: float = 480.0
    nutrition_volume: float = 500.0
    transfusion_volume: float = 300.0
    occlusion: bool = False
    reaction: bool = False
    call_pressed: bool = False
    device_status: dict[str, str] = field(default_factory=dict)
    faults: dict[str, dict[str, str]] = field(default_factory=dict)  # pannes d'appareil : {type: {code, label}}

    # cadence des publications
    _next: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        p = self.profile
        self.vitals = {"hr": p.hr, "spo2": p.spo2, "sys": p.sys, "dia": p.dia, "temp": p.temp, "rr": p.rr, "glucose": p.glucose, "st": 0.0}
        self.skin_temp = p.temp - 0.4
        for t in DEVICE_TYPES:
            self.device_status[t] = "running"
        if p.nutrition_rate <= 0:
            self.device_status["nutrition_pump"] = "standby"
        if p.transfusion_rate <= 0:
            self.device_status["transfusion"] = "standby"
        if p.oxygen_flow <= 0:
            self.device_status["oxygen"] = "standby"

    # ── physiologie ─────────────────────────────────────────────────────────
    def step(self, dt: float, now: float, night: bool) -> None:
        p = self.profile
        base = {"hr": p.hr, "spo2": p.spo2, "sys": p.sys, "dia": p.dia, "temp": p.temp, "rr": p.rr, "glucose": p.glucose, "st": 0.0}
        # modulations par l'état
        if self.activity == "sleeping":
            base["hr"] -= 6
            base["rr"] -= 2
        elif self.activity in ("out_of_bed", "toilet"):
            base["hr"] += 10
            base["sys"] += 6
        if self.activity == "fall":
            base["hr"] += 32
            base["sys"] -= 18
            base["rr"] += 6
        if self.expression == "pain":
            base["hr"] += 12
            base["sys"] += 10
        # tendances actives
        for metric, tr in list(self.trends.items()):
            if metric not in self.vitals:
                del self.trends[metric]
                continue
            if tr.remaining > 0:
                k = min(1.0, dt / tr.remaining)
                self.vitals[metric] += (tr.target - self.vitals[metric]) * k
                tr.remaining -= dt
                base[metric] = self.vitals[metric]
            else:
                base[metric] = tr.target
                if tr.hold > 0:
                    tr.hold -= dt
                    if tr.hold <= 0:
                        del self.trends[metric]
        # relaxation vers la base + bruit
        for m, b in base.items():
            tau = 25.0 if m != "temp" else 180.0
            self.vitals[m] += (b - self.vitals[m]) * min(1.0, dt / tau)
            # bruit par pas ; écart-type au repos ≈ bruit × 3,5 (× 9,5 pour la température) : FC ± 2,5 · PAS ± 3 · SpO2 ± 0,5 · FR ± 0,9 · T° ± 0,08
            noise = {"hr": 0.7, "spo2": 0.15, "sys": 0.8, "dia": 0.7, "temp": 0.008, "rr": 0.25, "glucose": 0.006, "st": 0.01}[m] * p.variability
            self.vitals[m] += random.gauss(0, noise) * math.sqrt(min(dt, 1.0))
        self.vitals["hr"] = max(28, min(200, self.vitals["hr"]))
        self.vitals["spo2"] = max(70, min(100, self.vitals["spo2"]))
        self.vitals["sys"] = max(60, min(230, self.vitals["sys"]))
        self.vitals["dia"] = max(35, min(140, min(self.vitals["dia"], self.vitals["sys"] - 20)))
        self.vitals["temp"] = max(34.0, min(42.0, self.vitals["temp"]))
        self.vitals["rr"] = max(6, min(45, self.vitals["rr"]))
        self.vitals["glucose"] = max(0.3, min(6.0, self.vitals["glucose"]))
        self.vitals["st"] = max(-1.0, min(6.0, self.vitals["st"]))
        # température cutanée (caméra thermique) suit la température centrale
        # la peau suit la température centrale, et se réchauffe aussi dans une chambre trop chaude (sans fièvre)
        skin_target = self.vitals["temp"] - 0.4 + max(0.0, self.env_temp - 25.0) * 0.3
        self.skin_temp += (skin_target - self.skin_temp) * min(1.0, dt / 60.0) + random.gauss(0, 0.02)

        # appareils
        if self.device_status["iv_pump"] == "running" and not self.occlusion:
            self.iv_volume = max(0.0, self.iv_volume - p.iv_rate * dt / 3600.0)
        if self.device_status["nutrition_pump"] == "running":
            self.nutrition_volume = max(0.0, self.nutrition_volume - p.nutrition_rate * dt / 3600.0)
        if self.device_status["transfusion"] == "running":
            self.transfusion_volume = max(0.0, self.transfusion_volume - p.transfusion_rate * dt / 3600.0)

        # environnement : dérive + effet des équipements
        target_env = 22.5 + (1.5 if night is False else -0.5) + self.env_offset
        if self.equipment.get("heater") == "on":
            target_env += 4.5
        if self.equipment.get("ac") == "on":
            target_env -= 4.5
        if self.equipment.get("window") == "open":
            target_env += (self.outdoor_temp - target_env) * 0.45  # l'air extérieur tire la chambre vers sa température
        self.env_temp += (target_env - self.env_temp) * min(1.0, dt / 60.0) + random.gauss(0, 0.02)
        self.env_hum += (45 - self.env_hum) * min(1.0, dt / 600.0) + random.gauss(0, 0.1)
        self.motion = self.activity not in ("sleeping",) and (random.random() < 0.6 or self.staff_inside)

        # comportements autonomes (chambres virtuelles uniquement)
        if self.autonomous and self.virtual_vision and self.activity not in ("fall",) and not self.staff_inside:
            self._autonomy(dt, now, night)

    def _autonomy(self, dt: float, now: float, night: bool) -> None:
        r = random.random()
        per_min = dt / 60.0
        if self.activity == "awake_bed" and night and r < 0.15 * per_min:
            self.set_posture("lying_bed", "sleeping", "bed")
        elif self.activity == "sleeping" and not night and r < 0.2 * per_min:
            self.set_posture("lying_bed", "awake_bed", "bed")
        elif self.activity == "awake_bed" and not night and r < 0.04 * per_min:
            self.set_posture("sitting_chair", "out_of_bed", "floor")
        elif self.posture == "sitting_chair" and r < 0.08 * per_min:
            self.set_posture("lying_bed", "awake_bed", "bed")

    # ── actions de scénario ─────────────────────────────────────────────────
    def set_posture(self, posture: str, activity: str | None = None, zone: str | None = None, confidence: float = 0.9) -> None:
        if posture != self.posture:
            self.still_since = time.time()
        self.posture = posture
        default_activity = {
            "lying_bed": "awake_bed", "sitting_bed": "awake_bed", "sitting_chair": "out_of_bed", "standing": "out_of_bed",
            "walking": "out_of_bed", "on_floor": "fall", "absent": "out_of_room",
        }[posture]
        default_zone = {"lying_bed": "bed", "sitting_bed": "bed", "sitting_chair": "floor", "standing": "floor", "walking": "floor", "on_floor": "floor", "absent": "exit"}[posture]
        self.activity = activity or default_activity
        self.zone = zone or default_zone
        self.confidence = confidence
        if posture != "absent":
            self.last_zone_before_absent = self.zone

    def fall(self) -> None:
        self.set_posture("on_floor", "fall", "floor", 0.93)
        self.expression, self.expression_conf = "pain", 0.78

    def recover(self) -> None:
        self.set_posture("lying_bed", "awake_bed", "bed", 0.92)
        self.expression, self.expression_conf = "neutral", 0.7
        self.call_pressed = False

    def staff_enter(self, persons: int = 2, role: Optional[str] = None) -> None:
        self.staff_role = role or "nurse"
        self.staff_inside = True
        self.persons = max(2, persons)
        self.staff_since = time.time()

    def staff_leave(self) -> float:
        dur = time.time() - (self.staff_since or time.time())
        self.staff_inside = False
        self.staff_role = None
        self.persons = 0 if self.posture == "absent" else 1
        self.staff_since = None
        return dur

    def trend(self, metric: str, target: float, duration: float, hold: float = 0.0) -> None:
        self.trends[metric] = Trend(target=target, remaining=max(0.1, duration), hold=hold)
        if metric == "env_temp":
            pass

    def apply_command(self, equipment: str, action: str, value: Any = None) -> tuple[bool, str]:
        """Comportement d'un edge virtuel face à `cmd/{equipment}`."""
        if equipment not in self.equipment and equipment != "buzzer":
            return False, "unknown"
        if equipment == "window":
            new = "open" if action in ("open", "on") else "closed"
        elif equipment == "buzzer":
            return True, "on" if action == "on" else "off"
        else:
            new = "on" if action in ("on", "open") else "off"
        self.equipment[equipment] = new
        return True, new

    # ── publications ────────────────────────────────────────────────────────
    def due(self, key: str, period: float, now: float) -> bool:
        nxt = self._next.get(key, 0.0)
        if now >= nxt:
            self._next[key] = now + period
            return True
        return False

    def messages(self, now: float, source: str = "sim") -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        ts = iso_now()
        pre = f"hackcure/room/{self.room}"
        if self.virtual_vision:
            if self.due("vision", 0.5, now):
                persons = self.persons if self.posture != "absent" else (1 if self.staff_inside else 0)
                out.append((f"{pre}/vision/state", {
                    "ts": ts, "source": source, "persons": persons,
                    "patientTrackId": None if self.posture == "absent" else self.patient_track,
                    "posture": self.posture, "activity": self.activity, "zone": self.zone,
                    "confidence": round(min(0.99, max(0.3, self.confidence + random.gauss(0, 0.02))), 3),
                    "cvClass": {"lying_bed": "patient_lying", "sitting_bed": "patient_sitting", "sitting_chair": "patient_sitting",
                                "standing": "patient_moving_out", "walking": "patient_moving_out", "on_floor": "patient_fallen", "absent": "patient_out"}[self.posture],
                    "floorPos": None if self.posture in ("lying_bed", "sitting_bed", "absent") else {"x": round(random.uniform(0.2, 0.8), 2), "y": round(random.uniform(0.3, 0.9), 2)},
                    # variance des points clés du squelette (0 = immobile) et fréquence dominante du mouvement, calculées par l'edge
                    "kpVariance": round(max(0.0, 0.02 + self.seizure_motion * 0.6 + random.gauss(0, 0.005)), 3), "rhythmicHz": round(4.0 + random.gauss(0, 0.2), 1) if self.seizure_motion > 0.3 else 0.0,
                }))
            if self.due("expression", 3.0, now):
                out.append((f"{pre}/vision/expression", {"ts": ts, "source": source, "expression": self.expression, "confidence": round(self.expression_conf, 2)}))
            if self.due("thermal", 1.0, now):
                out.append((f"{pre}/thermal", {"ts": ts, "source": source, "skinTempC": round(self.skin_temp, 2), "maxTempC": round(self.skin_temp + 0.3, 2), "calibrated": self.thermal_calibrated}))
            if self.due("env", 5.0, now):
                out.append((f"{pre}/env", {"ts": ts, "source": source, "tempC": round(self.env_temp, 2), "humidity": round(self.env_hum, 1), "motion": self.motion, "doorOpen": self.door_open or self.staff_inside, "outdoorC": round(self.outdoor_temp, 1)}))
            if self.call_pressed and self.due("call", 10.0, now):
                out.append((f"{pre}/call", {"ts": ts, "source": source, "pressed": True}))
        if self.due("devices", 1.0, now):
            out.extend(self.device_messages(ts, source))
        return out

    def device_messages(self, ts: str, source: str = "sim") -> list[tuple[str, dict[str, Any]]]:
        v, p = self.vitals, self.profile
        pre = f"hackcure/room/{self.room}/device"
        sys_, dia = round(v["sys"]), round(v["dia"])
        hr = round(v["hr"])
        rhythm = p.rhythm
        if hr > 110:
            rhythm = "tachy" if p.rhythm == "sinus" else p.rhythm
        elif hr < 50:
            rhythm = "brady"
        if self.activity == "fall" and random.random() < 0.3:
            rhythm = "artifact"
        iv_status = "alarm" if (self.occlusion or self.iv_volume < 50) else self.device_status["iv_pump"]
        tr_status = "alarm" if self.reaction else self.device_status["transfusion"]
        msgs = [
            (f"{pre}/{self.room}-iv_pump", {"type": "iv_pump", "status": iv_status, "metrics": {"rateMlH": p.iv_rate if iv_status != "paused" else 0, "volumeLeftMl": round(self.iv_volume, 1), "occlusion": self.occlusion}}),
            (f"{pre}/{self.room}-nutrition_pump", {"type": "nutrition_pump", "status": self.device_status["nutrition_pump"], "metrics": {"rateMlH": p.nutrition_rate, "volumeLeftMl": round(self.nutrition_volume, 1)}}),
            (f"{pre}/{self.room}-transfusion", {"type": "transfusion", "status": tr_status, "metrics": {"rateMlH": p.transfusion_rate, "volumeLeftMl": round(self.transfusion_volume, 1), "reaction": self.reaction}}),
            (f"{pre}/{self.room}-bp", {"type": "bp", "status": "running", "metrics": {"sys": sys_, "dia": dia, "map": round(dia + (sys_ - dia) / 3)}}),
            (f"{pre}/{self.room}-ecg", {"type": "ecg", "status": "running", "metrics": {"hr": hr, "rhythm": rhythm, "rr": round(v["rr"]), "stMm": round(v["st"], 1)}}),
            (f"{pre}/{self.room}-glucometer", {"type": "glucometer", "status": "running", "metrics": {"glucose": round(v["glucose"], 2)}}),
            (f"{pre}/{self.room}-oxygen", {"type": "oxygen", "status": self.device_status["oxygen"], "metrics": {"flowLMin": p.oxygen_flow}}),
            (f"{pre}/{self.room}-spo2", {"type": "spo2", "status": "running", "metrics": {"spo2": round(v["spo2"])}}),
            (f"{pre}/{self.room}-thermometer", {"type": "thermometer", "status": "running", "metrics": {"tempC": round(v["temp"], 1)}}),
        ]
        for _, payload in msgs:  # appareil en panne : état « alarm » + champ fault (contrat device.json)
            if payload["type"] in self.faults:
                payload["status"], payload["fault"] = "alarm", dict(self.faults[payload["type"]])
        return [(t, {"ts": ts, "source": source, **payload}) for t, payload in msgs]


@dataclass
class ScenarioStep:
    at: float
    room: str
    action: str
    params: dict[str, Any]


class Scenario:
    def __init__(self, data: dict[str, Any]):
        self.name: str = data["name"]
        self.description: str = data.get("description", "")
        self.room: str = str(data.get("room", "104"))
        self.duration: float = float(data.get("duration", 0))
        # scénario de résolution : types de risque traités et rôle du soignant qui intervient
        self.resolves: list[str] = list(data.get("resolves", []))
        self.role: Optional[str] = data.get("role")
        self.steps: list[ScenarioStep] = [
            ScenarioStep(at=float(s.get("at", 0)), room=str(s.get("room", self.room)), action=s["action"], params={k: v for k, v in s.items() if k not in ("at", "room", "action")})
            for s in data.get("steps", [])
        ]
        self.steps.sort(key=lambda s: s.at)

    @staticmethod
    def load(name: str) -> "Scenario":
        path = SCENARIOS_DIR / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Scénario inconnu : {name}")
        with open(path, encoding="utf-8") as f:
            return Scenario(yaml.safe_load(f))

    @staticmethod
    def available() -> list[dict[str, Any]]:
        out = []
        for p in sorted(SCENARIOS_DIR.glob("*.yaml")):
            with open(p, encoding="utf-8") as f:
                d = yaml.safe_load(f)
            out.append({"name": d["name"], "description": d.get("description", ""), "room": str(d.get("room", "")), "duration": d.get("duration", 0),
                        "resolves": d.get("resolves", []), "role": d.get("role")})
        return out


class SimEngine:
    """Fait avancer toutes les chambres et publie les messages via `publish(topic, payload)`."""

    def __init__(self, publish: Publish, rooms: list[str] | None = None, speed: float = 1.0, source: str = "sim", profiles: dict[str, Profile] | None = None, hmac_key: Optional[str] = None):
        self.publish = publish
        # intégrité des trames : `seq` + `sig` ajoutés à chaque message si une clé est fournie (`hmac_key`, sinon EDGE_HMAC_KEY) ; rien sinon
        self.signer = Signer(hmac_key) if Signer is not None else None
        self.speed = max(0.1, speed)
        self.source = source
        profiles = profiles or DEFAULT_PROFILES
        self.rooms: dict[str, VirtualRoom] = {r: VirtualRoom(room=r, profile=profiles.get(r, Profile())) for r in (rooms or ["101", "102", "103", "104"])}
        self.sim_time = 0.0
        self.last_real = time.time()
        self.scenario: Optional[Scenario] = None
        self.scenario_t0 = 0.0
        self._pending: list[ScenarioStep] = []
        self.on_scenario_event: Optional[Callable[[str, dict[str, Any]], Any]] = None
        self.night_override: Optional[bool] = None
        self.outdoor_temp = 18.0
        # résolutions (interventions d'un soignant) : jouées en surcouche du scénario principal, une par chambre à la fois
        self.resolutions: dict[str, dict[str, Any]] = {}
        self._resolution_queue: dict[str, list[tuple[str, Optional[str]]]] = {}

    def _send(self, topic: str, payload: dict[str, Any]) -> Any:
        """Point de sortie unique des messages : signature (si une clé est configurée) puis `publish`."""
        if self.signer is not None:
            payload = self.signer.sign(topic, payload)
        return self.publish(topic, payload)

    # ── temps ───────────────────────────────────────────────────────────────
    @property
    def is_night(self) -> bool:
        if self.night_override is not None:
            return self.night_override
        h = datetime.now().hour
        return h >= 22 or h < 6

    def tick(self, real_dt: float | None = None) -> int:
        """Avance la simulation ; renvoie le nombre de messages publiés."""
        now_real = time.time()
        if real_dt is None:
            real_dt = now_real - self.last_real
        self.last_real = now_real
        # un blocage de la boucle (import lourd, pause machine) ne doit jamais faire « sauter » un scénario
        dt = min(max(0.0, real_dt), 2.0) * self.speed
        self.sim_time += dt
        self._run_scenario_steps()
        self._run_resolutions()
        n = 0
        for room in self.rooms.values():
            if not room.occupied:
                continue
            room.step(dt, self.sim_time, self.is_night)
            for topic, payload in room.messages(self.sim_time, self.source):
                self._send(topic, payload)
                n += 1
        return n

    # ── scénarios ───────────────────────────────────────────────────────────
    def start_scenario(self, name: str, room: str | None = None) -> Scenario:
        sc = Scenario.load(name)
        if room:
            sc.room = room
            for s in sc.steps:
                s.room = room
        self.scenario = sc
        self.scenario_t0 = self.sim_time
        self._pending = list(sc.steps)
        logger.info("Scénario « %s » démarré (chambre %s, %d étapes)", sc.name, sc.room, len(sc.steps))
        self._emit("scenario_started", {"name": sc.name, "room": sc.room, "description": sc.description, "duration": sc.duration})
        return sc

    def stop_scenario(self) -> None:
        if self.scenario:
            self._emit("scenario_stopped", {"name": self.scenario.name})
        self.scenario = None
        self._pending = []
        self.resolutions.clear()
        self._resolution_queue.clear()

    def start_resolution(self, name: str, room: str, role: Optional[str] = None) -> Scenario:
        """Lance un scénario `*_resolves` dans une chambre sans interrompre le scénario principal.
        Une intervention à la fois par chambre : les suivantes attendent la sortie du soignant."""
        room = str(room)
        sc = Scenario.load(name)
        sc.room = room
        sc.role = role or sc.role or "nurse"
        for s in sc.steps:
            s.room = room
            if s.action == "staff_enter":
                s.params.setdefault("role", sc.role)
        running = self.resolutions.get(room)
        if running:
            queue = self._resolution_queue.setdefault(room, [])
            if running["scenario"].name != name and all(n != name for n, _ in queue):
                queue.append((name, role))
            return sc
        self.resolutions[room] = {"scenario": sc, "t0": self.sim_time, "pending": list(sc.steps)}
        logger.info("Résolution « %s » démarrée (chambre %s, %s)", sc.name, room, sc.role)
        self._emit("resolution_started", {"name": sc.name, "room": room, "role": sc.role, "description": sc.description, "duration": sc.duration, "resolves": sc.resolves})
        return sc

    def _run_resolutions(self) -> None:
        for room, run in list(self.resolutions.items()):
            sc, elapsed = run["scenario"], self.sim_time - run["t0"]
            while run["pending"] and run["pending"][0].at <= elapsed:
                step = run["pending"].pop(0)
                try:
                    self.apply(step.room, step.action, **step.params)
                    self._emit("resolution_step", {"name": sc.name, "room": room, "action": step.action, "at": step.at, "params": step.params})
                except Exception as exc:
                    logger.exception("Étape de résolution en erreur: %s", exc)
            if not run["pending"] and elapsed >= sc.duration:
                del self.resolutions[room]
                self._emit("resolution_finished", {"name": sc.name, "room": room})
                queue = self._resolution_queue.get(room) or []
                if queue:
                    name, role = queue.pop(0)
                    self.start_resolution(name, room, role)

    def _run_scenario_steps(self) -> None:
        if not self.scenario:
            return
        elapsed = self.sim_time - self.scenario_t0
        while self._pending and self._pending[0].at <= elapsed:
            step = self._pending.pop(0)
            try:
                self.apply(step.room, step.action, **step.params)
                self._emit("scenario_step", {"name": self.scenario.name, "room": step.room, "action": step.action, "at": step.at, "params": step.params})
            except Exception as exc:  # un scénario ne doit jamais tuer le moteur
                logger.exception("Étape de scénario en erreur: %s", exc)
        if not self._pending and self.scenario and (self.scenario.duration <= 0 or elapsed >= self.scenario.duration):
            self._emit("scenario_finished", {"name": self.scenario.name})
            self.scenario = None

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        if self.on_scenario_event:
            try:
                self.on_scenario_event(kind, data)
            except Exception:
                logger.exception("on_scenario_event")

    def apply(self, room: str, action: str, **params: Any) -> None:
        """Applique une action de scénario à une chambre (aussi utilisable directement par l'API)."""
        r = self.rooms[str(room)]
        if action == "posture":
            r.set_posture(params["posture"], params.get("activity"), params.get("zone"), params.get("confidence", 0.9))
        elif action == "fall":
            r.fall()
        elif action == "recover":
            r.recover()
        elif action == "staff_enter":
            r.staff_enter(int(params.get("persons", 2)), params.get("role"))
            self._send(f"hackcure/room/{r.room}/vision/staff", {"ts": iso_now(), "source": self.source, "event": "staff_enter", "persons": r.persons, "role": r.staff_role})
        elif action == "staff_leave":
            dur = r.staff_leave()
            self._send(f"hackcure/room/{r.room}/vision/staff", {"ts": iso_now(), "source": self.source, "event": "staff_leave", "persons": r.persons, "durationSec": round(dur, 1)})
        elif action == "expression":
            r.expression, r.expression_conf = params["expression"], float(params.get("confidence", 0.7))
        elif action == "trend":
            r.trend(params["metric"], float(params["target"]), float(params.get("duration", 60)), float(params.get("hold", 0)))
        elif action == "clear_trends":
            r.trends.clear()
            r.seizure_motion = 0.0
        elif action == "iv_volume":
            r.iv_volume = float(params["volume"])
        elif action == "occlusion":
            r.occlusion = bool(params.get("value", True))
        elif action == "reaction":
            r.reaction = bool(params.get("value", True))
        elif action == "call":
            r.call_pressed = bool(params.get("pressed", True))
            if r.call_pressed:
                self._send(f"hackcure/room/{r.room}/call", {"ts": iso_now(), "source": self.source, "pressed": True})
        elif action == "env":
            if "tempC" in params:  # source de chaleur : la chambre tend vers cette température (les équipements gardent leur effet)
                r.env_offset = float(params["tempC"]) - 22.5
            if "outdoorC" in params:
                self.outdoor_temp = float(params["outdoorC"])
                for rr in self.rooms.values():
                    rr.outdoor_temp = self.outdoor_temp
            if "doorOpen" in params:
                r.door_open = bool(params["doorOpen"])
        elif action == "thermal":
            r.trend("temp", float(params["skinTempC"]) + 0.4, float(params.get("duration", 60)))
        elif action == "equipment":
            r.equipment[params["equipment"]] = params["state"]
        elif action == "seizure":  # mouvements rythmiques anormaux (level 0..1) ; 0 = arrêt
            r.seizure_motion = float(params.get("level", 1.0))
        elif action == "night":
            self.night_override = bool(params.get("value", True))
        elif action == "sleep_all":
            for rr in self.rooms.values():
                if rr.virtual_vision and rr.activity != "fall":
                    rr.set_posture("lying_bed", "sleeping", "bed")
        elif action == "device_status":
            r.device_status[params["device"]] = params["status"]
        elif action == "device_fault":  # panne d'un appareil (code : power, motor, sensor, calibration, battery, comm)
            r.faults[params["device"]] = {"code": str(params.get("code", "reported")), "label": str(params.get("label", ""))}
        elif action == "device_clear":  # appareil remplacé ou réparé (tous si `device` est absent)
            if params.get("device"):
                r.faults.pop(params["device"], None)
            else:
                r.faults.clear()
        elif action == "noop":
            pass
        else:
            raise ValueError(f"Action de scénario inconnue : {action}")

    def set_occupied(self, room: str, occupied: bool) -> None:
        """Chambre libérée (sortie) ou de nouveau occupée (admission) : un nouveau patient repart d'un état de repos."""
        r = self.rooms.get(str(room))
        if not r:
            return
        r.occupied = occupied
        if occupied:
            r.trends.clear()
            r.faults.clear()
            r.__post_init__()
            r.set_posture("lying_bed", "awake_bed", "bed")
            r.expression, r.staff_inside, r.persons, r.seizure_motion = "neutral", False, 1, 0.0

    def set_room_virtual(self, room: str, virtual: bool) -> None:
        if room in self.rooms:
            self.rooms[room].virtual_vision = virtual

    def handle_command(self, room: str, equipment: str, action: str, value: Any = None, command_id: str | None = None) -> None:
        """Un edge virtuel reçoit `cmd/{equipment}` et répond `cmd/ack`."""
        r = self.rooms.get(str(room))
        if not r:
            return
        ok, state = r.apply_command(equipment, action, value)
        self._send(f"hackcure/room/{r.room}/cmd/ack", {"ts": iso_now(), "source": self.source, "equipment": equipment, "action": action, "ok": ok, "state": state, "commandId": command_id})

    def snapshot(self) -> dict[str, Any]:
        return {
            code: {
                "posture": r.posture, "activity": r.activity, "zone": r.zone, "persons": r.persons, "expression": r.expression,
                "staff": r.staff_inside, "virtual_vision": r.virtual_vision, "vitals": {k: round(v, 1) for k, v in r.vitals.items()},
                "env_temp": round(r.env_temp, 1), "equipment": dict(r.equipment), "iv_volume": round(r.iv_volume), "trends": list(r.trends),
            }
            for code, r in self.rooms.items()
        }
