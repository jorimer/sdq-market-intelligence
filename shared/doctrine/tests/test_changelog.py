"""El registro de cambios de metodología tiene que ser AUDITABLE, no notas de release.

Cada regla de escritura del YAML se verifica acá. Sin esto, el archivo degrada a prosa
suelta en tres entradas y deja de servir para responderle a un cliente por qué cambió su cifra.
"""
import re
from datetime import date

import pytest

from shared.doctrine.changelog import (
    CAMPOS_REQUERIDOS, atribuir, cambios, cargar, resumen_publicable,
)

_SECTORES_VALIDOS = {"banking", "insurance", "pension"}


def _entradas():
    return cargar().get("cambios") or []


def test_hay_registro():
    assert cargar().get("version")
    assert _entradas(), "el registro está vacío: no protege nada"


@pytest.mark.parametrize("c", _entradas(), ids=lambda c: c["id"])
class TestCadaEntrada:
    def test_trae_todos_los_campos_auditables(self, c):
        faltan = [k for k in CAMPOS_REQUERIDOS if not c.get(k)]
        assert not faltan, f"{c.get('id')}: faltan {faltan}"

    def test_el_pr_es_un_numero(self, c):
        """Sin PR el cambio no se puede contrastar contra el código."""
        assert isinstance(c["pr"], int) and c["pr"] > 0

    def test_la_fecha_es_iso(self, c):
        f = c["fecha_efectiva"]
        assert isinstance(f, date) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f))

    def test_los_sectores_son_claves_de_producto(self, c):
        """`insurance`, no `insurance_intel`: el registro habla el idioma del catálogo."""
        assert set(c["sectores"]) <= _SECTORES_VALIDOS, c["sectores"]

    def test_el_id_empieza_por_su_fecha(self, c):
        assert c["id"].startswith(str(c["fecha_efectiva"])), (
            "el id ordena el registro; tiene que empezar por la fecha efectiva")

    def test_las_cifras_de_impacto_van_etiquetadas(self, c):
        """Una cifra de panel suelta se vuelve mentira en la siguiente recalibración: solo
        se admite bajo `medido_al_publicar`, que la fecha explícitamente."""
        imp = c.get("impacto")
        if imp is None:
            return
        assert set(imp) <= {"medido_al_publicar"}, (
            f"{c['id']}: el impacto solo puede declararse como `medido_al_publicar`")

    def test_no_hay_cifras_sueltas_en_que_cambio(self, c):
        """`que_cambio` describe la REGLA. Los porcentajes de umbral son parte de la regla;
        un conteo de entidades es un RESULTADO y va en impacto."""
        assert not re.search(r"\b\d+\s+(aseguradoras|entidades|bancos|AFP)\b",
                             c["que_cambio"]), (
            f"{c['id']}: `que_cambio` trae un conteo de entidades — eso es resultado, "
            "va en `impacto.medido_al_publicar`")


def test_los_ids_son_unicos():
    ids = [c["id"] for c in _entradas()]
    assert len(ids) == len(set(ids))


def test_una_correccion_apunta_a_una_entrada_real():
    ids = {c["id"] for c in _entradas()}
    for c in _entradas():
        if c.get("corrige"):
            assert c["corrige"] in ids, f"{c['id']} corrige un id inexistente"


class TestConsulta:
    def test_filtra_por_sector(self):
        assert all("insurance" in c["sectores"] for c in cambios("insurance"))
        assert cambios("sector_inexistente") == []

    def test_devuelve_del_mas_reciente_al_mas_antiguo(self):
        fechas = [str(c["fecha_efectiva"]) for c in cambios()]
        assert fechas == sorted(fechas, reverse=True)

    def test_acota_por_ventana(self):
        """La consulta que responde «¿qué cambió entre el informe de junio y este?»."""
        ent = cambios("insurance", desde=date(2026, 8, 11))
        assert ent and all(str(c["fecha_efectiva"]) >= "2026-08-11" for c in ent)

    def test_atribuir_necesita_los_dos_cortes(self):
        """Sin corte previo no hay con qué comparar: no se atribuye nada."""
        assert atribuir("insurance", "2026-08-31") == []
        assert atribuir("insurance", None, "2026-07-31") == []

    def test_atribuir_toma_el_intervalo_correcto(self):
        ids = [c["id"] for c in atribuir("insurance", "2026-08-31", "2026-07-31")]
        assert "2026-08-12-solo-se-ordena-lo-comparable" in ids
        # Un cambio ANTERIOR al corte previo ya estaba vigente: no explica este movimiento.
        assert "2026-08-05-perfil-sdq" in ids  # cae dentro de la ventana de agosto
        assert atribuir("insurance", "2026-07-31", "2026-06-30") == []


class TestPayloadPublicable:
    def test_cada_impacto_viaja_fechado(self):
        r = resumen_publicable("insurance")
        assert r["cambios"]
        for f in r["cambios"]:
            assert "impacto_medido_al_publicar" in f
        assert "no una" in r["nota"] and "panel actual" in r["nota"]

    def test_no_filtra_campos_internos(self):
        permitidas = {"id", "fecha_efectiva", "sectores", "titulo", "que_cambio", "por_que",
                      "impacto_medido_al_publicar", "pr", "corrige"}
        for f in resumen_publicable()["cambios"]:
            assert set(f) == permitidas
