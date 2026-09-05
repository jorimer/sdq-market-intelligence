"""REGLA ESTRUCTURAL: una licencia declarada tiene que estar registrada — con quién la leyó.

**El caso que la motivó, que apareció dos veces el mismo día (2026-08-22).**

  · **UIP / Parline** declaraba «Unión Interparlamentaria (Parline) — uso público con
    cita». La licencia real es CC BY-NC-SA 4.0: la descripción omitía las DOS cláusulas
    que restringen. El indicador 2.43 de la END se alimenta de ahí y viaja en informes que
    se entregan en base comercial — o sea que la descripción podía sostener una decisión
    de publicación que la licencia no permite.
  · **OWID / EM-DAT** declaraba «CC-BY-4.0 (Our World in Data; EM-DAT/CRED)»: la licencia
    del REDISTRIBUIDOR con el nombre del PRODUCTOR pegado al lado. EM-DAT es de uso no
    comercial y el uso comercial exige un acuerdo aparte con CRED/UCLouvain.

Dos instancias de la misma forma, en módulos distintos, y ninguna la había contrastado
nadie contra la página de términos del emisor. La doctrina del repo para eso no es
corregir las dos y escribir la lección: es leer el código y exigir la regla.

**Y no es una regla de estilo.** La cadena es una ENTRADA DE MÁQUINA:
``shared.data_api.manifest.license_restricts_redistribution`` decide si un activo se puede
reexportar buscando marcas (``nc-``, ``-sa``, ``odbl``, «no comercial») en este mismo texto.
Una restricción escrita en prosa amable es una restricción que el detector no ve, y el
activo sale publicable sin que nadie lo haya decidido.

**Qué exige, y qué NO.** No exige que la licencia esté verificada — eso sería exigir abrir
treinta páginas de términos hoy. Exige que TODA cadena declarada exista en
``shared.data.licenses.LICENCIAS`` con lo que se sabe de ella: la URL de los términos y la
fecha en que alguien los leyó, o el reconocimiento explícito de que no se leyeron. La deuda
queda LISTADA —``deuda_de_verificacion()``— en vez de disolverse en una prosa que suena bien.
Y no puede crecer: una fuente nueva entra verificada o el ratchet la rechaza.

**Qué queda afuera del glob, a propósito.** Los archivos de test: sus cadenas son fixtures
—``license="lic"``, ``license="por confirmar"``— y no gobiernan ninguna ingesta. Todo lo
demás de ``shared/``, ``modules/`` y ``app/`` entra: la constante de módulo, el atributo de
``SourceClient``, el ``license=`` escrito al vuelo dentro de un ``Lineage(...)``, y los
valores de cualquier dict cuyo nombre hable de licencias. Ese último caso ya no tiene
ejemplos —``modules/social_dev/service.py`` pasó a importar las cadenas del conector en vez
de copiarlas— y la regla se queda igual: una copia es donde la corrección del conector se
pierde en silencio.
"""
import ast
import pathlib
from typing import Iterator, List, Tuple

import pytest

from shared.data.licenses import LICENCIAS, deuda_de_verificacion

RAIZ = pathlib.Path(__file__).resolve().parents[3]
PAQUETES = ("shared", "modules", "app")

#: Los nombres bajo los que se declara una licencia: constante de módulo, atributo de
#: `SourceClient`, o argumento `license=` de un `Lineage`/`CanonicalSeries`.
_NOMBRES = {"LICENSE", "_LICENSE", "LICENCIA", "license"}

#: El registro mismo: sus claves SON las cadenas declaradas, y contarlas como
#: declaraciones haría que el registro se justificara solo.
_EXCLUIDOS = {pathlib.Path("shared/data/licenses.py")}


