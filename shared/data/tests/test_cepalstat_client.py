"""CEPALSTAT — parser de participación política (lógica pura, sin red).

La respuesta trae las filas con `iso3` pero el AÑO y el SEXO como identificadores de
dimensión, así que el parser tiene que resolverlos contra `dimensions`. La planilla de
prueba reproduce esa forma, incluida la trampa que importa: las filas de hombres son el
complemento y son igual de plausibles.
"""
import pytest

from shared.data.cepalstat_client import CepalstatUnavailable, parse_serie


def _payload(filas, con_sexo=True):
    dims = [
        {"id": 208, "name": "País__ESTANDAR", "members": [{"id": 216, "name": "Argentina"}]},
        {"id": 29117, "name": "Años__ESTANDAR",
         "members": [{"id": 900, "name": "2010"}, {"id": 901, "name": "2024"},
                     {"id": 902, "name": "Total"}]},
    ]
    if con_sexo:
        dims.append({"id": 11629, "name": "Sexo",
                     "members": [{"id": 11630, "name": "Mujeres"},
                                 {"id": 11631, "name": "Hombres"}]})
    return {"body": {"dimensions": dims, "data": filas}}


def _fila(iso, anio_id, sexo_id, valor):
    return {"iso3": iso, "dim_29117": anio_id, "dim_11629": sexo_id, "value": valor}


def test_toma_solo_republica_dominicana_y_solo_mujeres():
    """Las filas de hombres son el COMPLEMENTO: 92,3 es tan plausible como 7,7 y confundirlas
    publicaría el número contrario."""
    p = _payload([
        _fila("DOM", 900, 11630, "7.7"),
        _fila("DOM", 900, 11631, "92.3"),      # hombres — no debe entrar
        _fila("ARG", 900, 11630, "6.4"),       # otro país — no debe entrar
        _fila("DOM", 901, 11630, "9.8"),
    ])
    assert parse_serie(p) == [(2010, 7.7), (2024, 9.8)]


def test_descarta_las_etiquetas_de_ano_que_no_son_un_ano():
    """El eje de años trae agregados como «Total». Estamparlos como año produciría un punto
    que no existe."""
    p = _payload([_fila("DOM", 902, 11630, "50.0"), _fila("DOM", 900, 11630, "7.7")])
    assert parse_serie(p) == [(2010, 7.7)]


def test_sin_la_dimension_de_sexo_falla_en_vez_de_devolver_el_complemento():
    """Es el guard que más importa: sin él, el parser devolvería la serie de hombres —o una
    mezcla— y nada lo advertiría, porque el nivel es plausible en los dos casos."""
    p = _payload([_fila("DOM", 900, 11630, "7.7")], con_sexo=False)
    with pytest.raises(CepalstatUnavailable, match="Mujeres"):
        parse_serie(p)


def test_sin_filas_de_RD_falla_con_motivo():
    p = _payload([_fila("ARG", 900, 11630, "6.4")])
    with pytest.raises(CepalstatUnavailable, match="DOM"):
        parse_serie(p)
