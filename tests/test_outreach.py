# -*- coding: utf-8 -*-
"""Tests — Outreach: campañas de outbound email (adquisición)."""
import datetime as dt

import pytest

from b2b_ai.db.db import Database
from b2b_ai.outreach.sequences import (OutreachManager, render_template,
                                       render_subject, SEQUENCE_TEMPLATES,
                                       SEQUENCE_SUBJECTS, FOLLOWUP_DAY_OFFSETS,
                                       SEQUENCE_LENGTH, default_tracking_base)
from b2b_ai.outreach.analytics import (campaign_stats, lead_score,
                                       best_send_time, subject_line_ab_test)

TENANT = 7


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "outreach.db"))


@pytest.fixture
def mgr(db):
    return OutreachManager(db=db, tenant_id=TENANT,
                           sender_email="ventas@b2b.example",
                           sender_first_name="Ana", sender_company="Likida AI Enterprise",
                           tracking_base="https://track.test.example")


LEAD_A = {"email": "luis@firma.com", "first_name": "Luis",
          "last_name": "Ramírez", "company": "Firma X",
          "role": "Socio", "industry": "Contabilidad"}
LEAD_B = {"email": "maria@otra.com", "first_name": "María",
          "company": "Otra SA", "industry": "Auditoría"}


# --------------------------------------------------------------------------- #
# Secuencia y render de plantillas
# --------------------------------------------------------------------------- #
def test_secuencia_tiene_cinco_pasos_con_plantilla_y_asunto():
    assert SEQUENCE_LENGTH == 5
    for stage in range(1, 6):
        assert SEQUENCE_TEMPLATES[stage].startswith("cold_outreach_")
        assert SEQUENCE_TEMPLATES[stage].endswith(".html")
        assert SEQUENCE_SUBJECTS[stage]
        assert stage in FOLLOWUP_DAY_OFFSETS


def test_render_template_sustituye_placeholders_y_respeta_css():
    html = "<style>.a{color:red}</style> Hola {first_name} {last_name} en {company} img={tracking_open_url}"
    out = render_template(html, {"first_name": "Luis", "company": "Firma X",
                                 "tracking_open_url": "https://t/x"})
    assert "Luis" in out and "Firma X" in out and "https://t/x" in out
    assert ".a{color:red}" in out  # llaves de CSS intactas
    # Clave ausente se deja tal cual (no rompe el render).
    assert "{last_name}" in out


def test_render_subject_plano():
    assert render_subject("Hola {first_name}", {"first_name": "Ana"}) == "Hola Ana"


def test_default_tracking_base_env(tmp_path, monkeypatch):
    monkeypatch.setenv("B2B_TRACKING_BASE", "https://track.custom.example")
    assert default_tracking_base() == "https://track.custom.example"


# --------------------------------------------------------------------------- #
# launch_campaign
# --------------------------------------------------------------------------- #
def test_launch_campaign_crea_campania_y_leads(db, mgr):
    camp = mgr.launch_campaign([LEAD_A, LEAD_B], sequence_id=1, name="Cold Q3")
    assert camp["status"] == "active"
    assert camp["sequence_id"] == 1
    assert len(camp["leads"]) == 2
    rows = db.list_outreach_campaigns(tenant_id=TENANT)
    assert len(rows) == 1 and rows[0]["name"] == "Cold Q3"
    leads = db.list_outreach_leads(campaign_id=camp["id"])
    assert {l["email"] for l in leads} == {"luis@firma.com", "maria@otra.com"}
    assert all(l["stage"] == 1 and l["status"] == "queued" for l in leads)


def test_launch_requiere_tenant_y_leads(db):
    m = OutreachManager(db=db, tenant_id=None)
    with pytest.raises(ValueError):
        m.launch_campaign([LEAD_A])
    m2 = OutreachManager(db=db, tenant_id=1)
    with pytest.raises(ValueError):
        m2.launch_campaign([])
    with pytest.raises(ValueError):
        m2.launch_campaign([{"first_name": "Sin email"}])


