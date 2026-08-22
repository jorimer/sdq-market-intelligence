"""REGLA ESTRUCTURAL: ningún renderizador declara su propio color de marca.

**El caso que la motivó.** La paleta estaba declarada cuatro veces —el PDF genérico
(`shared/products/render.py`), el Word (`render_docx.py`), los gráficos (`charts.py`) y el
PDF de banca (`modules/banking_score/reports/pdf_generator.py`)—. Cuando la aplicación
migró a la dirección «Claro & Vivo» (tinta `#0A1A3A`, acento `#1E6FFF`), las cuatro copias
se quedaron en `#1A365D` + `#2B6CB0` + un `signal red #E11D48`. El resultado: el cliente
veía un producto azul eléctrico en pantalla y recibía un informe en otra marca, y nadie lo
notó porque cada archivo era internamente consistente.

**Por qué un test y no una nota.** La lección escrita ya falló: `docs/REPORT_STANDARD.md`
§5 documentaba la paleta vieja y se siguió documentando después de que la app cambiara. Un
quinto renderizador nace con su propio `HexColor("#...")` y nadie se entera hasta que un
comprador compara pantalla contra PDF.

**Por qué `ast` y no `grep`.** Los comentarios tienen que poder nombrar los hex retirados
—esta misma docstring lo hace, y saber POR QUÉ se fueron es lo que evita reintroducirlos—.
Leyendo el árbol, los comentarios no existen: se inspecciona solo lo que puede terminar
pintado, que son los literales de cadena.

**La regla.** Ningún módulo de `shared/` ni de `modules/` (fuera de tests) contiene un
literal de color hexadecimal, salvo:

- `shared/brand/tokens.py`, que ES la paleta;
- los archivos exentos de abajo, cuyos colores no son de marca y tienen su motivo escrito;
- un literal marcado con `# color-propio-ok: <razón>` en su línea o en la de su sentencia.
"""
import ast
import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[3]

# SOLO `#RRGGBB`. La forma corta `#RGB` quedó fuera a propósito: no se usa en el repo y
# cazaba las referencias a PR (`#552`, `#598`), que abundan en los docstrings. Un número de
# PR de seis dígitos no existe acá, así que seis es la longitud que distingue color de cita.
_HEX = re.compile(r"#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])")
# Un hex "pelado" (sin `#`): el formato que pide el sombreado OOXML. Se exige que sean
# SEIS dígitos y que haya al menos una letra, para no confundirlo con un número.
_HEX_PELADO = re.compile(r"(?=[0-9A-Fa-f]{6}$)(?=.*[A-Fa-f])[0-9A-Fa-f]{6}")
_EXENCION = "color-propio-ok:"

_DIRECTORIOS = ("shared", "modules")
# `shared/brand/` ES la marca: define los tokens y su docstring nombra los hex retirados
# para explicar por qué se fueron, que es lo que evita que vuelvan.
_EXCLUIDOS = ("/tests/", "/test_", "/__pycache__/", "/shared/brand/")

# EXCEPCIONES DECLARADAS, archivo completo. Van acá y no como comentario disperso porque
# son del archivo entero: leerlas juntas es lo que permite auditar la lista.
# Las SUPERFICIES que imprimen. Sobre ellas la regla es más estricta (ver
# `test_las_superficies_no_construyen_color_desde_literales`): tampoco pueden armar un
# color con `RGBColor(0x..)` ni con un hex "pelado" sin almohadilla, que es como se cuela
# el color en python-docx y en el sombreado OOXML. Los dos huecos son reales: se
# descubrieron con `forensic_docx.py`, que tenía cuatro `RGBColor` y dos hex pelados y
# pasaba el test general sin despeinarse.
_SUPERFICIES = (
    "shared/products/render.py",
    "shared/products/render_docx.py",
    "shared/products/charts.py",
    "shared/billing/invoice.py",
    "modules/banking_score/reports/pdf_generator.py",
    "modules/banking_score/reports/forensic_pdf.py",
    "modules/banking_score/reports/forensic_docx.py",
    "modules/brand_intel/report.py",
)

_ARCHIVOS_EXENTOS = {
    # La escala de letras RETIRADA (`SDQ-AAA…D`) y sus colores. No se publica en ninguna
    # superficie; el archivo sobrevive como linaje del dato histórico.
    "modules/banking_score/scoring/rating_scale.py",
}


def _fuentes():
    for d in _DIRECTORIOS:
        for path in sorted((RAIZ / d).rglob("*.py")):
            rel = path.relative_to(RAIZ).as_posix()
            if any(x in f"/{rel}" for x in _EXCLUIDOS) or rel in _ARCHIVOS_EXENTOS:
                continue
            yield rel, path


def _lineas_exentas(texto: str) -> set:
    return {i for i, line in enumerate(texto.splitlines(), 1) if _EXENCION in line}


def test_ningun_renderizador_declara_su_propio_color():
    """Todo color de marca sale de `shared.brand`; nadie escribe un hex."""
    ofensas = []
    for rel, path in _fuentes():
        texto = path.read_text(encoding="utf-8")
        if "#" not in texto:
            continue
        try:
            arbol = ast.parse(texto)
        except SyntaxError:  # pragma: no cover — un archivo roto lo caza el linter
            continue
        exentas = _lineas_exentas(texto)
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
                continue
            if not _HEX.search(nodo.value):
                continue
            if nodo.lineno in exentas or (nodo.lineno - 1) in exentas:
                continue
            ofensas.append(f"{rel}:{nodo.lineno}  {nodo.value[:60]!r}")

    assert not ofensas, (
        "Estos literales declaran un color en vez de leerlo de `shared.brand`:\n  "
        + "\n  ".join(ofensas)
        + "\n\nUsá los tokens (`from shared import brand` → `brand.INK`, `brand.ACCENT`, …). "
          "Si el color NO es de marca y tiene que ser literal, declaralo con "
          "`# color-propio-ok: <razón>` en su línea."
    )