def _literales(nodo: ast.AST) -> List[str]:
    """Las cadenas que un valor de licencia puede tomar. Sin barrer el subárbol entero.

    Un barrido con ``ast.walk`` traería la condición de un ternario (``src == "WDI"``) o el
    nombre del atributo de un ``getattr`` como si fueran licencias. Se desenvuelven solo las
    formas que producen un valor: la constante, el ternario y el ``or`` de respaldo.
    """
    if isinstance(nodo, ast.Constant):
        return [nodo.value] if isinstance(nodo.value, str) else []
    if isinstance(nodo, ast.IfExp):
        return _literales(nodo.body) + _literales(nodo.orelse)
    if isinstance(nodo, ast.BoolOp):
        return [s for v in nodo.values for s in _literales(v)]
    return []


def _declaraciones() -> Iterator[Tuple[str, str]]:
    """``(cadena declarada, 'archivo:línea')`` por cada licencia escrita en el código."""
    for paquete in PAQUETES:
        for path in sorted((RAIZ / paquete).rglob("*.py")):
            rel = path.relative_to(RAIZ)
            if "tests" in rel.parts or rel.name.startswith("test_") or rel in _EXCLUIDOS:
                continue
            try:
                arbol = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):      # pragma: no cover - defensivo
                continue
            for n in ast.walk(arbol):
                if isinstance(n, (ast.Assign, ast.AnnAssign)):
                    destinos = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for d in destinos:
                        nombre = (d.id if isinstance(d, ast.Name)
                                  else d.attr if isinstance(d, ast.Attribute) else None)
                        if nombre in _NOMBRES and n.value is not None:
                            for s in _literales(n.value):
                                yield s, f"{rel}:{n.lineno}"
                        # Un dict de licencias por fuente: cada VALOR es una declaración,
                        # y además una copia — es la forma en que una corrección en el
                        # conector no llega al descriptor que se sirve.
                        if (isinstance(d, ast.Name) and "LICENS" in d.id.upper()
                                and isinstance(n.value, ast.Dict)):
                            for v in n.value.values:
                                for s in _literales(v):
                                    yield s, f"{rel}:{n.lineno} ({d.id})"
                if isinstance(n, ast.Call):
                    for kw in n.keywords:
                        if kw.arg in _NOMBRES:
                            for s in _literales(kw.value):
                                yield s, f"{rel}:{kw.value.lineno}"


_DECLARADAS = sorted(set(_declaraciones()))

#: Cuántas licencias quedan sin contrastar contra la página del emisor. Es un TECHO, no una
#: meta: baja cuando alguien lee unos términos y los registra, y el test no deja que suba.
#: Una fuente nueva entra verificada — que es barato en el momento en que se la incorpora, y
#: caro después.
#:
#: 30 al abrir el registro (2026-08-22) → 26 al día siguiente. Se corrigieron CEPALSTAT y
#: Comtrade (dos instancias más del mismo defecto), se confirmó el Banco Mundial como
#: estaba, y la UIT salió de la deuda por una vía que no estaba prevista: una respuesta
#: ESCRITA del emisor que ya estaba en el buzón. De 7 fuentes resueltas, 4 estaban
#: subdeclaradas y 1 SOBRE-declarada. Después el lote de datos.gob.do: seis cadenas más que
#: no nombraban ninguna cláusula, todas ODbL. La deuda NO baja con SISALRIL aunque se
#: promoviera: salió de la cadena que compartía con el SIS a una entrada propia, y la del
#: SIS sigue esperando que alguien lea los términos de su canal. El resto de la deuda no es
#: «probablemente está bien».
#: +1 el 2026-08-23: DIGEPRES entra con su licencia SIN verificar y eso sube la deuda a
#: proposito. El informe se publica por mandato del articulo 59 de la Ley 423-06 —lo dice el
#: propio documento— y su portal no declara terminos de reutilizacion. Publicacion obligatoria
#: no es reutilizacion libre, y registrar la fuente como verificada por ser oficial habria
#: sido exactamente la sobre-declaracion que esta regla persigue.
DEUDA_AL_2026_08_23 = 24


def test_el_detector_encuentra_las_declaraciones():
    """Sin esto, renombrar la constante volvería decorativa la regla y nadie lo notaría."""
    archivos = {donde.split(":")[0] for _, donde in _DECLARADAS}
    assert len(_DECLARADAS) >= 35, f"el detector se volvió decorativo: {_DECLARADAS}"
    assert len(archivos) >= 25, f"el detector dejó de ver módulos: {sorted(archivos)}"


