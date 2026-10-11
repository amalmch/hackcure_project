"""
Prédiction des crises (V2, étape 8) — scores déterministes et transparents.

Pour chaque patient : un **risque** (0–100) et, si une tendance le permet, une **fenêtre de temps approximative**
avant la crise, pour cinq conditions : crise d'épilepsie, sepsis / choc septique, événement cardiaque,
détérioration générale, complications du diabète (hypoglycémie, acidocétose).

Méthode : règles cliniques connues (qSOFA, NEWS2, seuils) + extrapolation linéaire des tendances avec un
intervalle d'incertitude. Estimation de prototype, non validée cliniquement.
"""

from __future__ import annotations

import os

from typing import Any, Optional, Sequence

LABELS = {"seizure": "Crise d'épilepsie", "sepsis": "Sepsis / choc septique", "cardiac": "Infarctus / événement cardiaque", "deterioration": "Détérioration générale", "diabetes": "Complication du diabète"}
RISK_TYPES = {"seizure": "predicted_seizure", "sepsis": "predicted_sepsis", "cardiac": "predicted_cardiac", "deterioration": "predicted_deterioration", "diabetes": "predicted_glycemia"}


def level(risk: float) -> str:
    return "critique" if risk >= 80 else "élevé" if risk >= 60 else "modéré" if risk >= 30 else "faible"


MIN_SPAN_S = float(os.environ.get("PREDICTION_MIN_SPAN_S", "90"))  # durée minimale d'observation pour parler d'une tendance
NEWS2_RISE = 0.1  # point par minute : en dessous, la variation du NEWS2 relève du bruit de mesure


def slope_per_min(series: Sequence[tuple[float, float]], window_s: float = 600.0) -> Optional[float]:
    """Pente (unités par minute) par régression linéaire sur la fenêtre ; None s'il y a trop peu de points."""
    if not series:
        return None
    t_end = series[-1][0]
    pts = [(t, v) for t, v in series if t_end - t <= window_s]
    if len(pts) < 8 or pts[-1][0] - pts[0][0] < MIN_SPAN_S:
        return None
    n = len(pts)
    mt, mv = sum(t for t, _ in pts) / n, sum(v for _, v in pts) / n
    den = sum((t - mt) ** 2 for t, _ in pts)
    if den <= 0:
        return None
    return sum((t - mt) * (v - mv) for t, v in pts) / den * 60.0


def window_to(current: Optional[float], threshold: float, slope: Optional[float], uncertainty: float = 0.4) -> Optional[dict[str, Any]]:
    """Temps estimé avant que `current` franchisse `threshold` à la pente actuelle, avec ± `uncertainty`.
    None si la valeur ne s'en approche pas."""
    if current is None or slope is None or abs(slope) < 1e-6:
        return None
    minutes = (threshold - current) / slope
    if minutes <= 0 or minutes > 24 * 60:
        return None
    lo, hi = minutes * (1 - uncertainty), minutes * (1 + uncertainty)
    return fmt_window(lo, hi)


def fmt_window(lo_min: float, hi_min: float) -> dict[str, Any]:
    lo_min, hi_min = max(0.0, lo_min), max(1.0, hi_min)
    if hi_min >= 120:
        text = f"~{lo_min / 60:.0f}–{hi_min / 60:.0f} h"
    else:
        text = f"~{lo_min:.0f}–{hi_min:.0f} min"
    return {"min_minutes": round(lo_min, 1), "max_minutes": round(hi_min, 1), "text": text}


def _has(text: str, *keys: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in keys)


