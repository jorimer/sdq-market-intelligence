"""Tests del Cerebro — `build_system` arma las secciones correctas y la orientación
por audiencia cae al default ante una clave inválida."""
from shared.narrative.cerebro import (
    AUDIENCE_FRAMES,
    AXIS_DOCTRINE,
    BARRA_DE_INSIGHT,
    CEREBRO_IDENTITY,
    DEFAULT_AUDIENCE,
    DEPTH_DIRECTIVE,
    EPISTEMIC_STANDARD,
    build_system,
    resolve_audience,
)


def test_default_audience_banking_is_comite_credito():
    assert DEFAULT_AUDIENCE["banking"] == "comite_credito"
    # the four pilot audiences are present and distinct
    assert set(AUDIENCE_FRAMES["banking"]) == {
        "comite_credito", "entidad", "inversionista", "supervisor"}
    assert len(set(AUDIENCE_FRAMES["banking"].values())) == 4


def test_build_system_includes_nucleus_and_axis():
    sys = build_system("banking", "comite_credito", "standard")
    # núcleo siempre presente
    assert CEREBRO_IDENTITY in sys
    assert EPISTEMIC_STANDARD in sys
    assert BARRA_DE_INSIGHT in sys
    # doctrina del eje
    assert AXIS_DOCTRINE["banking"] in sys
    # frame de la audiencia pedida
    assert AUDIENCE_FRAMES["banking"]["comite_credito"] in sys


def test_build_system_section_order():
    sys = build_system("banking", "supervisor", "standard")
    # identidad → doctrina → estándar → frame → barra
    order = [
        sys.index(CEREBRO_IDENTITY),
        sys.index(AXIS_DOCTRINE["banking"]),
        sys.index(EPISTEMIC_STANDARD),
        sys.index(AUDIENCE_FRAMES["banking"]["supervisor"]),
        sys.index(BARRA_DE_INSIGHT),
    ]
    assert order == sorted(order)


def test_audience_orients_frame():
    for aud in ("comite_credito", "entidad", "inversionista", "supervisor"):
        sys = build_system("banking", aud, "standard")
        assert AUDIENCE_FRAMES["banking"][aud] in sys
        # no fuga de otro frame
        for other in AUDIENCE_FRAMES["banking"]:
            if other != aud:
                assert AUDIENCE_FRAMES["banking"][other] not in sys


def test_unknown_or_none_audience_falls_back_to_default():
    default_frame = AUDIENCE_FRAMES["banking"]["comite_credito"]
    assert default_frame in build_system("banking", None, "standard")
    assert default_frame in build_system("banking", "inexistente", "standard")
    assert resolve_audience("banking", "inexistente") == "comite_credito"
    assert resolve_audience("banking", None) == "comite_credito"
    assert resolve_audience("banking", "supervisor") == "supervisor"


def test_detailed_mode_adds_depth_directive():
    assert DEPTH_DIRECTIVE in build_system("banking", "comite_credito", "detailed")
    assert DEPTH_DIRECTIVE not in build_system("banking", "comite_credito", "standard")


def test_deep_mode_adds_depth_directive_too():
    # deep is a superset of detailed at the system level (internal-reasoning directive);
    # the length override (DEEP_DIRECTIVE) lives in the task message, not the system.
    assert DEPTH_DIRECTIVE in build_system("banking", "comite_credito", "deep")


def test_axis_without_frames_skips_frame_section():
    # an axis present in doctrine but with no audience frames must not crash.
    AXIS_DOCTRINE["__test_axis__"] = "doctrina de prueba"
    try:
        sys = build_system("__test_axis__", "whatever", "standard")
        assert "doctrina de prueba" in sys and BARRA_DE_INSIGHT in sys
        assert resolve_audience("__test_axis__", "whatever") is None
    finally:
        del AXIS_DOCTRINE["__test_axis__"]
