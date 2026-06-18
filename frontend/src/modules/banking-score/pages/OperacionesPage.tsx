import { OperationsConsole } from "@/shared/ops/OperationsConsole";

/** Global operation console: every data operation across all sources. Per-source
 * Datos pages (Social, Comercio, …) reuse OperationsConsole with a filter. */
export function OperacionesPage() {
  return (
    <OperationsConsole
      eyebrow="Datos · operación"
      title="Consola de Operación"
      sub="Dispara, monitorea y agenda las operaciones de datos recurrentes — sin terminal."
    />
  );
}
