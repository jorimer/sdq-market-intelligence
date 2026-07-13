import { describe, it, expect } from "vitest";
import { computeChanges, initialDraft, normalizeAmount } from "./tariffBulk";
import type { CatalogSku } from "../billingApi";

const price = (amount: string) => ({
  amount, currency: "USD", effective_from: null, effective_to: null, label: null,
});

const SKUS: CatalogSku[] = [
  {
    sku: "insight:banking", kind: "insight", ref: "banking",
    label: "Insight · Banca", intervals: ["monthly", "annual"],
    prices: { monthly: price("149.00"), annual: null },
  },
  {
    sku: "deep_dive:banking", kind: "deep_dive", ref: "banking",
    label: "Deep Dive · Banca", intervals: ["once"],
    prices: { once: price("450.00") },
  },
];

describe("normalizeAmount", () => {
  it("normaliza números válidos a 2 decimales", () => {
    expect(normalizeAmount("149")).toBe("149.00");
    expect(normalizeAmount(" 1,490.5 ")).toBe("1490.50");
  });
  it("rechaza vacío, cero, negativos y basura", () => {
    expect(normalizeAmount("")).toBeNull();
    expect(normalizeAmount("0")).toBeNull();
    expect(normalizeAmount("-5")).toBeNull();
    expect(normalizeAmount("abc")).toBeNull();
  });
});

describe("initialDraft", () => {
  it("precarga cada celda con el monto vigente (o vacía)", () => {
    const d = initialDraft(SKUS);
    expect(d["insight:banking"].monthly).toBe("149.00");
    expect(d["insight:banking"].annual).toBe("");
    expect(d["deep_dive:banking"].once).toBe("450.00");
  });
});

describe("computeChanges", () => {
  it("sin ediciones no hay cambios (precargado == vigente)", () => {
    expect(computeChanges(SKUS, initialDraft(SKUS))).toEqual([]);
  });

  it("detecta un cambio de monto y un precio nuevo", () => {
    const d = initialDraft(SKUS);
    d["insight:banking"].monthly = "199";      // cambio 149 → 199
    d["insight:banking"].annual = "1990";      // precio nuevo (no había)
    const ch = computeChanges(SKUS, d);
    expect(ch).toHaveLength(2);
    expect(ch[0]).toMatchObject({ sku: "insight:banking", interval: "monthly", current: "149.00", next: "199.00" });
    expect(ch[1]).toMatchObject({ sku: "insight:banking", interval: "annual", current: null, next: "1990.00" });
  });

  it("mismo número con formato distinto NO es cambio", () => {
    const d = initialDraft(SKUS);
    d["deep_dive:banking"].once = "450";
    expect(computeChanges(SKUS, d)).toEqual([]);
  });

  it("celda vaciada o inválida no publica (no hay borrar-por-lote)", () => {
    const d = initialDraft(SKUS);
    d["deep_dive:banking"].once = "";
    d["insight:banking"].monthly = "-3";
    expect(computeChanges(SKUS, d)).toEqual([]);
  });
});
