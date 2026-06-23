import { useTranslation } from "react-i18next";
import { OperationsConsole } from "@/shared/ops/OperationsConsole";

/** Global operation console: every data operation across all sources. Per-source
 * Datos pages (Social, Comercio, …) reuse OperationsConsole with a filter. */
export function OperacionesPage() {
  const { t } = useTranslation();
  return (
    <OperationsConsole
      eyebrow={t("datos.operaciones.eyebrow")}
      title={t("datos.operaciones.title")}
      sub={t("datos.operaciones.sub")}
    />
  );
}
