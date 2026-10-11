"""
EnvironmentAgent — confort thermique : > 27 °C clim, < 19 °C chauffage, fenêtre fermée si l'un est actif,
retour au repos entre 21 et 25 °C. Envoie `cmd/*`, attend `cmd/ack`, ne contredit jamais une règle locale
(alarme locale récente ou refus de l'edge) et ne force pas une commande manuelle récente.
"""

from __future__ import annotations

import time
from typing import Any

from ..bus import Event, bus
from ..ingest import handler
from .base import Agent

COOLDOWN_S = 90.0
MANUAL_HOLD_S = 600.0
COMFORT_LOW, COMFORT_HIGH = 20.0, 23.5  # plage de confort visée pour un patient fébrile


class EnvironmentAgent(Agent):
    name = "EnvironmentAgent"
    description = "Veille au confort thermique et pilote fenêtre, chauffage et climatisation (sans contredire les règles locales de l'edge)."
    patterns = ["hackcure/room/+/env", "hackcure/room/+/cmd/ack", "hackcure/room/+/cmd/+", "internal/reset"]
    tick_interval = 5.0

    def __init__(self) -> None:
        super().__init__()
        self.last_action: dict[str, float] = {}
        self.manual_until: dict[str, float] = {}
        self.local_refusal: dict[str, float] = {}
        self.pending_manual: dict[tuple[str, str], tuple[str, str, str]] = {}
        self.rechecks: dict[str, tuple[float, float, list[str]]] = {}  # room -> (échéance, température de départ, équipements actionnés)
        self.fragile_cache: dict[str, tuple[float, bool, str]] = {}
        self.insight_at: dict[str, float] = {}

    async def handle(self, ev: Event) -> None:
        if ev.topic == "internal/reset":
            self.last_action.clear()
            self.manual_until.clear()
            self.rechecks.clear()
            return
        p = ev.payload
        room, kind, d = p["room"], p["kind"], p["data"]
        if kind == "cmd":
            if d.get("requestedBy") and d["requestedBy"] != self.name and d.get("source") == "server":
                self.manual_until[room] = time.time() + MANUAL_HOLD_S  # un humain (ou n8n) a la main
                self.pending_manual[(room, p.get("groups", {}).get("equipment") or "")] = (d["requestedBy"], d.get("action"), d.get("reason") or "")
            return
        if kind == "cmd_ack":
            who = self.pending_manual.pop((room, d.get("equipment") or ""), None)
            if who:
                await self.log(room, input=f"commande de {who[0]} : {d.get('equipment')} → {who[1]} ({who[2] or 'sans motif'})",
                               reasoning="Commande d'équipement demandée hors EnvironmentAgent : exécutée telle quelle, l'agent s'abstient pendant 10 min. Mesure de confort : elle n'agit sur aucun risque clinique.",
                               output=f"{d.get('equipment')} = {d.get('state')}" if d.get("ok") else f"refusée : {d.get('error') or 'sans accusé'}", status="ok" if d.get("ok") else "error")
            if not d.get("ok") and d.get("error"):
                self.local_refusal[room] = time.time()
                await self.log(room, input=f"ack {d.get('equipment')}/{d.get('action')} refusé : {d.get('error')}", reasoning="Une règle locale de l'edge a priorité : on n'insiste pas pendant 5 min.", output="commande abandonnée")
            return
        if kind != "env":
            return
        await self.evaluate(room, float(d["tempC"]), bool(d.get("doorOpen", False)))

    async def evaluate(self, room: str, temp: float, door_open: bool) -> None:
        now = time.time()
        rs = handler.room_state(room)
        eq = rs.get("equipment", {})
        if now - self.last_action.get(room, 0) < COOLDOWN_S:
            return
        if now < self.manual_until.get(room, 0):
            return
        if now - self.local_refusal.get(room, 0) < 300:
            return
        alarm = rs.get("localAlarm")
        if alarm and alarm.get("reason") in ("fall", "critical"):
            return  # ne jamais interférer pendant une alarme locale
        from .fever import hold_rooms

        if room in hold_rooms:
            return  # fièvre vraie : le bilan clinique et biologique passe avant tout réglage de confort

        actions: list[tuple[str, str, str]] = []
        if temp > 27.0 and eq.get("ac") != "on" and eq.get("window") != "open":
            actions = self.cooling_actions(room, temp, eq)
        elif temp < 19.0 and eq.get("heater") != "on":
            actions.append(("heater", "on", f"température {temp:.1f} °C < 19 °C"))
            if eq.get("window") == "open":
                actions.append(("window", "close", "chauffage actif"))
            if eq.get("ac") == "on":
                actions.append(("ac", "off", "chauffage actif"))
        elif 21.0 <= temp <= 25.0:
            if eq.get("ac") == "on":
                actions.append(("ac", "off", f"température {temp:.1f} °C confortable"))
            if eq.get("heater") == "on":
                actions.append(("heater", "off", f"température {temp:.1f} °C confortable"))
        if temp > 30.0 or temp < 16.0:
            await bus.publish("internal/risk_candidate", {"room": room, "type": "thermal_discomfort", "details": {"tempC": round(temp, 1), "window": eq.get("window"), "heater": eq.get("heater"), "ac": eq.get("ac")}, "source_agent": self.name})
        if not actions:
            return
        self.last_action[room] = now
        async with self.working("acting"):
            results = await self.run_actions(room, actions)
            await self.log(room, input=f"tempC={temp:.1f}, porte {'ouverte' if door_open else 'fermée'}, équipements {eq}",
                           reasoning="Règles : > 27 °C → rafraîchir (fenêtre si l'air extérieur est plus frais et le patient non fragile, sinon clim) ; < 19 °C → chauffage ; 21–25 °C → repos. Commande manuelle récente, règle locale ou bilan de fièvre en cours → abstention.",
                           output="; ".join(results))

    # ── choix du moyen de rafraîchissement ───────────────────────────────────
    def fragile(self, room: str) -> tuple[bool, str]:
        """Patient pour qui on évite le courant d'air d'une fenêtre ouverte (grand âge, BPCO)."""
        cached = self.fragile_cache.get(room)
        if cached and time.time() - cached[0] < 300:
            return cached[1], cached[2]
        frag, why = False, ""
        try:
            from ..db import session_scope
            from ..risks import patient_context

            with session_scope() as s:
                pat = patient_context(s, room).get("patient") or {}
            hist = (pat.get("history") or "").lower()
            if (pat.get("age") or 0) >= 80:
                frag, why = True, f"patient de {pat['age']} ans"
            elif "bpco" in hist:
                frag, why = True, "patient BPCO"
        except Exception:
            pass
        self.fragile_cache[room] = (time.time(), frag, why)
        return frag, why

    def cooling_actions(self, room: str, temp: float, eq: dict[str, Any]) -> list[tuple[str, str, str]]:
        from ..config import settings

        outdoor = (handler.room_state(room).get("env") or {}).get("outdoorC")
        if outdoor is None:
            outdoor = settings.outdoor_temp_c
        frag, why = self.fragile(room)
        actions: list[tuple[str, str, str]] = []
        if eq.get("heater") == "on":
            actions.append(("heater", "off", f"chambre à {temp:.1f} °C"))
        if outdoor <= temp - 3.0 and not frag:
            actions.append(("window", "open", f"chambre à {temp:.1f} °C, {outdoor:.0f} °C dehors : aération"))
        else:
            reason = f"chambre à {temp:.1f} °C ; " + (f"{why} : pas de courant d'air" if frag else f"{outdoor:.0f} °C dehors : aérer ne suffirait pas")
            if eq.get("window") == "open":
                actions.append(("window", "close", "climatisation"))
            actions.append(("ac", "on", reason))
        return actions

    async def run_actions(self, room: str, actions: list[tuple[str, str, str]]) -> list[str]:
        from ..commands import send_command

        out = []
        for equipment, action, why in actions:
            r = await send_command(room, equipment, action, requested_by=self.name, reason=why)
            out.append(f"{equipment} {action} ({why}) → {'ack ' + str(r['ack'].get('state')) if r['ok'] else 'sans ack'}")
        self.last_action[room] = time.time()
        await self.insight(room, actions, out)
        return out

    async def insight(self, room: str, actions: list[tuple[str, str, str]], results: list[str]) -> None:
        """Note de confort rédigée par le LLM (workflow n8n `environment-comfort`), au plus une par chambre toutes les 5 min."""
        now = time.time()
        if not actions or now - self.insight_at.get(room, 0) < 300:
            return
        self.insight_at[room] = now
        from .. import orchestration

        rs = handler.room_state(room)
        frag, why = self.fragile(room)
        await orchestration.ask("environment-comfort", f"{room}:{int(now)}", {"task": "environment_comfort", "chambre": room, "ambiance": rs.get("env"), "equipements": rs.get("equipment"),
                                                                                "actions": [{"equipement": e, "action": a, "motif": w} for e, a, w in actions], "resultats": results,
                                                                                "patient_fragile": why if frag else None, "temperature_cutanee": rs.get("skinTempC")}, room=room)

    async def thermal_rise(self, room: str, a: dict[str, Any]) -> None:
        """Simple hausse thermique signalée par le FeverAgent : action directe, puis revérification."""
        from ..config import settings

        rs = handler.room_state(room)
        eq, temp = rs.get("equipment", {}), a.get("env")
        if time.time() < self.manual_until.get(room, 0):
            await self.log(room, input=f"hausse thermique, chambre {temp} °C", reasoning="Une commande manuelle récente a la main sur cette chambre : abstention.", output="aucune action")
            return
        actions = self.cooling_actions(room, float(temp), eq) if temp is not None and float(temp) >= 25.5 and eq.get("ac") != "on" and eq.get("window") != "open" else []
        async with self.working("acting"):
            results = await self.run_actions(room, actions) if actions else []
            self.rechecks[room] = (time.time() + settings.thermal_recheck_s, float(temp) if temp is not None else 0.0, [e for e, _, _ in actions])
            await self.log(room, input=f"simple hausse thermique : {a.get('criterion')}",
                           reasoning="Pas de fièvre (température centrale normale) : action d'ambiance directe, sans médecin ni bilan. Fenêtre si l'air extérieur est nettement plus frais et que le patient le tolère, sinon climatisation.",
                           output=("; ".join(results) if results else "ambiance déjà prise en charge ou chambre tempérée : surveillance") + f" — revérification dans {settings.thermal_recheck_s:.0f} s")

    async def comfort_for_fever(self, room: str) -> str:
        """Fièvre vraie, après le bilan clinique et biologique : réglage de CONFORT (ce n'est pas un traitement)."""
        rs = handler.room_state(room)
        eq, temp = rs.get("equipment", {}), (rs.get("env") or {}).get("tempC")
        if temp is None:
            note = "Température de la chambre non mesurée : aucun réglage."
            actions: list[tuple[str, str, str]] = []
        elif temp > COMFORT_HIGH:
            actions = self.cooling_actions(room, float(temp), eq) if eq.get("ac") != "on" and eq.get("window") != "open" else []
            note = f"Chambre à {temp:.1f} °C : rafraîchissement doux pour le confort du patient fébrile."
        elif temp < COMFORT_LOW:
            actions = [("heater", "on", f"chambre à {temp:.1f} °C : éviter les frissons")] if eq.get("heater") != "on" else []
            note = f"Chambre à {temp:.1f} °C : léger chauffage pour éviter les frissons."
        else:
            actions, note = [], f"Chambre à {temp:.1f} °C, déjà dans la plage de confort ({COMFORT_LOW:.0f}–{COMFORT_HIGH:.1f} °C) : aucun réglage nécessaire."
        async with self.working("acting"):
            results = await self.run_actions(room, actions) if actions else []
            if results:
                note += " " + "; ".join(results) + "."
            note += " Mesure de confort, pas un traitement de la fièvre."
            await self.log(room, input=f"fièvre vraie en chambre {room} : bilan clinique fait, bilan biologique validé", reasoning="Le confort ne vient qu'après le bilan. Régler la chambre ne traite pas la fièvre et ne résout aucun risque clinique.", output=note)
        return note

    async def on_tick(self) -> None:
        now = time.time()
        for room, (due, start, touched) in list(self.rechecks.items()):
            if now < due:
                continue
            del self.rechecks[room]
            t = handler.room_state(room)["env"].get("tempC")
            ok = t is not None and float(t) <= 25.5
            await self.log(room, input=f"revérification après hausse thermique : chambre {t} °C (départ {start:.1f} °C)",
                           reasoning="Contrôle de l'effet de la mesure d'ambiance quelques minutes plus tard.",
                           output="confort rétabli" if ok else "chambre encore chaude : mesure maintenue, nouvelle évaluation au prochain cycle", status="ok" if ok else "error")
        for room in handler.ROOMS:
            t = handler.room_state(room)["env"].get("tempC")
            if t is not None:
                await self.evaluate(room, float(t), bool(handler.room_state(room)["env"].get("doorOpen")))


from typing import Optional  # noqa: E402

from .. import orchestration as _orchestration  # noqa: E402


@_orchestration.handler("environment-comfort")
async def _on_comfort_note(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    """Note de confort affichée avec l'ambiance de la chambre (`room_state.envNote`)."""
    room = ref.split(":")[0]
    rs = handler.room_state(room)
    rs["envNote"] = {"text": str(result.get("note") or "")[:400], "next_check": str(result.get("next_check") or "")[:160], "provider": meta.get("provider") or "anthropic (n8n)", "ts": time.time()}
    handler._dirty_rooms.add(room)
    return None
