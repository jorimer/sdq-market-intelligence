"""De la venta al comprobante: un cobro consume el NCF autorizado, la factura lo imprime, y
quedarse sin secuencia NO tumba la venta (declara la brecha).

También cubre la matriz fiscal (consumo / crédito fiscal / exportación → 02 / 01 / 16), la
asignación retroactiva y el Formato 607.
"""
import pytest
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Importar todos los modelos para registrar sus tablas en el metadata.
import shared.auth.models  # noqa: F401
import shared.billing.models  # noqa: F401
import shared.products.models  # noqa: F401
import shared.settings.models  # noqa: F401
from shared.auth.models import User
from shared.billing.fiscal.documents import (
    assign_pending_numbers,
    build_607_rows,
    identification_kind,
    list_documents,
    pending_count,
)
from shared.billing.fiscal.sequences import upsert_sequence
from shared.billing.fiscal.types import (
    NCF_CONSUMO,
    NCF_CREDITO_FISCAL,
    NCF_EXPORTACIONES,
    REGIME_NCF,
)
from shared.billing.invoice import (
    LEYENDA_COMPROBANTE_INTERNO,
    _fiscal_identity,
    render_invoice_pdf,
)
from shared.billing.models import BillingTransaction
from shared.billing.tax import compute_tax
from shared.billing.transactions import intended_doc_type, record_transaction_once
from shared.database.base import Base

_TAX_RD = {"enabled": True, "rate": "18", "label": "ITBIS",
           "home_country": "DO", "exempt_foreign": True}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _user(db, *, email="cliente@ejemplo.do", country="DO", tax_id=None):
    u = User(email=email, password_hash="x", full_name="Cliente Ejemplo",
             is_active=True, role="viewer", country=country, tax_id=tax_id)
    db.add(u)
    db.commit()
    return u


def _breakdown(country="DO"):
    return compute_tax("450.00", currency="USD", country=country, config=_TAX_RD)


def _cobrar(db, user, *, event_id="ev-1", country="DO", has_rnc=False):
    return record_transaction_once(
        db, user_id=user.id, sku="deep_dive:banking", kind="order", provider="paypal",
        provider_ref="PP-1", event_id=event_id, breakdown=_breakdown(country),
        client_has_rnc=has_rnc)


# ── Matriz fiscal: qué tipo corresponde ──────────────────────────────

@pytest.mark.parametrize("country,has_rnc,esperado", [
    ("DO", False, NCF_CONSUMO),          # consumidor final local
    ("DO", True, NCF_CREDITO_FISCAL),    # cliente de RD que aporta su RNC
    ("US", False, NCF_EXPORTACIONES),    # exterior → exportación de servicios (exento)
])
def test_matriz_fiscal_elige_el_tipo(country, has_rnc, esperado):
    bd = compute_tax("450.00", currency="USD", country=country, config=_TAX_RD)
    assert intended_doc_type(bd, regime=REGIME_NCF, client_has_rnc=has_rnc) == esperado


def test_la_matriz_traduce_al_regimen_electronico():
    """La matriz se escribe UNA vez y se traduce: 02 (NCF) ↔ 32 (e-CF). Así los dos motores
    no pueden divergir."""
    bd = _breakdown()
    assert intended_doc_type(bd, regime=REGIME_NCF) == "02"
    assert intended_doc_type(bd, regime="ecf") == "32"


# ── El cobro consume el comprobante ──────────────────────────────────

def test_un_cobro_consume_el_ncf_autorizado(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO,
                    range_from=101, range_to=200)
    user = _user(db)
    tx, created = _cobrar(db, user)
    assert created is True
    assert tx["ncf_number"] == "B0200000101"
    assert tx["ncf_status"] == "emitido"
    # El número nunca viaja solo: sale con su tipo, su etiqueta y su régimen.
    assert tx["fiscal_regime"] == REGIME_NCF
    assert tx["fiscal_doc_type"] == NCF_CONSUMO
    assert tx["fiscal_doc_label"] == "Factura de Consumo"