# --------------------------------------------------------------------------- #
# send_email
# --------------------------------------------------------------------------- #
def test_send_email_renderiza_paso_1_con_tracking(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e = mgr.send_email(lid)
    assert e["stage"] == 1
    assert e["template"] == "cold_outreach_1.html"
    assert "Firma X" in e["body"]
    assert "Luis" in e["body"]
    assert "/track/open?email_id=" in e["body"]
    assert "/track/click?email_id=" in e["body"]
    assert "{company}" not in e["body"]  # sin placeholders sin llenar
    row = db.get_outreach_email(e["id"])
    assert row["status"] == "sent"
    lead = db.get_outreach_lead(lid)
    assert lead["emails_sent"] == 1 and lead["status"] == "active"


def test_send_email_no_envia_campania_pausada(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    mgr.pause_campaign(camp["id"])
    res = mgr.send_email(lid)
    assert res["skipped"] is True and "pausada" in res["reason"]


def test_send_email_no_envia_lead_terminal(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    db.update_outreach_lead(lid, status="unsubscribed")
    res = mgr.send_email(lid)
    assert res["skipped"] is True and "status" in res["reason"]


def test_send_email_permite_plantilla_override(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e = mgr.send_email(lid, template="cold_outreach_4.html")
    assert e["template"] == "cold_outreach_4.html"
    assert e["stage"] == 4


# --------------------------------------------------------------------------- #
# Tracking
# --------------------------------------------------------------------------- #
def test_track_open_incrementa_y_marca_timestamp(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e = mgr.send_email(lid)
    mgr.track_open(lid, e["id"])
    row = db.get_outreach_email(e["id"])
    assert row["opened_count"] == 1 and row["opened_at"] is not None
    events = db.list_outreach_events(email_id=e["id"])
    assert any(ev["event_type"] == "open" for ev in events)


def test_track_click_y_unsubscribe(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e = mgr.send_email(lid)
    mgr.track_click(lid, "cta_1", email_id=e["id"])
    row = db.get_outreach_email(e["id"])
    assert row["click_count"] == 1 and row["first_clicked_at"] is not None

    mgr.track_click(lid, "unsubscribe", email_id=e["id"])
    lead = db.get_outreach_lead(lid)
    assert lead["status"] == "unsubscribed"
    # Un lead dado de baja ya no recibe más pasos.
    assert mgr.send_email(lid)["skipped"] is True


def test_track_click_sin_email_id_resuelve_ultimo(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e = mgr.send_email(lid)
    ev = mgr.track_click(lid, "cta_1")  # sin email_id
    assert ev["email_id"] == e["id"]


# --------------------------------------------------------------------------- #
# auto_followup
# --------------------------------------------------------------------------- #
def test_auto_followup_espera_dias_configurados(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e1 = mgr.send_email(lid)
    # Enviado ahora: aún no toca el paso 2 (offset 2 días).
    res = mgr.auto_followup(lid)
    assert res["skipped"] is True and "aún no toca" in res["reason"]
    # Backdatear el envío para que ya venció el offset.
    old = (dt.datetime.utcnow() - dt.timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    db.conn.execute("UPDATE outreach_emails SET sent_at=? WHERE id=?",
                    (old, e1["id"]))
    db.conn.commit()
    e2 = mgr.auto_followup(lid)
    assert e2.get("skipped") is not True
    assert e2["stage"] == 2 and e2["template"] == "cold_outreach_2.html"
    assert db.get_outreach_lead(lid)["stage"] == 2


def test_auto_followup_marca_completado_al_terminar(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    db.update_outreach_lead(lid, stage=SEQUENCE_LENGTH, status="active")
    res = mgr.auto_followup(lid)
    assert res["skipped"] is True and "completada" in res["reason"]
    assert db.get_outreach_lead(lid)["status"] == "completed"


def test_auto_followup_no_avanza_lead_que_respondio(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    db.update_outreach_lead(lid, status="replied")
    assert mgr.auto_followup(lid)["skipped"] is True


# --------------------------------------------------------------------------- #
# pause / resume
# --------------------------------------------------------------------------- #
def test_pause_y_resume_campania(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    p = mgr.pause_campaign(camp["id"])
    assert p["status"] == "paused" and p["paused_at"] is not None
    r = mgr.resume_campaign(camp["id"])
    assert r["status"] == "active"


# --------------------------------------------------------------------------- #
# analytics
# --------------------------------------------------------------------------- #
def test_campaign_stats_calculan_rates(db, mgr):
    camp = mgr.launch_campaign([LEAD_A, LEAD_B])
    la, lb = camp["leads"][0]["id"], camp["leads"][1]["id"]
    ea = mgr.send_email(la)
    eb = mgr.send_email(lb)
    mgr.track_open(la, ea["id"])
    mgr.track_click(la, "cta_1", email_id=ea["id"])
    db.update_outreach_lead(la, status="replied")
    stats = campaign_stats(camp["id"], db)
    assert stats["leads"] == 2
    assert stats["emails_sent"] == 2
    assert stats["unique_opens"] == 1
    assert stats["open_rate"] == 0.5
    assert stats["unique_clickers"] == 1
    assert stats["replies"] == 1 and stats["reply_rate"] == 0.5


def test_campaign_stats_sin_db_vacio():
    stats = campaign_stats(99, None)
    assert stats["emails_sent"] == 0 and stats["open_rate"] == 0.0


def test_lead_score_suma_senales(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e = mgr.send_email(lid)
    # Solo open -> 20
    mgr.track_open(lid, e["id"])
    assert lead_score(lid, db)["score"] == 20
    # + click -> 60
    mgr.track_click(lid, "cta_1", email_id=e["id"])
    assert lead_score(lid, db)["score"] == 60
    # + reply -> 100
    db.update_outreach_lead(lid, status="replied")
    assert lead_score(lid, db)["score"] == 100


def test_best_send_time_sin_datos_da_default():
    rec = best_send_time(TENANT, None)["recommendation"]
    assert "mañana" in rec


def test_best_send_time_observa_opens(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e = mgr.send_email(lid)
    mgr.track_open(lid, e["id"])
    rec = best_send_time(TENANT, db)
    assert rec["basis"] == "observed"
    assert rec["best_hour"] in rec["hourly"]


def test_subject_line_ab_test_solo_un_asunto(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    mgr.send_email(lid)
    res = subject_line_ab_test(camp["id"], db)
    assert res["winner"] is None and "solo un asunto" in res["note"]


def test_subject_line_ab_test_detecta_ganador(db, mgr):
    camp = mgr.launch_campaign([LEAD_A])
    lid = camp["leads"][0]["id"]
    e_ganador = mgr.send_email(lid)  # asunto por defecto, se abre
    # Forzamos un segundo correo con asunto distinto que NO se abre.
    mgr.send_email(lid, template="cold_outreach_4.html",
                   subject="Otro asunto de prueba")
    mgr.track_open(lid, e_ganador["id"])
    res = subject_line_ab_test(camp["id"], db)
    assert res["note"] == "ok"
    assert len(res["subjects"]) == 2
    # El asunto con open gana.
    winner = max(res["subjects"].items(), key=lambda kv: kv[1]["open_rate"])[0]
    assert winner == res["winner"]
    assert res["subjects"][res["winner"]]["open_rate"] > 0
