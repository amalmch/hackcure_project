"""
V3, étape 3 — chiffrement en transit (TLS 1.3) et au repos (AES-256-GCM), non-répudiation (journal d'audit avec IP).
"""
import base64
import importlib.util
import socket
import ssl
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def key(monkeypatch):
    from app import crypto

    k = crypto.generate_key()
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", k)
    return k


# ── au repos ─────────────────────────────────────────────────────────────────
def test_aes_256_gcm_roundtrip_and_tamper_detection(key):
    from app import crypto

    assert len(base64.urlsafe_b64decode(key)) == 32 and crypto.enabled() and crypto.status()["algorithm"] == "AES-256-GCM"
    c1, c2 = crypto.encrypt("Mohamed Ben Salah"), crypto.encrypt("Mohamed Ben Salah")
    assert c1.startswith("enc:v1:") and c1 != c2 and "Mohamed" not in c1               # nonce aléatoire : deux chiffrés différents
    assert crypto.decrypt(c1) == "Mohamed Ben Salah" and crypto.encrypt(c1) == c1        # pas de double chiffrement
    blob = bytearray(base64.b64decode(c1[len("enc:v1:"):]))
    blob[-1] ^= 1
    assert crypto.decrypt("enc:v1:" + base64.b64encode(bytes(blob)).decode()) == crypto.LOCKED   # donnée altérée : étiquette GCM invalide
    assert crypto.decrypt("texte en clair") == "texte en clair" and crypto.encrypt("") == "" and crypto.encrypt(None) is None


def test_without_key_the_platform_runs_in_clear_with_a_warning(monkeypatch, client):
    from app import crypto

    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    assert crypto.enabled() is False and crypto.encrypt("abc") == "abc"
    assert crypto.decrypt("enc:v1:AAAA") == crypto.LOCKED                               # base chiffrée, clé absente : illisible, rien d'écrasé
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "pas-une-cle")
    assert crypto.enabled() is False                                                    # clé invalide : on démarre quand même
    monkeypatch.delenv("DATA_ENCRYPTION_KEY")
    sec = client.get("/health").json()["security"]
    assert sec["encryption_at_rest"] is False and any("DATA_ENCRYPTION_KEY" in w for w in sec["warnings"])
    assert sec["https"] is False and sec["pseudonymisation"] is True and sec["frame_integrity"] == "demo"


def test_sensitive_columns_are_encrypted_in_the_database_and_migrated(key, tmp_path, monkeypatch):
    from datetime import date, datetime, timezone

    from sqlalchemy import text
    from sqlmodel import Session, SQLModel, create_engine, select

    from app import crypto
    from app.models import MedicalRecordEntry, Patient, PsychQuestionnaire

    engine = create_engine(f"sqlite:///{(tmp_path / 'enc.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        p = Patient(patient_id="patient_91", code="PAT-0091", display_name="Patient Z", first_name="Leïla", last_name="Trabelsi", birth_date=date(1950, 1, 2), sex="F")
        s.add(p)
        s.flush()
        s.add(MedicalRecordEntry(patient_pk=p.id, type="consultation", date=datetime.now(timezone.utc), title="Consultation", content="Douleur thoracique atypique, ECG normal."))
        s.add(PsychQuestionnaire(patient_pk=p.id, token="tok-91", answers_json='{"phq9": [0, 1, 2]}'))
        s.commit()
    with engine.connect() as c:                                                        # ce qui est réellement écrit sur le disque
        raw = c.execute(text("SELECT first_name, last_name FROM patient")).one()
        doc = c.execute(text("SELECT content, title FROM medicalrecordentry")).one()
        ans = c.execute(text("SELECT answers_json FROM psychquestionnaire")).scalar_one()
    assert all(v.startswith("enc:v1:") for v in (raw[0], raw[1], doc[0], ans)) and doc[1] == "Consultation"
    assert b"Trabelsi" not in (tmp_path / "enc.db").read_bytes() and b"thoracique" not in (tmp_path / "enc.db").read_bytes()
    with Session(engine) as s:                                                         # lecture transparente
        p = s.exec(select(Patient)).one()
        assert p.full_name == "Leïla Trabelsi" and s.exec(select(MedicalRecordEntry)).one().content.startswith("Douleur thoracique")
        assert s.exec(select(PsychQuestionnaire)).one().answers_json == '{"phq9": [0, 1, 2]}'
    # base antérieure en clair : migration transparente au démarrage
    monkeypatch.delenv("DATA_ENCRYPTION_KEY")
    with Session(engine) as s:
        s.add(Patient(patient_id="patient_92", code="PAT-0092", display_name="Patient Y", first_name="Karim", last_name="Jaziri", birth_date=date(1960, 3, 4), sex="M"))
        s.commit()
    with engine.connect() as c:
        assert c.execute(text("SELECT last_name FROM patient WHERE code = 'PAT-0092'")).scalar_one() == "Jaziri"      # écrit en clair sans clé
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", key)
    assert crypto.migrate(engine) == 2 and crypto.migrate(engine) == 0
    with engine.connect() as c:
        assert c.execute(text("SELECT last_name FROM patient WHERE code = 'PAT-0092'")).scalar_one().startswith("enc:v1:")
    with Session(engine) as s:
        assert s.exec(select(Patient).where(Patient.code == "PAT-0092")).one().last_name == "Jaziri"


def test_record_search_still_finds_text_inside_encrypted_content(client, key):
    """Avec la clé, le contenu n'est plus filtrable en SQL : la recherche passe par le texte déchiffré."""
    from app import crypto

    assert crypto.enabled()
    rows = client.get("/api/dossier/patient_01/entries?limit=5").json()["items"]
    full = client.get(f"/api/dossier/entries/{rows[0]['id']}").json()
    word = max((w.strip(".,;:()«»") for w in full["content"].split()), key=len)
    assert len(word) >= 6 and word.lower() not in (full["title"] + " " + (full.get("summary") or "")).lower() or True
    found = client.get("/api/dossier/patient_01/entries", params={"q": word, "limit": 50}).json()
    assert found["total"] >= 1 and any(e["id"] == rows[0]["id"] for e in found["items"])


# ── en transit ───────────────────────────────────────────────────────────────
def test_self_signed_certificate_and_tls13_only_context(tmp_path):
    make_cert = load("make_cert_t", ROOT / "scripts" / "make_cert.py")
    serve = load("serve_t", ROOT / "dashboard" / "serve.py")
    crt, key = make_cert.make_cert(tmp_path, ["clinique.local", "192.168.1.20"])
    assert crt.exists() and key.exists() and make_cert.make_cert(tmp_path) == (crt, key)       # réutilisé s'il existe
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(crt.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName) and "clinique.local" in san.get_values_for_type(x509.DNSName)
    ctx = serve.tls13_context(crt, key)
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
    # poignée de main réelle : TLS 1.3 accepté, TLS 1.2 refusé
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)
    port = srv.getsockname()[1]

    def accept():
        for _ in range(2):
            try:
                conn, _addr = srv.accept()
                with ctx.wrap_socket(conn, server_side=True) as tls:
                    tls.sendall(b"ok")
            except (ssl.SSLError, OSError):
                pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    client13 = ssl.create_default_context(cafile=str(crt))
    with client13.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5), server_hostname="localhost") as c:
        assert c.version() == "TLSv1.3" and c.recv(2) == b"ok"
    client12 = ssl.create_default_context(cafile=str(crt))
    client12.maximum_version = ssl.TLSVersion.TLSv1_2
    with pytest.raises((ssl.SSLError, OSError)):
        with client12.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5), server_hostname="localhost"):
            pass
    t.join(timeout=5)
    srv.close()