def test_cobros_sucesivos_consumen_correlativos_distintos(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=50)
    user = _user(db)
    a, _ = _cobrar(db, user, event_id="ev-a")
    b, _ = _cobrar(db, user, event_id="ev-b")
    assert a["ncf_number"] != b["ncf_number"]
    assert [a["ncf_number"], b["ncf_number"]] == ["B0200000001", "B0200000002"]


def test_reentregar_el_mismo_evento_no_consume_otro_comprobante(db):
    """La idempotencia tiene que cubrir la NUMERACIÓN, no solo el cobro: si el webhook y el
    retorno liquidan la misma venta, no puede quemarse un segundo NCF."""
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=50)
    user = _user(db)
    primero, created_1 = _cobrar(db, user, event_id="ev-igual")
    repetido, created_2 = _cobrar(db, user, event_id="ev-igual")
    assert (created_1, created_2) == (True, False)
    assert primero["ncf_number"] == repetido["ncf_number"] == "B0200000001"
    assert db.query(BillingTransaction).count() == 1


def test_un_cliente_con_rnc_recibe_factura_de_credito_fiscal(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CREDITO_FISCAL,
                    range_from=1, range_to=50)
    user = _user(db, tax_id="130862346")
    tx, _ = _cobrar(db, user, has_rnc=True)
    assert tx["ncf_number"].startswith("B01")
    assert tx["fiscal_doc_label"] == "Factura de Crédito Fiscal"


def test_cliente_del_exterior_recibe_comprobante_de_exportacion(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_EXPORTACIONES,
                    range_from=1, range_to=50)
    user = _user(db, email="foreign@example.com", country="US")
    tx, _ = _cobrar(db, user, country="US")
    assert tx["ncf_number"].startswith("B16")
    assert tx["tax_exempt"] is True


# ── La brecha se declara, no se rellena ──────────────────────────────

def test_sin_secuencia_el_cobro_se_registra_igual_con_la_brecha_declarada(db):
    """Quedarse sin números NO puede tumbar una venta ya cobrada por PayPal. Se registra el
    cobro, el número queda en None (no en 0, ni en un placeholder) y el estado lo dice."""
    user = _user(db)
    tx, created = _cobrar(db, user)
    assert created is True
    assert tx["ncf_number"] is None
    assert tx["ncf_status"] == "sin_secuencia"
    assert tx["fiscal_regime"] is None
    assert pending_count(db) == 1


def test_la_factura_sin_comprobante_no_se_hace_pasar_por_factura(db):
    """Sin comprobante asignado el documento NO es una factura y el renderer lo sabe:
    ``_fiscal_identity`` devuelve None, que es lo que dispara el rótulo de comprobante
    interno y la leyenda de que no vale como crédito fiscal."""
    user = _user(db)
    _cobrar(db, user)
    tx = db.query(BillingTransaction).one()
    assert _fiscal_identity(tx) is None
    assert "No válido como crédito fiscal" in LEYENDA_COMPROBANTE_INTERNO
    assert render_invoice_pdf(db, tx, user).startswith(b"%PDF")


def test_la_factura_con_ncf_lleva_numero_tipo_y_vencimiento(db):
    """Con comprobante asignado, el PDF tiene de dónde imprimir el número CON su etiqueta y
    su fecha de validez — los tres datos que exige un NCF impreso."""
    vence = datetime(2026, 12, 31)
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=50,
                    expires_at=vence)
    user = _user(db, tax_id="130862346")
    _cobrar(db, user)
    tx = db.query(BillingTransaction).one()

    identidad = _fiscal_identity(tx)
    assert identidad["regime"] == REGIME_NCF
    assert identidad["number"] == "B0200000001"
    assert identidad["doc_type"] == NCF_CONSUMO
    assert identidad["label"] == "Factura de Consumo"
    assert identidad["valid_until"] == vence
    assert render_invoice_pdf(db, tx, user).startswith(b"%PDF")


