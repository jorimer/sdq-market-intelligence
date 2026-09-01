"""El libro de crédito del sistema abierto por SECTOR ECONÓMICO y PROVINCIA.

**Por qué vive en `shared/reference/` y no en `banking_score`.** Es el cubo público
`carteras/creditos` de la Superintendencia de Bancos: un registro NACIONAL de crédito que
cubre a todas las entidades supervisadas, con 19 sectores CIIU y 33 provincias. Ningún eje es
su dueño — igual que el padrón de la DGII, que ya vive acá.

Lo mudó la fase 1 del plan de enriquecimiento sectorial
(`docs/PLAN_ENRIQUECIMIENTO_SECTORIAL.md`): once productos van a leer esta tabla, y la
alternativa —que `shared/` importe el modelo de un módulo— existe hoy en tres archivos de
todo el repo y es una excepción, no un patrón.

**Por qué NO se materializó un agregado de sistema en otra tabla**, que habría evitado el
grano de entidad: dos caminos que tienen que coincidir es exactamente el defecto que costó la
tasa de 38 entidades el 2026-08-31. Se lee de la fuente y se agrega al vuelo.

**La deuda que queda, dicha para que no se descubra sola.** `bank_id` es un FK a `banks`, que
sigue en `banking_score` y se referencia en 53 archivos. Es la primera FK de `shared/` hacia
una tabla de módulo en este repo — las demás apuntan a `users.id`, que también es de
`shared/`. El registro de entidades supervisadas de la SIB es tan nacional como este cubo y
debería acompañarlo, pero moverlo es otra tarea y no bloquea ésta.
"""
from sqlalchemy import (Column, Date, ForeignKey, Index, Numeric, String,
                        UniqueConstraint)

from shared.database.base import Base, UUIDMixin


class CarteraSectorial(UUIDMixin, Base):
    """El libro de crédito abierto por SECTOR ECONÓMICO — una fila por entidad, período y
    sector.

    Por qué existe. El cubo `carteras/creditos` de la SIB trae, en cada fila, el sector
    junto a la mora, la mora TEMPRANA de 31 a 90 días, la clasificación, la garantía y la
    provisión. Hasta ahora se recorría entero para computar un HHI y el resto se descartaba.
    Esta tabla es el único lugar donde queda el libro de TODAS las entidades abierto por
    sector: un banco tiene su propia fila del cubo y ninguna de las otras noventa y una, así
    que es lo que permite responder la pregunta que un comité de crédito no puede
    responderse solo —«mi cartera de construcción se deterioró: ¿es mi originación o es el
    sector?»— separando lo idiosincrático de lo compartido.

    `sector` es texto y NO un Enum a propósito: son las etiquetas CIIU de la SIB
    («F - CONSTRUCCIÓN»), que la fuente puede cambiar o ampliar, y en Postgres los tipos ENUM
    viven en un namespace global — recrear uno en una migración ya tumbó un deploy en este
    repo.
    """
    __tablename__ = "cartera_sectorial"

    bank_id = Column(String, ForeignKey("banks.id"), nullable=False)
    period_end = Column(Date, nullable=False)
    sector = Column(String(160), nullable=False)
    # GRANO COMPLETO: sector × provincia. Agregar hacia arriba es una suma; bajar exigiría
    # volver a descargar los 22 trimestres del cubo, así que la provincia nace con la tabla.
    # "SIN PROVINCIA" es un valor real y no un NULL: la fila existe, lo que falta es el
    # rótulo, y un NULL en una clave única se comporta distinto en cada motor.
    provincia = Column(String(80), nullable=False, server_default="SIN PROVINCIA")
    # Se COPIA de la fuente en vez de derivarse: la trae el cubo, y un mapa propio
    # provincia→región se desincroniza el día que la SIB reagrupa.
    region = Column(String(80), nullable=True)

    deuda = Column(Numeric(18, 2), nullable=True)
    vencida = Column(Numeric(18, 2), nullable=True)
    # Mora de 31 a 90 días: señal ADELANTADA. Se deteriora antes que `vencida`, y por sector
    # es lo que convierte la alerta temprana en algo que el banco no puede replicar.
    vencida_31_90 = Column(Numeric(18, 2), nullable=True)
    cartera_a = Column(Numeric(18, 2), nullable=True)
    garantia = Column(Numeric(18, 2), nullable=True)
    provision = Column(Numeric(18, 2), nullable=True)
    creditos = Column(Numeric(18, 2), nullable=True)

    # ── Medidas agregadas en #997 y ampliadas antes del backfill ──
    # Se suman TODAS en la misma pasada del cubo porque re-hacerlo cuesta ~2h30: cada campo
    # que se agregue después obliga a pagar esa espera otra vez.
    desembolso = Column(Numeric(18, 2), nullable=True)      # flujo NUEVO, no el stock
    deuda_capital = Column(Numeric(18, 2), nullable=True)
    plasticos = Column(Numeric(18, 2), nullable=True)
    # Σ(tasa × deuda) y su base: el promedio ponderado se reconstruye a cualquier nivel de
    # agregación. Un promedio simple de tasas de celdas de tamaño distinto no es la tasa de
    # nadie, y guardarlo así lo haría irrecuperable.
    # LA TASA, no el numerador crudo. `tasaPorDeuda` del cubo viene ponderado por el
    # emisor y su magnitud desbordó Numeric(22,4) incluso sin multiplicar, o sea que su
    # unidad no es la que se supuso; guardar un número que no se puede interpretar no
    # sirve. `None` cuando la tasa derivada cae fuera de la banda creíble: dice «no se
    # pudo derivar», que es distinto de un cero.
    tasa_ponderada = Column(Numeric(9, 4), nullable=True)
    deuda_con_tasa = Column(Numeric(18, 2), nullable=True)
    # `moneda` y `persona` tienen DOS valores: entran como medida y no como dimensión, que
    # cuadruplicaría las filas para decir lo mismo. El resto es nacional y jurídica.
    deuda_moneda_extranjera = Column(Numeric(18, 2), nullable=True)
    deuda_persona_fisica = Column(Numeric(18, 2), nullable=True)
    # La clasificación COMPLETA: con las cinco clases se computa migración y pérdida
    # esperada por sector; con solo la A, no.
    cartera_b = Column(Numeric(18, 2), nullable=True)
    cartera_c = Column(Numeric(18, 2), nullable=True)
    cartera_d = Column(Numeric(18, 2), nullable=True)
    cartera_e = Column(Numeric(18, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("bank_id", "period_end", "sector", "provincia",
                         name="uq_cartera_sectorial_bank_period_sector_prov"),
        Index("ix_cartera_sectorial_bank_period", "bank_id", "period_end"),
        # El barrido del sistema pregunta «quién está en este sector en este corte», que es
        # la lectura que ningún banco puede hacer por su cuenta.
        Index("ix_cartera_sectorial_sector_period", "sector", "period_end"),
        # «Qué se presta en esta provincia» — el eje geográfico del sistema, que ningún
        # banco puede ver más allá de su propio libro.
        Index("ix_cartera_sectorial_prov_period", "provincia", "period_end"),
    )
