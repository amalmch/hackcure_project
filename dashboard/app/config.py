"""
Configuration centrale (variables d'environnement, fichier .env à la racine).
Aucun secret dans le code : les valeurs par défaut sont des valeurs de démo.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv est optionnel
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = DASHBOARD_DIR.parent
STATIC_DIR = DASHBOARD_DIR / "static"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
CONTRACTS_DIR = PROJECT_ROOT / "contracts"

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    """Lecture paresseuse de l'environnement (réévaluée à l'instanciation)."""

    def __init__(self) -> None:
        self.app_name = "HackCure — Hospital Copilot"
        self.version = "2.0.0"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        # Base de données : SQLite par défaut, SQL Server si DATABASE_URL est défini
        self.database_url = os.getenv("DATABASE_URL") or f"sqlite:///{(DASHBOARD_DIR / 'clinic.db').as_posix()}"
        self.seed_on_startup = _bool("SEED_ON_STARTUP", True)

        # Auth
        self.jwt_secret = os.getenv("JWT_SECRET", "hackcure-dev-secret-change-me-before-production-0123456789")
        self.jwt_algorithm = "HS256"
        self.jwt_expire_minutes = _int("JWT_EXPIRE_MINUTES", 12 * 60)
        self.auth_required = _bool("AUTH_REQUIRED", True)
        self.cookie_name = "hackcure_token"
        self.demo_password = os.getenv("DEMO_PASSWORD", "hackcure2026")

        # LLM
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock").lower()
        self.llm_model = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.llm_timeout_s = _float("LLM_TIMEOUT_S", 45.0)
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            self.llm_provider = "mock"

        # MQTT (optionnel)
        self.mqtt_enabled = _bool("MQTT_ENABLED", True)
        self.mqtt_host = os.getenv("MQTT_HOST", "localhost")
        self.mqtt_port = _int("MQTT_PORT", 1883)
        self.mqtt_prefix = os.getenv("MQTT_PREFIX", "hackcure")

        # Telegram (désactivé sans jeton)
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        # Simulateur embarqué (appareils + chambres virtuelles dans le serveur)
        self.embedded_sim = _bool("EMBEDDED_SIM", True)
        self.sim_speed = _float("SIM_SPEED", 1.0)

        # n8n (orchestration des actions) — repli sur les agents locaux si indisponible
        self.n8n_enabled = _bool("N8N_ENABLED", False)
        self.n8n_base_url = os.getenv("N8N_BASE_URL", "http://localhost:5678").rstrip("/")
        self.n8n_webhook_secret = os.getenv("N8N_WEBHOOK_SECRET", "")
        self.n8n_api_key = os.getenv("N8N_API_KEY", "")
        self.platform_url = os.getenv("PLATFORM_URL", "http://localhost:8000").rstrip("/")
        self.platform_service_token = os.getenv("PLATFORM_SERVICE_TOKEN", "")

        # Agents
        self.agents_enabled = _bool("AGENTS_ENABLED", True)
        # Délais FollowUp en secondes (valeurs « simulées » courtes pour la démo)
        self.followup_recheck_s = _float("FOLLOWUP_RECHECK_S", 120.0)
        # V2 : en simulation, « Je prends en charge » fait intervenir un soignant virtuel (scénario *_resolves)
        self.auto_resolution = _bool("AUTO_RESOLUTION", True)
        self.vitals_tick_s = _float("VITALS_TICK_S", 20.0)  # période du calcul NEWS2 / tendances
        # Parcours fièvre (V2) : délais « simulés », raccourcis en démo
        self.fever_repeat_gap_s = _float("FEVER_REPEAT_GAP_S", 600.0)  # écart mini entre deux relevés ≥ 37,8 °C
        self.fever_lab_delay_s = _float("FEVER_LAB_DELAY_S", 45.0)  # arrivée des résultats biologiques simulés
        self.thermal_recheck_s = _float("THERMAL_RECHECK_S", 180.0)  # revérification après une simple hausse thermique
        self.outdoor_temp_c = _float("OUTDOOR_TEMP_C", 18.0)  # température extérieure si le simulateur ne la fournit pas
        # Plan d'administration (V2) : retard > 30 min ⇒ relance, > 60 min ⇒ médecin prévenu (raccourcis en démo)
        self.med_relaunch_s = _float("MED_RELAUNCH_S", 1800.0)
        self.med_escalate_s = _float("MED_ESCALATE_S", 3600.0)
        self.med_due_window_s = _float("MED_DUE_WINDOW_S", 900.0)  # « à faire maintenant » : de l'heure prévue − 15 min à + 30 min
        self.diagnostics_tick_s = _float("DIAGNOSTICS_TICK_S", 10.0)
        # Psychologie (V2) : période du score continu, seuil de bien-être sous lequel l'équipe est notifiée
        self.psych_tick_s = _float("PSYCH_TICK_S", 20.0)
        self.psych_threshold = int(_float("PSYCH_THRESHOLD", 50))
        self.prediction_tick_s = _float("PREDICTION_TICK_S", 10.0)
        # Ambulances (V2) : accélération du trajet simulé (démo), rayon d'arrivée, durée du transfert vers la chambre
        self.ambulance_time_scale = max(0.1, _float("AMBULANCE_TIME_SCALE", 1.0))
        self.ambulance_arrival_m = _float("AMBULANCE_ARRIVAL_M", 60.0)
        self.ambulance_install_s = _float("AMBULANCE_INSTALL_S", 20.0)
        self.escalation_critical_s = _float("ESCALATION_CRITICAL_S", 120.0)
        self.escalation_high_s = _float("ESCALATION_HIGH_S", 600.0)
        self.escalation_medium_s = _float("ESCALATION_MEDIUM_S", 1800.0)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
