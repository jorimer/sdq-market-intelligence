import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import client from "@/shared/api/client";
import { PageHead, Card, BandBadge, StateBlock, LoadingGrid } from "@/shared/ui/primitives";
import { Band, bandFor, riskBandFor } from "@/shared/lib/bands";
import { fmtNum } from "@/shared/lib/format";

import { scoreCountry } from "@/modules/macro-political-risk/api";
import { SAMPLE_REGIONAL } from "@/modules/macro-political-risk/data";
import { scoreTrade } from "@/modules/trade-intel/api";
import { SAMPLE_FLOWS } from "@/modules/trade-intel/data";
import { getExposure } from "@/modules/esg-climate/api";
import { SAMPLE_SECTORS as ESG_SECTORS } from "@/modules/esg-climate/data";
import { computeIndex } from "@/modules/social-dev/api";
import { SAMPLE_REGIONS } from "@/modules/social-dev/data";
import { SAMPLE_SECTORS as IAI_SECTORS } from "@/modules/sector-intel/data";

interface Tile {
  to: string;
  eyebrow: string;
  title: string;
  value: string;
  band: Band | null;
  note?: string;
}

function esgBand(score: number): Band {
  if (score >= 70) return { label: "Exposición baja", tone: "ok" };
  if (score >= 40) return { label: "Exposición moderada", tone: "warn" };
  return { label: "Exposición alta", tone: "alert" };
}

export function OverviewPage() {
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
        // Sectorial (IAI turismo)
        client.post("/sector-intel/iai", { sector_code: "turismo", dataset: IAI_SECTORS }),
        // Social
        computeIndex("2025", SAMPLE_REGIONS),
        // Comercio
        scoreTrade(SAMPLE_FLOWS),
        // ESG
        getExposure("turismo", ESG_SECTORS),
        // Macro
        client.get<{ count: number }>("/macro-monitor/indicators"),
      ]);

      const t: Tile[] = [];

      const fin = results[0];
      if (fin.status === "fulfilled") {
        const [, ranks] = fin.value;
        const rs = ranks.data.rankings ?? [];
        const avg = rs.length ? rs.reduce((s, r) => s + r.overall_score, 0) / rs.length : null;
        t.push({ to: "/banking-score", eyebrow: "SIB", title: "Financiero", value: fmtNum(avg, 1), band: bandFor(avg ?? undefined), note: `${rs.length} entidades` });
      }

      const irmp = results[1];
      if (irmp.status === "fulfilled")
        t.push({ to: "/macro-political-risk", eyebrow: "WGI", title: "Regulatorio & político", value: fmtNum(irmp.value.irmp_score, 1), band: riskBandFor(irmp.value.irmp_score), note: "IRMP · RD" });

      const sec = results[2];
      if (sec.status === "fulfilled")
        t.push({ to: "/sector-intel", eyebrow: "ONE", title: "Sectorial", value: fmtNum(sec.value.data.iai_score, 1), band: bandFor(sec.value.data.iai_score), note: "IAI · Turismo" });

      const soc = results[3];
      if (soc.status === "fulfilled")
        t.push({ to: "/social-dev", eyebrow: "ONE", title: "Social & desarrollo", value: fmtNum(soc.value.distribution.mean, 1), band: bandFor(soc.value.distribution.mean ?? undefined), note: "IDM · promedio" });

      const tr = results[4];
      if (tr.status === "fulfilled")
        t.push({ to: "/trade-intel", eyebrow: "BCRD", title: "Comercio exterior", value: fmtNum(tr.value.resilience_score, 1), band: bandFor(tr.value.resilience_score ?? undefined), note: "Resiliencia" });

      const esg = results[5];
      if (esg.status === "fulfilled")
        t.push({ to: "/esg-climate", eyebrow: "TCFD", title: "ESG & clima", value: fmtNum(esg.value.esg_score, 1), band: esgBand(esg.value.esg_score), note: "Turismo" });

      const mac = results[6];
      if (mac.status === "fulfilled")
        t.push({ to: "/macro-monitor", eyebrow: "BCRD", title: "Macroeconómico", value: String(mac.value.data.count ?? 0), band: null, note: "series monitoreadas" });

      setTiles(t);
      setStatus(t.length ? "ready" : "error");
    })();
  }, []);

  const head = (
    <PageHead
      eyebrow="Plataforma"
      title="Resumen ejecutivo"
      sub="Lectura consolidada de los 7 ejes de inteligencia. Datos ilustrativos por eje; abre cada uno para el detalle explicable."
    />
  );

  if (status === "loading") return <div>{head}<LoadingGrid /></div>;
  if (status === "error")
    return <div>{head}<StateBlock kind="error" message="No se pudo consolidar la vista. Verifica el backend." /></div>;

  return (
    <div>
      {head}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {tiles.map((tile) => (
          <Link key={tile.to} to={tile.to} className="block">
            <Card className="h-full hover:border-linestrong transition">
              <div className="mono text-[10px] uppercase tracking-[0.16em] text-accent">{tile.eyebrow}</div>
              <div className="flex items-baseline justify-between gap-2 mt-1">
                <h3 className="font-display text-[15px] font-bold text-ink truncate">{tile.title}</h3>
                <ArrowRight size={15} className="text-faint shrink-0" />
              </div>
              <div className="flex items-baseline gap-2 mt-4">
                <span className="font-display text-3xl font-extrabold text-ink mono">{tile.value}</span>
                {tile.note && <span className="text-xs text-muted">{tile.note}</span>}
              </div>
              {tile.band && <div className="mt-3"><BandBadge band={tile.band} /></div>}
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
