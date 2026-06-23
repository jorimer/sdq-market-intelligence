import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { ArrowRight } from "lucide-react";
import client from "@/shared/api/client";
import { PageHead, Card, BandBadge, StateBlock, LoadingGrid } from "@/shared/ui/primitives";
import { Band, bandFor, riskBandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";

import { scoreCountry } from "@/modules/macro-political-risk/api";
import { SAMPLE_REGIONAL } from "@/modules/macro-political-risk/data";
import { getTradeScore } from "@/modules/trade-intel/api";
import { getIndicators as getEsgIndicators } from "@/modules/esg-climate/api";

type BandKind = "std" | "risk" | "esg" | "none";

interface Tile {
  to: string;
  eyebrow: string;            // source code (proper noun) — no translation
  titleKey: string;          // i18n key for the axis title
  value: string;
  score: number | null;      // raw score → band computed at render (i18n-reactive)
  bandKind: BandKind;
  noteKey?: string;
  noteParams?: Record<string, string | number>;
}

/** IRC band (higher = more resilient) — reuses the ESG axis band labels. */
function esgBand(score: number, t: TFunction): Band {
  if (score >= 60) return { label: t("esg.band.high"), tone: "ok" };
  if (score >= 40) return { label: t("esg.band.moderate"), tone: "warn" };
  return { label: t("esg.band.low"), tone: "alert" };
}

function tileBand(tile: Tile, t: TFunction): Band | null {
  if (tile.bandKind === "none" || tile.score == null) return null;
  if (tile.bandKind === "risk") return riskBandFor(tile.score, t);
  if (tile.bandKind === "esg") return esgBand(tile.score, t);
  return bandFor(tile.score, t);
}

export function OverviewPage() {
  const { t } = useTranslation();
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");

  useEffect(() => {
    (async () => {
      const results = await Promise.allSettled([
        // Financiero
        Promise.all([
          client.get("/banking-score/stats"),
          client.get<{ rankings: { overall_score: number }[] }>("/banking-score/rankings"),
        ]),
        // Regulatorio (IRMP)
        scoreCountry("DO", SAMPLE_REGIONAL),
        // Sectorial (IAI turismo) — persisted snapshot (real data, single-source)
        client.get<{ has_score: boolean; iai_score?: number }>("/sector-intel/turismo/latest"),
        // Social
        // Social (IDM) — persisted snapshot (real data, single-source)
        client.get<{ distribution: { mean: number | null } }>("/social-dev/indicators"),
        // Comercio (resiliencia) — snapshot persistido real (DGA/Aduanas)
        getTradeScore(),
        // ESG — scores persistidos (vacío hasta tener fuente sectorial real)
        getEsgIndicators(),
        // Macro
        client.get<{ count: number }>("/macro-monitor/indicators"),
      ]);

      const tl: Tile[] = [];

      const fin = results[0];
      if (fin.status === "fulfilled") {
        const [, ranks] = fin.value;
        const rs = ranks.data.rankings ?? [];
        const avg = rs.length ? rs.reduce((s, r) => s + r.overall_score, 0) / rs.length : null;
        tl.push({ to: "/banking-score", eyebrow: "SIB", titleKey: "platform.overview.axisFinanciero", value: fmtNum(avg, 1), score: avg, bandKind: "std", noteKey: "platform.overview.noteEntities", noteParams: { count: rs.length } });
      }

      const irmp = results[1];
      if (irmp.status === "fulfilled")
        tl.push({ to: "/macro-political-risk", eyebrow: "WGI", titleKey: "platform.overview.axisRegulatorio", value: fmtNum(irmp.value.irmp_score, 1), score: irmp.value.irmp_score, bandKind: "risk", noteKey: "platform.overview.noteRegulatorio" });

      const sec = results[2];
      if (sec.status === "fulfilled" && sec.value.data.has_score)
        tl.push({ to: "/sector-intel", eyebrow: "BCRD", titleKey: "platform.overview.axisSectorial", value: fmtNum(sec.value.data.iai_score, 1), score: sec.value.data.iai_score ?? null, bandKind: "std", noteKey: "platform.overview.noteSectorial" });

      const soc = results[3];
      if (soc.status === "fulfilled" && soc.value.data.distribution?.mean != null)
        tl.push({ to: "/social-dev", eyebrow: "ONE", titleKey: "platform.overview.axisSocial", value: fmtNum(soc.value.data.distribution.mean, 1), score: soc.value.data.distribution.mean, bandKind: "std", noteKey: "platform.overview.noteSocial" });

      const tr = results[4];
      if (tr.status === "fulfilled" && tr.value.has_score)
        tl.push({ to: "/trade-intel", eyebrow: "DGA", titleKey: "platform.overview.axisComercio", value: fmtNum(tr.value.resilience_score, 1), score: tr.value.resilience_score ?? null, bandKind: "std", noteKey: "platform.overview.noteComercio", noteParams: { period: tr.value.period ?? "" } });

      const esg = results[5];
      if (esg.status === "fulfilled" && esg.value.count > 0) {
        // National IRC for the product focus (RD), with the panel as context.
        const dr = esg.value.indicators.find((c) => c.entity_key === "DOM")
          ?? esg.value.indicators[0];
        tl.push({ to: "/esg-climate", eyebrow: "ND-GAIN", titleKey: "platform.overview.axisEsg", value: fmtNum(dr.esg_score, 1), score: dr.esg_score, bandKind: "esg", noteKey: "platform.overview.noteEsg", noteParams: { country: dr.country_name } });
      }

      const mac = results[6];
      if (mac.status === "fulfilled")
        tl.push({ to: "/macro-monitor", eyebrow: "BCRD", titleKey: "platform.overview.axisMacro", value: String(mac.value.data.count ?? 0), score: null, bandKind: "none", noteKey: "platform.overview.noteMacro" });

      setTiles(tl);
      setStatus(tl.length ? "ready" : "error");
    })();
  }, []);

  const head = (
    <PageHead
      eyebrow={t("platform.overview.eyebrow")}
      title={t("platform.overview.title")}
      sub={t("platform.overview.sub")}
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return <div>{head}<StateBlock kind="error" message={t("platform.overview.error")} /></div>;

  return (
    <div>
      {head}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {tiles.map((tile) => {
          const band = tileBand(tile, t);
          return (
            <Link key={tile.to} to={tile.to} className="block">
              <Card className="h-full hover:border-linestrong transition">
                <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent">{tile.eyebrow}</div>
                <div className="flex items-baseline justify-between gap-2 mt-1">
                  <h3 className="font-display text-[15px] font-bold text-ink truncate">{t(tile.titleKey)}</h3>
                  <ArrowRight size={15} className="text-faint shrink-0" />
                </div>
                <div className="flex items-baseline gap-2 mt-4">
                  <span className="font-display text-3xl font-extrabold text-ink mono">{tile.value}</span>
                  {tile.noteKey && <span className="text-xs text-muted">{t(tile.noteKey, tile.noteParams)}</span>}
                </div>
                {band && <div className="mt-3"><BandBadge band={band} /></div>}
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