def test_las_superficies_no_construyen_color_desde_literales():
    """En lo que imprime, tampoco vale `RGBColor(0x..)` ni un hex sin almohadilla.

    El test general mira literales `#RRGGBB`, y así se le escapaban las dos formas que
    usa python-docx: el constructor por canales y el hex pelado del sombreado OOXML.
    """
    ofensas = []
    for rel in _SUPERFICIES:
        path = RAIZ / rel
        texto = path.read_text(encoding="utf-8")
        arbol = ast.parse(texto)
        exentas = _lineas_exentas(texto)
        for nodo in ast.walk(arbol):
            linea = getattr(nodo, "lineno", None)   # Module y otros nodos no la tienen
            if linea is None or linea in exentas or (linea - 1) in exentas:
                continue
            # `RGBColor(0xC8, 0x39, 0x2E)` — color por canales.
            if (isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Name) and nodo.func.id == "RGBColor"
                    and nodo.args
                    and all(isinstance(a, ast.Constant) and isinstance(a.value, int)
                            for a in nodo.args)):
                ofensas.append(f"{rel}:{linea}  RGBColor(...) con literales")
            # `"E5F3EC"` — hex pelado, el formato del sombreado OOXML.
            if (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
                    and _HEX_PELADO.fullmatch(nodo.value)):
                ofensas.append(f"{rel}:{linea}  {nodo.value!r} (hex sin almohadilla)")

    assert not ofensas, (
        "Estas superficies construyen un color desde literales:\n  "
        + "\n  ".join(ofensas)
        + "\n\nUsá los tokens de `shared.brand` (en docx, `_rgb()` / `_hex()`)."
    )


def test_los_renderizadores_importan_la_marca():
    """Toda superficie que imprime lee la paleta; si una deja de hacerlo, se sabe.

    Complementa al test de arriba: sin esto, un renderizador podría «cumplir» borrando sus
    colores y quedándose en gris por omisión.
    """
    sin_marca = [m for m in _SUPERFICIES
                 if "shared import brand" not in (RAIZ / m).read_text(encoding="utf-8")
                 and "shared.brand" not in (RAIZ / m).read_text(encoding="utf-8")]
    assert not sin_marca, f"Estos motores no leen la paleta de `shared.brand`: {sin_marca}"


def test_los_tokens_espejan_el_css_del_frontend():
    """`shared/brand/tokens.py` y `frontend/src/index.css` no pueden divergir.

    Son dos lados de la misma marca: el que se ve en pantalla y el que se imprime. La
    divergencia entre ambos es exactamente el defecto que este paquete vino a curar, así
    que se verifica en vez de confiarse al comentario que dice «espejo».
    """
    from shared.brand import tokens

    css = (RAIZ / "frontend/src/index.css").read_text(encoding="utf-8")
    raiz = css[css.index(":root {"):css.index(".dark {")]
    declarados = dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})", raiz))

    # token de Python → variable CSS. Solo los que ambos lados definen.
    pares = {
        "CANVAS": "canvas", "SURFACE": "surface", "SURFACE_2": "surface-2",
        "INK": "ink", "BODY": "body", "MUTED": "muted", "FAINT": "faint",
        "BORDER": "border", "BORDER_STRONG": "border-strong",
        "ACCENT": "accent", "ACCENT_HOVER": "accent-hover",
        "ACCENT_SOFT": "accent-soft", "ACCENT_INK": "accent-ink",
        "TEAL": "teal", "TEAL_SOFT": "teal-soft",
        "OK": "ok", "OK_SOFT": "ok-soft", "WARN": "warn", "WARN_SOFT": "warn-soft",
        "ALERT": "alert", "ALERT_SOFT": "alert-soft", "GRID": "grid",
    }
    divergen = []
    for py, var in pares.items():
        esperado = declarados.get(var)
        actual = getattr(tokens, py)
        if esperado is None:
            divergen.append(f"--{var} no está en index.css (¿se renombró?)")
        elif esperado.upper() != actual.upper():
            divergen.append(f"{py}={actual} vs --{var}:{esperado}")
    assert not divergen, (
        "La paleta de impresión y la de pantalla divergieron:\n  " + "\n  ".join(divergen))


@pytest.mark.parametrize("token,minimo", [("INK", 4.5), ("BODY", 4.5), ("ACCENT_INK", 4.5)])
def test_el_texto_contrasta_sobre_blanco(token, minimo):
    """Los tokens que se usan para TEXTO pasan WCAG AA sobre blanco.

    `ACCENT` (#1E6FFF) da 4,40:1 y queda deliberadamente fuera de esta lista: por eso
    existe `ACCENT_INK`, y por eso el acento puro solo pinta rellenos. Si alguien
    «simplifica» usando ACCENT para texto, este test no lo caza — lo caza la revisión;
    pero al menos el umbral queda escrito y verificado para los que sí son de texto.
    """
    from shared.brand import tokens

    def _canal(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    h = getattr(tokens, token).lstrip("#")
    lum = (0.2126 * _canal(int(h[0:2], 16))
           + 0.7152 * _canal(int(h[2:4], 16))
           + 0.0722 * _canal(int(h[4:6], 16)))
    ratio = 1.05 / (lum + 0.05)
    assert ratio >= minimo, f"{token} da {ratio:.2f}:1 sobre blanco; hace falta {minimo}:1"
