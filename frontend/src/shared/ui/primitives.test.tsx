import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// react-i18next: t devuelve el fallback (2º arg) o la clave — sin cargar i18n real.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));

import {
  StateBlock,
  BandBadge,
  Delta,
  StatTile,
  Gauge,
} from "@/shared/ui/primitives";
import type { Band } from "@/shared/lib/bands";

const BAND: Band = { label: "Sólido", tone: "accent" };

describe("StateBlock — los estados canónicos", () => {
  const kinds = [
    ["loading", "Cargando…"],
    ["empty", "Sin datos"],
    ["error", "Error al cargar"],
    ["forbidden", "Sin permiso"],
    ["soon", "En construcción"],
  ] as const;

  it.each(kinds)("renderiza el estado %s con su título", (kind, title) => {
    render(<StateBlock kind={kind} />);
    expect(screen.getByText(title)).toBeInTheDocument();
  });

  it("el estado loading tiene spinner (animate-spin)", () => {
    const { container } = render(<StateBlock kind="loading" />);
    expect(container.querySelector(".animate-spin")).not.toBeNull();
  });

  it("muestra título, mensaje y acción custom", () => {
    render(
      <StateBlock
        kind="error"
        title="Falló la carga"
        message="Reintentá en un momento"
        action={<button>Reintentar</button>}
      />,
    );
    expect(screen.getByText("Falló la carga")).toBeInTheDocument();
    expect(screen.getByText("Reintentá en un momento")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});

describe("BandBadge", () => {
  it("renderiza la etiqueta de la banda", () => {
    render(<BandBadge band={BAND} />);
    expect(screen.getByText("Sólido")).toBeInTheDocument();
  });
});

describe("Delta", () => {
  it("prefija + en positivos", () => {
    render(<Delta value={2.5} />);
    expect(screen.getByText("+2.5")).toBeInTheDocument();
  });
  it("muestra negativos sin prefijo extra", () => {
    render(<Delta value={-1.2} />);
    expect(screen.getByText("-1.2")).toBeInTheDocument();
  });
  it("muestra — cuando el valor es nulo", () => {
    render(<Delta value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("StatTile", () => {
  it("renderiza label, valor y unidad", () => {
    render(<StatTile label="Solvencia" value="16.5" unit="%" />);
    expect(screen.getByText("Solvencia")).toBeInTheDocument();
    expect(screen.getByText("16.5")).toBeInTheDocument();
    expect(screen.getByText("%")).toBeInTheDocument();
  });
});

describe("Gauge", () => {
  it("muestra el score con un decimal", () => {
    render(<Gauge score={72.34} band={BAND} />);
    expect(screen.getByText("72.3")).toBeInTheDocument();
  });
  it("muestra — cuando el score es nulo", () => {
    render(<Gauge score={null} band={BAND} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