@pytest.mark.parametrize("cadena,donde", _DECLARADAS,
                         ids=[d for _, d in _DECLARADAS])
def test_toda_licencia_declarada_esta_en_el_registro(cadena, donde):
    assert cadena in LICENCIAS, (
        f"{donde} declara una licencia que no está en `shared.data.licenses.LICENCIAS`:\n"
        f"    {cadena!r}\n"
        f"Escribir una licencia no obliga a haberla leído, y así entraron dos que decían "
        f"menos de lo que la licencia real restringe (Parline y EM-DAT). Registrala con "
        f"la URL de sus términos y la fecha en que la leíste — o con `verificado_el=None` "
        f"y el motivo, que es honesto y queda en la lista de deuda.\n"
        f"Y si la licencia RESTRINGE, que el texto NOMBRE la cláusula (NC · SA · ODbL): "
        f"`shared.data_api.manifest.license_restricts_redistribution` la busca ahí, y no "
        f"lee prosa."
    )


def test_el_registro_no_tiene_entradas_muertas():
    """Una entrada que ya nadie declara envejece mintiendo: dice que algo se verificó."""
    vivas = {c for c, _ in _DECLARADAS}
    muertas = sorted(set(LICENCIAS) - vivas)
    assert not muertas, (
        f"el registro tiene entradas que ningún código declara: {muertas}. "
        f"Si la cadena cambió, actualizá la clave; si la fuente se fue, borrá la entrada.")


@pytest.mark.parametrize("cadena", sorted(t for t, lic in LICENCIAS.items() if lic.verificada))
def test_una_licencia_verificada_dice_contra_que_se_verifico(cadena):
    """«Verificada» sin evidencia es la misma prosa que el registro vino a reemplazar."""
    lic = LICENCIAS[cadena]
    assert len(lic.nota) > 40, f"{cadena!r}: verificada el {lic.verificado_el} y sin decir qué se leyó"


@pytest.mark.parametrize(
    "cadena", sorted(t for t, lic in LICENCIAS.items() if lic.atribucion))
def test_la_atribucion_exigida_nombra_al_emisor(cadena):
    """Un texto de atribución que no nombra a nadie no atribuye.

    El campo existe porque hay licencias que CONDICIONAN el uso a citar la fuente — la de
    la UIT es un permiso comercial concedido sobre esa condición. El texto viaja al
    narrador tal cual, así que tiene que servir impreso.
    """
    texto = LICENCIAS[cadena].atribucion
    assert texto.lower().startswith("fuente:") and len(texto) > 30, texto


# Subido de 23 a 24 el 2026-09-04, a propósito y con motivo: SECMCA (cuadros EMFA) entra
# sin términos que leer. Se recorrió su sitio buscando aviso legal, términos, condiciones,
# privacidad y copyright y NO publica ninguno — la ausencia está verificada, lo que falta
# es el permiso. Un organismo regional no queda cubierto por la doctrina de emisores
# públicos dominicanos, así que la alternativa honesta era declarar la deuda o no traer el
# dato. Se pide la licencia por escrito antes de una distribución masiva.
def test_la_deuda_de_verificacion_no_crece():
    deuda = deuda_de_verificacion()
    assert len(deuda) <= DEUDA_AL_2026_08_23, (
        f"hay {len(deuda)} licencias sin contrastar y el techo es {DEUDA_AL_2026_08_23}. "
        f"Una fuente nueva entra con sus términos leídos: es barato ahora y caro el día "
        f"que alguien decida publicar sobre ella.\nSin verificar: {sorted(deuda)}")
    # El techo NO falla cuando la deuda baja. Ese es exactamente el comportamiento de
    # `mypy-baseline` que ya costó una corrida en rojo por un refactor que MEJORÓ el
    # código: un gate que castiga resolver deuda enseña a no resolverla. Bajar el número
    # queda como cortesía para el siguiente, no como condición de merge.
