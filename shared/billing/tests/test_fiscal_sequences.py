"""Asignación de comprobantes fiscales: formato, agotamiento, vencimiento y concurrencia.

El caso que justifica el módulo es ``test_dos_asignaciones_concurrentes_no_repiten_numero``:
la versión anterior avanzaba el contador con ``row.current += 1`` sobre el valor en memoria,
bajo un ``FOR UPDATE`` que SQLite ignora en silencio. Cuando las dos sesiones ya tenían la
fila cargada, las dos emitían el MISMO número — reproducido con dos sesiones reales sobre una
base en archivo. Cuando la fila NO estaba cargada el bug no se manifestaba, y por eso el test
monta explícitamente la condición que lo dispara en vez de una benigna que pasaría igual.
"""
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Importar todos los modelos para registrar sus tablas en el metadata.
import shared.auth.models  # noqa: F401
import shared.billing.models  # noqa: F401
import shared.products.models  # noqa: F401
import shared.settings.models  # noqa: F401
from shared.billing.models import FiscalSequence
from shared.billing.fiscal.sequences import (
    FiscalSequenceError,
    allocate_next,
    list_sequences,
    sequences_needing_attention,
    try_allocate,
    upsert_sequence,
)
from shared.billing.fiscal.types import (
    FiscalTypeError,
    NCF_CONSUMO,
    NCF_CREDITO_FISCAL,
    NCF_EXPORTACIONES,
    REGIME_ECF,
    REGIME_NCF,
    format_number,
    parse_number,
)
from shared.database.base import Base


@pytest.fixture()
def engine(tmp_path):
    """Base en ARCHIVO (no :memory:) para que dos sesiones vean la misma tabla."""
    eng = create_engine(f"sqlite:///{tmp_path/'fiscal.db'}")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ── Formato ──────────────────────────────────────────────────────────

def test_ncf_es_b_mas_tipo_mas_ocho_digitos():
    assert format_number(REGIME_NCF, NCF_CONSUMO, 1) == "B0200000001"
    assert len(format_number(REGIME_NCF, NCF_CREDITO_FISCAL, 12345678)) == 11


def test_encf_es_e_mas_tipo_mas_diez_digitos():
    assert format_number(REGIME_ECF, "32", 1) == "E320000000001"
    assert len(format_number(REGIME_ECF, "31", 1)) == 13


def test_parse_number_recupera_regimen_tipo_y_correlativo():
    assert parse_number("B0200000007") == (REGIME_NCF, NCF_CONSUMO, 7)
    assert parse_number("E320000000007") == (REGIME_ECF, "32", 7)


def test_un_tipo_de_ecf_no_es_valido_bajo_ncf():
    # '31' es Crédito Fiscal ELECTRÓNICO: bajo régimen impreso no existe. Es el error que
    # convierte un número en otro documento si nadie lo valida.
    with pytest.raises(FiscalTypeError):
        format_number(REGIME_NCF, "31", 1)


# ── Asignación ───────────────────────────────────────────────────────

def test_asigna_correlativos_consecutivos(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=5)
    numeros = [allocate_next(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO)["number"]
               for _ in range(3)]
    assert numeros == ["B0200000001", "B0200000002", "B0200000003"]


def test_secuencia_agotada_no_asigna(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=1)
    allocate_next(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO)
    with pytest.raises(FiscalSequenceError):
        allocate_next(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO)


def test_secuencia_vencida_no_asigna(db):
    ayer = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_EXPORTACIONES,
                    range_from=1, range_to=100, expires_at=ayer)
    with pytest.raises(FiscalSequenceError):
        allocate_next(db, regime=REGIME_NCF, doc_type=NCF_EXPORTACIONES)


def test_try_allocate_devuelve_none_en_vez_de_lanzar(db):
    # La facturación usa esta puerta: quedarse sin números NO puede tumbar un cobro ya hecho.
    assert try_allocate(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO) is None


def test_los_regimenes_no_comparten_contador(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=10)
    upsert_sequence(db, regime=REGIME_ECF, doc_type="32", range_from=1, range_to=10)
    assert allocate_next(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO)["number"] == "B0200000001"
    assert allocate_next(db, regime=REGIME_ECF, doc_type="32")["number"] == "E320000000001"


def test_rango_fuera_del_formato_del_regimen_se_rechaza(db):
    # 8 dígitos en NCF: 100.000.000 no entra. Cargarlo emitiría números de 12 caracteres.
    with pytest.raises(FiscalSequenceError):
        upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO,
                        range_from=1, range_to=100_000_000)


# ── Concurrencia: la propiedad que IMPORTA ───────────────────────────

