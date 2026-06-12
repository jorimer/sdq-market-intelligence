"""Tests for the BCRD diagnostic helper in the macro_monitor router."""
from modules.macro_monitor.api.router import _describe_shape


def test_describe_shape_dict_with_values():
    payload = {
        "name": "Inflación",
        "values": [
            {"period": "2025-01", "value": 4.5},
            {"period": "2025-02", "value": 4.3},
            {"period": "2025-03", "value": 4.1},
            {"period": "2025-04", "value": 3.9},
        ],
    }
    shape = _describe_shape(payload, sample=2)
    assert shape["type"] == "dict"
    assert shape["name"] == "Inflación"
    assert "values" in shape["keys"]
    v = shape["values"]
    assert v["count"] == 4
    assert v["item_keys"] == ["period", "value"]
    assert len(v["sample"]) == 2
    assert v["last"]["period"] == "2025-04"


def test_describe_shape_bare_list():
    shape = _describe_shape([1, 2, 3, 4], sample=2)
    assert shape["type"] == "list"
    assert shape["count"] == 4
    assert shape["sample"] == [1, 2]


def test_describe_shape_empty_values():
    shape = _describe_shape({"name": "x", "values": []})
    assert shape["values"]["count"] == 0
    assert "sample" not in shape["values"]