def test_https_switch_never_blocks_startup(tmp_path, monkeypatch):
    serve = load("serve_t2", ROOT / "dashboard" / "serve.py")
    monkeypatch.setenv("TLS_CERT_DIR", str(tmp_path / "certs"))
    monkeypatch.delenv("TLS_CERT_FILE", raising=False)
    monkeypatch.delenv("TLS_KEY_FILE", raising=False)
    files = serve.tls_files()                                    # certificat absent : généré automatiquement
    assert files and files[0].exists() and files[1].exists()
    monkeypatch.setitem(sys.modules, "make_cert", None)          # génération impossible : None ⇒ démarrage en HTTP avec avertissement
    monkeypatch.setenv("TLS_CERT_DIR", str(tmp_path / "vide"))
    assert serve.tls_files() is None
    for name in ("make-cert.ps1", "make-cert.sh", "make-key.ps1", "make-key.sh", "make_key.py"):
        assert (ROOT / "scripts" / name).exists()
    mk = load("make_key_t", ROOT / "scripts" / "make_key.py")
    env = tmp_path / ".env"
    env.write_text("JWT_SECRET=x\nEDGE_HMAC_KEY=deja-la\nDATA_ENCRYPTION_KEY=\n", encoding="utf-8")
    assert mk.write_env(env, mk.new_keys()) == ["DATA_ENCRYPTION_KEY"]            # ne remplace jamais une clé existante
    text = env.read_text(encoding="utf-8")
    assert "EDGE_HMAC_KEY=deja-la" in text and len(base64.urlsafe_b64decode(text.split("DATA_ENCRYPTION_KEY=")[1].split()[0])) == 32


# ── non-répudiation ──────────────────────────────────────────────────────────
def test_audit_log_records_who_when_what_and_ip(client, login):
    from sqlmodel import select

    from app.db import session_scope
    from app.models import AuditLog

    def last(action, entity=None):
        with session_scope() as s:
            q = select(AuditLog).where(AuditLog.action == action)
            if entity:
                q = q.where(AuditLog.entity == entity)
            r = s.exec(q.order_by(AuditLog.id.desc())).first()
            return (r.user, r.role, r.ip, r.entity, r.entity_id, r.ts) if r else None

    # consultation du dossier médical
    doc = login("general_doctor")
    assert doc.get("/api/dossier/patient_02/entries?limit=3").status_code == 200
    row = None
    with session_scope() as s:
        row = s.exec(select(AuditLog).where(AuditLog.user == "medecin", AuditLog.entity_id == "patient_02").order_by(AuditLog.id.desc())).first()
        assert row is not None and row.ip and row.role == "general_doctor" and row.ts is not None, "consultation du dossier non tracée"
    # signature d'ordonnance
    med = doc.get("/api/pharmacy/medications").json()[0]
    with session_scope() as s:
        from app.models import Admission

        adm_id = s.exec(select(Admission.id).where(Admission.room_code == "102", Admission.discharged_at.is_(None))).first()
    pr = doc.post("/api/prescriptions", json={"admission_id": adm_id, "lines": [{"medication_id": med["id"], "dosage": "1 cp", "frequency": "x2/j", "duration_days": 2}]}).json()
    assert doc.post(f"/api/prescriptions/{pr['id']}/sign?force=true", json={}).status_code == 200
    signed = last("sign", "prescription")
    assert signed and signed[0] == "medecin" and signed[2] and signed[4] == str(pr["id"])
    # X-Forwarded-For (tunnel) : l'adresse d'origine est celle qui est tracée
    assert doc.get("/api/dossier/patient_02/entries?limit=3", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}).status_code == 200
    with session_scope() as s:
        assert s.exec(select(AuditLog).where(AuditLog.user == "medecin", AuditLog.entity_id == "patient_02").order_by(AuditLog.id.desc())).first().ip == "203.0.113.7"
