import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// react-i18next: t devuelve el fallback (2º arg) o la clave — sin cargar i18n real.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));

const getAlertSubscriptions = vi.fn();
const watchSubject = vi.fn();
const unwatch = vi.fn();
vi.mock("@/shared/api/alerts", () => ({
  getAlertSubscriptions: (...a: unknown[]) => getAlertSubscriptions(...a),
  watchSubject: (...a: unknown[]) => watchSubject(...a),
  unwatch: (...a: unknown[]) => unwatch(...a),
}));

import { VigilarButton } from "@/shared/ui/VigilarButton";

const SUB = {
  id: "s1", sector_key: "banking", sector_label: "SDQ Banking Intelligence",
  subject: "banco-a", rule_codes: null, min_severity: "media", channels: ["inapp"],
  digest: "inmediato", active: true, suspended_reason: null,
  tier_requerido: "insight", created_at: null,
};

beforeEach(() => {
  getAlertSubscriptions.mockReset();
  watchSubject.mockReset();
  unwatch.mockReset();
  getAlertSubscriptions.mockResolvedValue({ subscriptions: [], total: 0, max: 100 });
});

describe("VigilarButton", () => {
  it("arranca en «vigilar» cuando el sujeto no está en la watchlist", async () => {
    render(<VigilarButton sectorKey="banking" subject="banco-a" />);
    await waitFor(() => expect(screen.getByRole("button")).toBeEnabled());
    expect(screen.getByRole("button")).toHaveTextContent("alerts.watch");
  });

  it("reconoce el sujeto ya vigilado y NO lo confunde con otro del mismo eje", async () => {
    // El match es por (eje, sujeto): si solo mirara el eje, vigilar el Banco A pintaría
    // como vigilado al Banco B — y el cliente creería que le avisan de algo que no.
    getAlertSubscriptions.mockResolvedValue({
      subscriptions: [SUB], total: 1, max: 100,
    });
    const { unmount } = render(<VigilarButton sectorKey="banking" subject="banco-a" />);
    await waitFor(() =>
      expect(screen.getByRole("button")).toHaveTextContent("alerts.watching"));
    unmount();

    render(<VigilarButton sectorKey="banking" subject="banco-b" />);
    await waitFor(() =>
      expect(screen.getByRole("button")).toHaveTextContent("alerts.watch"));
  });

  it("sin sujeto vigila el EJE ENTERO y manda null, no cadena vacía", async () => {
    watchSubject.mockResolvedValue({ ...SUB, subject: null, tier_requerido: "pulse" });
    render(<VigilarButton sectorKey="banking" />);
    await waitFor(() => expect(screen.getByRole("button")).toBeEnabled());
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(watchSubject).toHaveBeenCalledWith("banking", null));
  });

  it("da de baja lo que ya vigila", async () => {
    getAlertSubscriptions.mockResolvedValue({ subscriptions: [SUB], total: 1, max: 100 });
    unwatch.mockResolvedValue(undefined);
    render(<VigilarButton sectorKey="banking" subject="banco-a" />);
    await waitFor(() =>
      expect(screen.getByRole("button")).toHaveTextContent("alerts.watching"));
    await userEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(unwatch).toHaveBeenCalledWith("s1"));
    expect(screen.getByRole("button")).toHaveTextContent("alerts.watch");
  });

  it("MUESTRA el motivo del 402 en vez de no hacer nada", async () => {
    // Un botón que falla en silencio es peor que uno que no está: el cliente no sabe que
    // le falta plan, cree que la plataforma se rompió.
    watchSubject.mockRejectedValue({
      response: { data: { detail: { message: "Tu plan (free) no incluye el nivel insight." } } },
    });
    render(<VigilarButton sectorKey="banking" subject="banco-a" />);
    await waitFor(() => expect(screen.getByRole("button")).toBeEnabled());
    await userEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/no incluye el nivel insight/)).toBeInTheDocument();
  });

  it("MUESTRA el motivo del 422 (detail en texto plano)", async () => {
    watchSubject.mockRejectedValue({
      response: { data: { detail: "«SDQ Macro» tiene un sujeto único: no se elige entidad." } },
    });
    render(<VigilarButton sectorKey="macro" subject="DOM" />);
    await waitFor(() => expect(screen.getByRole("button")).toBeEnabled());
    await userEvent.click(screen.getByRole("button"));
    expect(await screen.findByText(/sujeto único/)).toBeInTheDocument();
  });

  it("declara que la vigilancia está suspendida", async () => {
    getAlertSubscriptions.mockResolvedValue({
      subscriptions: [{ ...SUB, suspended_reason: "acceso_revocado" }], total: 1, max: 100,
    });
    render(<VigilarButton sectorKey="banking" subject="banco-a" />);
    expect(await screen.findByText("alerts.suspended")).toBeInTheDocument();
  });

  it("dice que todavía no suena — la honestidad del estado en la fase A", async () => {
    getAlertSubscriptions.mockResolvedValue({ subscriptions: [SUB], total: 1, max: 100 });
    render(<VigilarButton sectorKey="banking" subject="banco-a" />);
    expect(await screen.findByText("alerts.pendingEngine")).toBeInTheDocument();
  });
});