def _result(key: str, parts: list[tuple[bool, float, str]], window: Optional[dict[str, Any]], data_points: int, needed: int) -> dict[str, Any]:
    used = [(w, t) for ok, w, t in parts if ok]
    risk = round(min(100.0, sum(w for w, _ in used)))
    conf = "élevée" if data_points >= needed and window else ("moyenne" if data_points >= max(1, needed // 2) else "faible")
    return {"key": key, "label": LABELS[key], "risk": risk, "level": level(risk), "window": window if risk >= 30 else None, "confidence": conf,
            "factors": [t for _, t in sorted(used, key=lambda x: -x[0])]}


def predict(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """`ctx` : vitals {hr, sys, rr, spo2, tempC, glucose, st}, news2, qsofa, history, treatments, labs {code: {value}}, expression,
    kp_variance, rhythmic_hz, sleep_hours, missed_antiepileptic (int), series {hr, sys, rr, spo2, tempC, glucose, news2: [(t, v)]}."""
    v = ctx.get("vitals") or {}
    labs = ctx.get("labs") or {}
    lab = lambda c: (labs.get(c) or {}).get("value")  # noqa: E731
    hist, tr = ctx.get("history") or "", ctx.get("treatments") or ""
    ser = ctx.get("series") or {}
    sl = {k: slope_per_min(ser.get(k) or []) for k in ("hr", "sys", "rr", "spo2", "tempC", "glucose", "news2", "st")}
    hr, sys_, rr, temp, glu, st = v.get("hr"), v.get("sys"), v.get("rr"), v.get("tempC"), v.get("glucose"), v.get("st")
    news2, qsofa = ctx.get("news2"), ctx.get("qsofa") or 0
    out = []

    # 1) crise d'épilepsie
    epi = _has(hist, "épilep", "epilep", "comitial")
    missed = int(ctx.get("missed_antiepileptic") or 0)
    kv, hz = ctx.get("kp_variance") or 0.0, ctx.get("rhythmic_hz") or 0.0
    rhythmic = kv >= 0.25 and 2.0 <= hz <= 8.0
    sleep_h = ctx.get("sleep_hours")
    win = fmt_window(0, 5) if rhythmic else (fmt_window(60, 360) if epi and missed >= 2 else (fmt_window(240, 1440) if epi and missed == 1 else None))
    out.append(_result("seizure", [
        (epi, 22, "épilepsie connue au dossier"), (missed >= 1, min(36, 18 * missed), f"{missed} dose(s) d'antiépileptique manquée(s)"),
        (sleep_h is not None and sleep_h < 4.5, 12, f"privation de sommeil (≈ {sleep_h} h)"), (temp is not None and temp >= 38.0, 10, f"fièvre {temp} °C (abaisse le seuil épileptogène)"),
        (rhythmic, 55, f"mouvements rythmiques anormaux vus par la caméra ({hz:.0f} Hz, variance {kv:.2f})"),
    ], win, int(epi) + missed + int(rhythmic) * 2, 2))

    # 2) sepsis / choc septique
    lact, crp, pct = lab("LACT"), lab("CRP"), lab("PCT")
    w_sys = window_to(sys_, 90.0, sl["sys"]) if sl["sys"] is not None and sl["sys"] < -0.3 else None
    out.append(_result("sepsis", [
        (qsofa >= 1, 16 * qsofa, f"qSOFA {qsofa}/3"), (news2 is not None and news2 >= 5, min(24, 3 * (news2 or 0)), f"NEWS2 {news2}"),
        (temp is not None and temp >= 38.0, 8, f"température {temp} °C"), (sl["hr"] is not None and sl["hr"] > 0.8, 8, f"FC en hausse (+{sl['hr']:.1f}/min par minute)" if sl["hr"] else ""),
        (sl["sys"] is not None and sl["sys"] < -0.5, 10, f"PA en baisse ({sl['sys']:.1f} mmHg par minute)" if sl["sys"] else ""), (sl["rr"] is not None and sl["rr"] > 0.3, 6, "FR en hausse"),
        (lact is not None and lact > 2, 14, f"lactates {lact} mmol/L"), (crp is not None and crp > 100, 6, f"CRP {crp:.0f} mg/L" if crp else ""), (pct is not None and pct > 2, 8, f"procalcitonine {pct} ng/mL"),
    ], w_sys, sum(len(ser.get(k) or []) >= 8 for k in ("hr", "sys", "rr")) + int(lact is not None), 3))

    # 3) infarctus / événement cardiaque
    tropo = lab("TROPO")
    w_st = fmt_window(0, 20) if st is not None and st >= 2.0 else (window_to(st, 2.0, sl["st"]) if st is not None and sl["st"] and sl["st"] > 0.02 else None)
    out.append(_result("cardiac", [
        (st is not None and st >= 2.0, 48, f"sus-décalage ST {st} mm" if st is not None else ""), (st is not None and 1.0 <= st < 2.0, 30, f"sus-décalage ST {st} mm" if st is not None else ""),
        (hr is not None and hr >= 110, 8, f"FC {hr:.0f}/min" if hr else ""), (sys_ is not None and (sys_ < 95 or sys_ > 170), 8, f"PAS {sys_:.0f} mmHg" if sys_ else ""),
        (_has(hist, "cardiaque", "coronar", "infarctus", "hta", "fibrillation"), 10, "antécédents cardiovasculaires"), (ctx.get("expression") == "pain", 10, "expression de douleur"),
        (tropo is not None and tropo > 14, 22 if (tropo or 0) <= 100 else 30, f"troponine {tropo:.0f} ng/L" if tropo else ""),
    ], w_st, int(st is not None) + int(tropo is not None) + int(len(ser.get("st") or []) >= 8), 2))

    # 4) détérioration générale (NEWS2 et sa pente)
    w_news = window_to(news2, 7.0, sl["news2"]) if news2 is not None and news2 < 7 and sl["news2"] and sl["news2"] >= NEWS2_RISE else (fmt_window(0, 15) if news2 is not None and news2 >= 7 else None)
    out.append(_result("deterioration", [
        (news2 is not None and news2 >= 3, min(60, 8 * (news2 or 0)), f"NEWS2 {news2}"), (sl["news2"] is not None and sl["news2"] >= NEWS2_RISE, min(25, 100 * (sl["news2"] or 0)), f"NEWS2 en hausse (+{(sl['news2'] or 0) * 10:.1f} point(s) en 10 min)"),
        (sl["spo2"] is not None and sl["spo2"] < -0.2, 8, "SpO2 en baisse"), (sl["hr"] is not None and sl["hr"] > 0.8, 6, "FC en hausse"), (sl["sys"] is not None and sl["sys"] < -0.5, 6, "PA en baisse"),
    ], w_news, len(ser.get("news2") or []) // 8 + int(news2 is not None), 2))

    # 5) complications du diabète
    diabetic = _has(hist, "diab") or _has(tr, "metformine", "insuline")
    w_glu = None
    if glu is not None:
        if glu < 0.7:
            w_glu = fmt_window(0, 15)
        elif sl["glucose"] is not None and sl["glucose"] < -0.005 and glu < 1.4:
            w_glu = window_to(glu, 0.6, sl["glucose"])
        elif glu >= 3.0:
            w_glu = fmt_window(60, 360)
    out.append(_result("diabetes", [
        (glu is not None and glu < 0.7, 62, f"glycémie capillaire {glu} g/L (hypoglycémie)"), (glu is not None and glu < 0.54, 22, "glycémie < 0,54 g/L (hypoglycémie sévère)"),
        (glu is not None and 0.7 <= glu < 0.9 and (sl["glucose"] or 0) < -0.005, 34, f"glycémie {glu} g/L en baisse rapide"), (glu is not None and glu >= 2.5, 40, f"glycémie capillaire {glu} g/L (hyperglycémie)"),
        (glu is not None and glu >= 3.0 and (rr or 0) >= 22, 20, "hyperglycémie + polypnée (risque d'acidocétose)"), (diabetic, 8, "diabète traité"), (_has(tr, "insuline"), 8, "sous insuline"),
        ((lab("CETO") or 0) > 0.6, 18, f"cétonémie {lab('CETO')} mmol/L"),
    ], w_glu, int(glu is not None) + int(len(ser.get("glucose") or []) >= 8), 2))
    return out
