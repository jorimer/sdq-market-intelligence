"""Shared Power BI "publish to web" anonymous data-API plumbing.

Several Dominican public dashboards (TSS *Cotizaciones*, DGA *Comercio Exterior*,
SIS/InDataRD solvencia) expose their data only through Power BI's *publish to web*
feature. There is no documented API; the browser talks to an internal ``querydata``
endpoint that returns a compressed **DSR** (DataShapeResult). This module isolates
the three fragile, source-agnostic pieces so each connector stays thin:

  * :func:`resolve_api_host` — from the public ``view?r=<token>`` page, find the
    report's data cluster (``wabi-*-redirect`` → ``wabi-*-api``).
  * :func:`fetch_model_id` — ``conceptualschema`` → the model id ``querydata`` needs.
  * :func:`decode_dsr` — reconstruct the row matrix from the DSR (value dicts +
    the ``C``/``R``/``Ø`` per-row deltas). Pure of network → unit-testable.

Everything fails **closed**: any structural surprise raises :class:`PowerBIError`,
never fabricated data. This is an undocumented internal API — fragile by nature —
so connectors that use it always keep a committed fixture as the offline path.
"""
import base64
import json
import logging
import re
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger("sdq.data.powerbi")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


class PowerBIError(RuntimeError):
    """A Power BI publish-to-web report was unreachable or structurally changed."""


def browser_headers() -> Dict[str, str]:
    """Baseline browser-like headers (shared by the view page + data API)."""
    return dict(_HEADERS)


def decode_token(view_token: str) -> Dict[str, object]:
    """Decode a ``view?r=<token>`` payload → ``{k: resourceKey, t: tenant, c: cluster}``."""
    raw = base64.b64decode(view_token + "=" * (-len(view_token) % 4))
    return json.loads(raw)


def resource_key(view_token: str) -> str:
    """The resource key ``k`` embedded in a view token."""
    return str(decode_token(view_token)["k"])


def api_headers(res_key: str) -> Dict[str, str]:
    """Headers the anonymous data API expects, carrying the resource key."""
    return {
        **_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "X-PowerBI-ResourceKey": res_key,
        "Content-Type": "application/json;charset=UTF-8",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "Origin": "https://app.powerbi.com",
        "Referer": "https://app.powerbi.com/",
    }


def resolve_api_host(view_url: str) -> str:  # pragma: no cover - network I/O
    """Resolve the report's data cluster from its public view page, fail-closed.

    The view HTML embeds the ``wabi-*-redirect`` cluster; the data host is the same
    cluster with ``-redirect`` swapped for ``-api`` (the ``-redirect`` host 403s on
    the data endpoints).
    """
    import httpx

    r = httpx.get(view_url, timeout=30, follow_redirects=True, headers=_HEADERS)
    r.raise_for_status()
    m = re.search(r"https://(wabi-[a-z0-9-]+-redirect)\.analysis\.windows\.net", r.text)
    if not m:
        raise PowerBIError("no se pudo resolver el cluster del reporte Power BI")
    host = m.group(1).replace("-redirect", "-api")
    return f"https://{host}.analysis.windows.net"


def fetch_model_id(client, api: str, res_key: str) -> int:  # pragma: no cover - network I/O
    """POST ``conceptualschema`` and return the model id ``querydata`` requires."""
    resp = client.post(
        f"{api}/public/reports/conceptualschema",
        headers=api_headers(res_key),
        json={"version": "1.0.0", "queryApiVersion": 2, "resourceKey": res_key},
    )
    resp.raise_for_status()
    schemas = resp.json().get("schemas", [])
    if not schemas or "modelId" not in schemas[0]:
        raise PowerBIError("conceptualschema sin modelId — el reporte cambió")
    return schemas[0]["modelId"]


def _dsr_ds(response: dict) -> dict:
    """Pull the ``DS`` block from a querydata response, surfacing odata errors."""
    try:
        dsr = response["results"][0]["result"]["data"]["dsr"]
    except (KeyError, IndexError, TypeError) as e:
        raise PowerBIError(f"DSR inesperado de Power BI: {str(response)[:200]}") from e
    if "DS" not in dsr:
        # Power BI returns an odata error (e.g. a bad measure reference) under
        # DataShapes instead of DS — surface it explicitly, fail closed.
        try:
            msg = dsr["DataShapes"][0]["odata.error"]["message"]["value"]
        except (KeyError, IndexError, TypeError):
            msg = str(dsr)[:200]
        raise PowerBIError(f"Power BI rechazó la consulta: {msg}")
    return dsr["DS"][0]


def decode_dsr_rows(response: dict, *, min_cols: int = 1) -> List[List[object]]:
    """Decode a querydata DSR into a list of fully-resolved row value-lists.

    The DSR packs a matrix with per-column value dictionaries (``ValueDicts``) and a
    row list (``DM0``) where each row carries only the columns that changed: ``C``
    holds present values (a dict index for dimension columns, a literal for a
    measure), ``R`` is a bitmask of columns reused from the previous row, ``Ø`` a
    bitmask of nulls. Dimension columns (those with a ``DN`` value-dict name in the
    first row's ``S`` descriptor) are resolved to their string labels; measure
    columns keep their literal value. Pure of network — unit-testable.
    """
    ds = _dsr_ds(response)
    dicts = ds.get("ValueDicts", {})
    rows = ds.get("PH", [{}])[0].get("DM0", [])
    if not rows:
        return []
    # column → value dict name (D0/D1/…) from the first row's select descriptor;
    # a column with no ``DN`` is a measure (literal value, no dict).
    col_dict: Dict[int, Optional[str]] = {}
    for i, s in enumerate(rows[0].get("S", [])):
        col_dict[i] = s.get("DN")
    ncols = len(col_dict)
    if ncols < min_cols:
        raise PowerBIError(
            f"DSR sin descriptor de columnas (S) suficiente — el reporte cambió "
            f"(cols={ncols}, mínimo={min_cols})"
        )
    out: List[List[object]] = []
    prev: List[object] = [None] * ncols
    for r in rows:
        c = r.get("C", [])
        reuse = r.get("R", 0)
        nulls = r.get("Ø", 0)
        vals: List[object] = []
        ci = 0
        for col in range(ncols):
            if reuse & (1 << col):
                vals.append(prev[col])
            elif nulls & (1 << col):
                vals.append(None)
            else:
                vals.append(c[ci] if ci < len(c) else None)
                ci += 1
        prev = vals[:]
        resolved: List[object] = []
        for col in range(ncols):
            v = vals[col]
            dn = col_dict.get(col)
            if dn and isinstance(v, int) and dn in dicts and 0 <= v < len(dicts[dn]):
                resolved.append(dicts[dn][v])
            else:
                resolved.append(v)
        out.append(resolved)
    return out
