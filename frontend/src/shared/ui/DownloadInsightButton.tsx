import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FileDown, Loader2 } from "lucide-react";
import client from "@/shared/api/client";
import type { AiInsight } from "@/shared/ui/insight-types";

interface Props {
  /** The insight to download. Hidden when absent or a static fallback (then the
   * surface shows the "unavailable" hint, with nothing real to export). */
  ai?: AiInsight | null;
  title: string;
  eyebrow?: string;
  subtitle?: string;
  meta?: string;
}

/** Downloads the given insight as a branded SDQ PDF (server-rendered, no Claude
 * call). Posts the text the client already has; respects the UI language for the
 * disclaimer via the X-Lang header (axios interceptor). */
export function DownloadInsightButton({ ai, title, eyebrow, subtitle, meta }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const text = ai && ai.model_used !== "static_fallback" ? ai.text : null;
  if (!text) return null;

  const download = async () => {
    if (busy) return;
    setBusy(true);
    let url: string | null = null;
    try {
      const res = await client.post(
        "/tools/insight-pdf",
        { title, eyebrow, subtitle, meta, text },
        { responseType: "blob" },
      );
      url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      const cd = String(res.headers?.["content-disposition"] ?? "");
      a.download = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? "sdq-insight.pdf";
      a.click();
    } catch {
      /* best-effort; the on-screen insight is unchanged */
    } finally {
      if (url) URL.revokeObjectURL(url);
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={download}
      disabled={busy}
      title={t("widgets.downloadPdf")}
      className="inline-flex items-center gap-1.5 text-xs text-accent-ink hover:underline disabled:opacity-50 disabled:no-underline"
    >
      {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
      {t("widgets.downloadPdf")}
    </button>
  );
}
