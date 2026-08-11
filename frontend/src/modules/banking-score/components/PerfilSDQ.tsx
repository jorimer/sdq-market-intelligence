import { Tone, toneBadgeClass } from "@/shared/lib/bands";

/**
 * Perfil SDQ — dos ejes independientes en vez de un símbolo único.
 *
 * Ejecución (qué tan bien le va) y Resiliencia (qué tan expuesta está) se muestran SIEMPRE
 * juntos y con el mismo peso visual. Jerarquizar uno sobre el otro reintroduciría por diseño
 * lo que el sistema de dos ejes existe para evitar: que un solo número resuma dos cosas
 * distintas. Un banco puede ser sólido y poco eficiente a la vez, y el lector tiene que
 * poder ver las dos cosas de un vistazo.
 */

/** Bandas de Resiliencia (heredadas del ISF/ISA) → tono semántico. */
function toneResiliencia(banda: string | null | undefined): Tone {
  switch (banda) {
    case "Sólida":
      return "ok";
    case "Adecuada":
      return "accent";
    case "En vigilancia":
      return "warn";
    case "Frágil":
      return "alert";
    default:
      return "muted";
  }
}

/** Bandas de Ejecución (§4.1: Sobresaliente/Competitiva/Rezagada/Deficiente). */
function toneEjecucion(banda: string | null | undefined): Tone {
  switch (banda) {
    case "Sobresaliente":
      return "ok";
    case "Competitiva":
      return "accent";
    case "Rezagada":
      return "warn";
    case "Deficiente":
      return "alert";
    default:
      return "muted";
  }
}

interface EjeProps {
  titulo: string;
  glosa: string;
  score: number | null | undefined;
  banda: string | null | undefined;
  tone: Tone;
  /** Posición dentro del panel comparable, cuando el universo es chico. */
  posicion?: number | null;
  universo?: number | null;
}

function Eje({ titulo, glosa, score, banda, tone, posicion, universo }: EjeProps) {
  const sinDato = score == null;
  return (
    <div className="flex-1 min-w-[180px]">
      <div className="text-xs uppercase tracking-wide text-muted">{titulo}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-bold mono">{sinDato ? "—" : score.toFixed(1)}</span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${toneBadgeClass(tone)}`}>
          {banda ?? "Sin dato"}
        </span>
      </div>
      {/* Regla de N chico (§4.2): con un universo chico la banda sola engaña —
          "Sobresaliente" entre 4 dice bastante menos que entre 42. */}
      {posicion != null && universo != null && (
        <div className="mt-0.5 text-xs text-muted">
          {posicion} de {universo} en su grupo
        </div>
      )}
      <div className="mt-1 text-xs text-muted leading-snug">{glosa}</div>
    </div>
  );
}

export interface PerfilSDQProps {
  ejecucion: number | null | undefined;
  bandaEjecucion: string | null | undefined;
  resiliencia: number | null | undefined;
  bandaResiliencia: string | null | undefined;
  posicionEjecucion?: number | null;
  posicionResiliencia?: number | null;
  universo?: number | null;
  /** Motivo por el que Ejecución no se pudo calcular (p. ej. ciclo insuficiente). */
  notaEjecucion?: string | null;
}

export function PerfilSDQ({
  ejecucion,
  bandaEjecucion,
  resiliencia,
  bandaResiliencia,
  posicionEjecucion,
  posicionResiliencia,
  universo,
  notaEjecucion,
}: PerfilSDQProps) {
  return (
    <div className="rounded-lg border border-subtle p-4">
      <div className="flex flex-wrap gap-6">
        <Eje
          titulo="Ejecución"
          glosa="Qué tan bien le va: rentabilidad y disciplina operativa."
          score={ejecucion}
          banda={bandaEjecucion}
          tone={toneEjecucion(bandaEjecucion)}
          posicion={posicionEjecucion}
          universo={universo}
        />
        <Eje
          titulo="Resiliencia"
          glosa="Qué tan expuesta está: solvencia, liquidez y calidad de activos."
          score={resiliencia}
          banda={bandaResiliencia}
          tone={toneResiliencia(bandaResiliencia)}
          posicion={posicionResiliencia}
          universo={universo}
        />
      </div>
      {/* Un hueco declarado, no un cero disfrazado. */}
      {ejecucion == null && notaEjecucion && (
        <p className="mt-3 text-xs text-muted">{notaEjecucion}</p>
      )}
      <p className="mt-3 text-xs text-muted">
        Perfil SDQ no es una calificación crediticia. Los dos ejes son independientes y no se
        combinan en un solo símbolo.
      </p>
    </div>
  );
}


export interface PerfilCompactoProps {
  ejecucion: number | null | undefined;
  bandaEjecucion: string | null | undefined;
  resiliencia: number | null | undefined;
  bandaResiliencia: string | null | undefined;
  size?: "sm" | "md";
}

/**
 * Los dos ejes en una línea, para listas y tarjetas donde no cabe el bloque completo.
 *
 * Reemplaza a `RatingBadge`, que mostraba UN símbolo. Mantiene la regla del bloque grande:
 * los dos ejes con el mismo peso visual, nunca uno solo — un badge que muestre únicamente
 * Ejecución sería el símbolo único otra vez, con otro nombre.
 */
export function PerfilCompacto({
  ejecucion, bandaEjecucion, resiliencia, bandaResiliencia, size = "md",
}: PerfilCompactoProps) {
  const t = size === "sm" ? "text-[10px]" : "text-xs";
  const n = size === "sm" ? "text-xs" : "text-sm";
  const par = (
    etiqueta: string, score: number | null | undefined,
    banda: string | null | undefined, tone: Tone,
  ) => (
    <span className="inline-flex items-baseline gap-1">
      <span className={`${t} uppercase tracking-wide text-muted`}>{etiqueta}</span>
      <span className={`${n} font-semibold mono`}>{score == null ? "—" : score.toFixed(0)}</span>
      <span className={`px-1.5 py-0.5 rounded-full ${t} font-semibold ${toneBadgeClass(tone)}`}>
        {banda ?? "sin dato"}
      </span>
    </span>
  );
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      {par("Ejec", ejecucion, bandaEjecucion, toneEjecucion(bandaEjecucion))}
      {par("Resil", resiliencia, bandaResiliencia, toneResiliencia(bandaResiliencia))}
    </div>
  );
}
