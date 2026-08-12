/**
 * Las dos series que llegan aparte del libro del proveedor: la venta del operador y la
 * matriz histórica del tracker.
 *
 * Ambas entraban por script, y una capacidad que solo un desarrollador puede ejecutar no
 * es una capacidad del producto: cada actualización del expediente quedaba atada a una
 * persona. Acá se suben, y lo que la lectura descartó se MUESTRA — una ingesta silenciosa
 * parece completa, y así entraron cuatro columnas del tablero como celdas vacías sin que
 * nada fallara.
 */
import { useRef, useState } from "react";
import { AlertTriangle, Table2, Upload } from "lucide-react";
import { Card, CardHead, Chip } from "@/shared/ui/primitives";
import {
  uploadSales,
  uploadTrackerHistory,
  type SalesIngestReport,
  type SeriesUploadResult,
} from "../api";

interface Props {
  slug: string;
  /** Cargar una serie cambia el informe: la página recarga lo que depende de ella. */
  onLoaded: () => void;
}

type Kind = "ventas" | "historico";

const COPY: Record<Kind, { title: string; hint: string; sheet: string }> = {
  ventas: {
    title: "Tablero de ventas del operador",
    hint: "Jornada por local y día. Reenviar la misma entrega corrige las jornadas, "
        + "no las duplica.",
    sheet: "Requiere la hoja de detalle «Base de Datos», no un agregado ya calculado.",
  },
  historico: {
    title: "Matriz histórica del proveedor",
    hint: "Olas anteriores en formato ancho. Solo agrega lo que falta: nunca sustituye "
        + "una observación que ya está.",
    sheet: "Requiere la hoja «KPIs».",
  },
};

function esInformeDeVentas(x: unknown): x is SalesIngestReport {
  return !!x && typeof x === "object" && "filas_leidas" in x;
}

export function SeriesPanel({ slug, onLoaded }: Props) {
  const [busy, setBusy] = useState<Kind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ kind: Kind; data: SeriesUploadResult } | null>(
    null,
  );
  const refs = { ventas: useRef<HTMLInputElement>(null), historico: useRef<HTMLInputElement>(null) };

  async function subir(kind: Kind, file: File) {
    setBusy(kind);
    setError(null);
    setResult(null);
    try {
      const data = kind === "ventas"
        ? await uploadSales(slug, file)
        : await uploadTrackerHistory(slug, file);
      setResult({ kind, data });
      onLoaded();
    } catch (e: unknown) {
      // El servidor devuelve el motivo REAL del rechazo (qué hoja falta, qué hojas hay).
      // Reemplazarlo por «error al subir» es quitarle al usuario lo único que le permite
      // corregir el archivo por su cuenta.
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setError(detail || "No se pudo cargar la serie.");
    } finally {
      setBusy(null);
    }
  }

  const lectura = result && esInformeDeVentas(result.data.lectura)
    ? result.data.lectura
    : null;

  return (
    <Card>
      <CardHead
        icon={Table2}
        title="Series complementarias"
        subtitle="La venta del operador y el histórico del proveedor"
      />
      <div className="grid gap-3 sm:grid-cols-2">
        {(["ventas", "historico"] as Kind[]).map((kind) => (
          <div key={kind} className="rounded-lg border border-line p-3">
            <p className="text-sm font-medium">{COPY[kind].title}</p>
            <p className="mt-1 text-xs text-muted">{COPY[kind].hint}</p>
            <p className="mt-1 text-xs text-muted">{COPY[kind].sheet}</p>
            <button
              className="btn btn-ghost mt-3 text-sm"
              disabled={busy !== null}
              onClick={() => refs[kind].current?.click()}
            >
              <Upload size={15} />
              {busy === kind ? "Cargando…" : "Subir .xlsx"}
            </button>
            <input
              ref={refs[kind]}
              type="file"
              accept=".xlsx,.xlsm"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void subir(kind, f);
                e.target.value = "";      // permite reintentar el MISMO archivo
              }}
            />
          </div>
        ))}
      </div>

      {error && (
        <p className="mt-3 flex items-start gap-2 text-sm text-alert">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </p>
      )}

      {result && (
        <div className="mt-3 space-y-2 text-sm">
          <p className="font-medium">
            {result.kind === "ventas" ? "Tablero cargado" : "Matriz cargada"}
          </p>
          {lectura && (
            <>
              <div className="flex flex-wrap gap-1.5 tabular-nums">
                <Chip tone="ok">{lectura.filas_leidas} jornadas leídas</Chip>
                <Chip tone="muted">{lectura.locales} locales</Chip>
                {lectura.desde && lectura.hasta && (
                  <Chip tone="muted">{lectura.desde} → {lectura.hasta}</Chip>
                )}
                {lectura.filas_descartadas > 0 && (
                  <Chip tone="warn">{lectura.filas_descartadas} descartadas</Chip>
                )}
              </div>
              {/* Lo descartado y lo no mapeado van A LA VISTA, no en un log del servidor:
                  es la diferencia entre una carga incompleta y una que parece completa. */}
              {Object.keys(lectura.motivos_descarte).length > 0 && (
                <ul className="ml-4 list-disc text-xs text-muted tabular-nums">
                  {Object.entries(lectura.motivos_descarte).map(([motivo, n]) => (
                    <li key={motivo}>{motivo}: {n}</li>
                  ))}
                </ul>
              )}
              {/* Solo lo NO RECONOCIDO es una alarma. El tablero real trae 27 columnas
                  derivadas —proyecciones, porcentajes, el cheque promedio que la
                  plataforma recomputa—: avisarlas junto a las demás sepultaría el único
                  caso que importa, que es una columna de datos quedándose afuera. */}
              {lectura.columnas_sin_mapear.length > 0 && (
                <p className="text-xs text-warn">
                  Columnas que parecían un dato y quedaron fuera:{" "}
                  {lectura.columnas_sin_mapear.join(", ")}. Revisá si el rótulo cambió en
                  esta entrega.
                </p>
              )}
              {Object.keys(lectura.columnas_ignoradas ?? {}).length > 0 && (
                <details className="text-xs text-muted">
                  <summary className="cursor-pointer">
                    {Object.keys(lectura.columnas_ignoradas).length} columnas ignoradas
                    por diseño
                  </summary>
                  <ul className="ml-4 mt-1 list-disc">
                    {Object.entries(lectura.columnas_ignoradas).map(([col, motivo]) => (
                      <li key={col}>{col} — {motivo}</li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
          {!lectura && (
            <pre className="overflow-x-auto rounded bg-surface-2 p-2 text-xs">
              {JSON.stringify(result.data.lectura, null, 2)}
            </pre>
          )}
        </div>
      )}
    </Card>
  );
}