def test_el_vencimiento_queda_congelado_en_la_factura(db):
    """La factura es un registro histórico: su "válido hasta" se copia al emitir, así que
    reemplazar el rango después no reescribe comprobantes ya emitidos."""
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=50,
                    expires_at=datetime(2026, 12, 31))
    user = _user(db)
    _cobrar(db, user)
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=50,
                    current=2, expires_at=datetime(2027, 6, 30))
    tx = db.query(BillingTransaction).one()
    assert tx.ncf_valid_until == datetime(2026, 12, 31)


# ── Asignación retroactiva ───────────────────────────────────────────

def test_al_cargar_el_rango_se_numeran_los_cobros_pendientes(db):
    user = _user(db)
    _cobrar(db, user, event_id="ev-a")
    _cobrar(db, user, event_id="ev-b")
    assert pending_count(db) == 2

    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=50)
    parte = assign_pending_numbers(db)
    assert parte["assigned_count"] == 2
    assert parte["still_pending"] == 0
    numeros = sorted(d["fiscal_number"] for d in parte["assigned"])
    assert numeros == ["B0200000001", "B0200000002"]


def test_la_asignacion_retroactiva_se_detiene_sin_inventar_numeros(db):
    """Si el rango cargado no alcanza, los que sobran siguen declarados como pendientes."""
    user = _user(db)
    for i in range(3):
        _cobrar(db, user, event_id=f"ev-{i}")
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=2)
    parte = assign_pending_numbers(db)
    assert parte["assigned_count"] == 2
    assert parte["still_pending"] == 1
    assert NCF_CONSUMO in parte["blocked"]


# ── Formato 607 ──────────────────────────────────────────────────────

def test_identification_kind_no_adivina():
    assert identification_kind("130862346") == "1"        # RNC: 9 dígitos
    assert identification_kind("001-1234567-8") == "2"    # cédula: 11 dígitos
    assert identification_kind("") is None
    assert identification_kind("12345") is None           # largo raro → no se fuerza


def test_el_607_solo_reporta_comprobantes_realmente_emitidos(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=1)
    user = _user(db)
    _cobrar(db, user, event_id="ev-con")     # consume el único número
    _cobrar(db, user, event_id="ev-sin")     # ya no hay: queda pendiente

    periodo = db.query(BillingTransaction).first().created_at.strftime("%Y-%m")
    filas = build_607_rows(db, periodo)
    assert len(filas) == 1, "un cobro sin número no existe fiscalmente todavía"
    assert filas[0][2] == "B0200000001"       # columna 3: Número de Comprobante Fiscal
    assert filas[0][4] == "01"                # Tipo de Ingreso: operaciones del giro
    assert filas[0][7] == "450.00"            # Monto facturado (subtotal)
    assert filas[0][8] == "81.00"             # ITBIS facturado (18%)
    assert filas[0][18] == "531.00"           # Tarjeta débito/crédito: el total cobrado


def test_el_607_lleva_el_rnc_del_comprador_cuando_lo_hay(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CREDITO_FISCAL,
                    range_from=1, range_to=10)
    user = _user(db, tax_id="130862346")
    _cobrar(db, user, has_rnc=True)
    periodo = db.query(BillingTransaction).first().created_at.strftime("%Y-%m")
    fila = build_607_rows(db, periodo)[0]
    assert fila[0] == "130862346" and fila[1] == "1"


def test_periodo_mal_formado_se_rechaza(db):
    with pytest.raises(ValueError):
        list_documents(db, period="agosto")


# ── El listado administrativo ────────────────────────────────────────

def test_el_listado_admin_ve_todo_con_su_identidad_fiscal(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=10)
    user = _user(db)
    _cobrar(db, user)
    doc = list_documents(db)[0]
    assert doc["fiscal_number"] == "B0200000001"
    assert doc["fiscal_doc_label"] == "Factura de Consumo"
    assert doc["fiscal_regime"] == REGIME_NCF
    assert doc["client_email"] == user.email
    assert Decimal(doc["total"]) == Decimal("531.00")