def test_dos_asignaciones_concurrentes_no_repiten_numero(engine):
    """Dos sesiones que YA tienen la fila cargada no pueden emitir el mismo comprobante.

    La condición importa y es la que se reproduce acá: con la fila en el identity map de cada
    sesión (cualquier lectura previa de la secuencia en el mismo request la deja ahí), el
    asignador viejo — ``row.current += 1`` sobre el valor EN MEMORIA, bajo un ``FOR UPDATE``
    que SQLite ignora en silencio — emitía ``B0200000001`` en las dos. Verificado: sin el
    compare-and-swap este test devuelve el mismo número dos veces."""
    Session = sessionmaker(bind=engine)
    setup = Session()
    upsert_sequence(setup, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=10)
    setup.close()

    a, b = Session(), Session()
    try:
        # Las dos cargan la fila (current = 1) ANTES de que ninguna escriba: es el estado
        # rancio del que partía la pérdida de actualización.
        fila_a = a.query(FiscalSequence).first()
        fila_b = b.query(FiscalSequence).first()
        assert int(fila_a.current) == int(fila_b.current) == 1

        n_a = allocate_next(a, regime=REGIME_NCF, doc_type=NCF_CONSUMO)["number"]
        n_b = allocate_next(b, regime=REGIME_NCF, doc_type=NCF_CONSUMO)["number"]
        assert n_a != n_b, "dos comprobantes fiscales con el MISMO número"
        assert sorted([n_a, n_b]) == ["B0200000001", "B0200000002"]
    finally:
        a.close()
        b.close()


def test_la_base_rechaza_dos_facturas_con_el_mismo_comprobante(db):
    """Último cerrojo: aunque un camino futuro asignara mal, el índice único impide que dos
    facturas queden persistidas con el mismo número. La propiedad que importa no es "el
    contador subió" sino "no hay dos comprobantes iguales"."""
    from decimal import Decimal

    from sqlalchemy.exc import IntegrityError

    from shared.billing.models import BillingTransaction

    def _tx(**extra):
        return BillingTransaction(
            user_id="u1", sku="deep_dive:banking", kind="order", provider="paypal",
            currency="USD", subtotal=Decimal("100"), tax_rate=Decimal("18"),
            tax_amount=Decimal("18"), total=Decimal("118"), **extra)

    db.add(_tx(invoice_number="SDQ-2026-00001", event_id="e1",
               ncf_type=NCF_CONSUMO, ncf_number="B0200000001"))
    db.commit()
    db.add(_tx(invoice_number="SDQ-2026-00002", event_id="e2",
               ncf_type=NCF_CONSUMO, ncf_number="B0200000001"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_varios_cobros_sin_comprobante_conviven(db):
    """El índice único no puede castigar la brecha declarada: muchos cobros pueden quedar
    esperando número (``ncf_number`` NULL) sin chocar entre sí."""
    from decimal import Decimal

    from shared.billing.models import BillingTransaction

    for i in range(3):
        db.add(BillingTransaction(
            user_id="u1", sku="deep_dive:banking", kind="order", provider="paypal",
            currency="USD", subtotal=Decimal("100"), tax_rate=Decimal("18"),
            tax_amount=Decimal("18"), total=Decimal("118"),
            invoice_number=f"SDQ-2026-0000{i}", event_id=f"e{i}",
            ncf_type=NCF_CONSUMO, ncf_number=None, ncf_status="sin_secuencia"))
    db.commit()
    assert db.query(BillingTransaction).count() == 3


def test_el_avance_se_revierte_con_la_transaccion(db):
    """``commit=False`` deja el correlativo en la transacción del llamador: si esta se
    revierte, el número no queda quemado."""
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=10)
    allocate_next(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, commit=False)
    db.rollback()
    assert allocate_next(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO)["number"] == "B0200000001"


# ── Aviso preventivo ─────────────────────────────────────────────────

def test_avisa_antes_de_agotarse(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=3)
    fila = list_sequences(db)[0]
    assert fila["low"] is True and fila["remaining"] == 3
    assert any(s["doc_type"] == NCF_CONSUMO for s in sequences_needing_attention(db))


def test_un_rango_holgado_no_alerta(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=5000)
    assert list_sequences(db)[0]["low"] is False
    assert sequences_needing_attention(db) == []


def test_avisa_por_vencimiento_proximo(db):
    upsert_sequence(db, regime=REGIME_NCF, doc_type=NCF_CONSUMO, range_from=1, range_to=5000,
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=10))
    assert list_sequences(db)[0]["expiring_soon"] is True
