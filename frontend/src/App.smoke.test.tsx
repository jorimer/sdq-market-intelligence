import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mockea el cliente HTTP: el smoke no debe pegarle a la red.
vi.mock("@/shared/api/client", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
}));

import "@/shared/i18n/config"; // i18n real (registra recursos ES/EN/FR)
import App from "@/App";
import { AuthProvider } from "@/shared/auth/AuthContext";

// Montar App importa TODAS las páginas (import eager en App.tsx): este smoke atrapa
// cualquier error de import/módulo que hoy produciría una "pantalla blanca", y
// verifica que la ruta pública /login renderiza el shell sin crashear.
describe("App — smoke de montaje", () => {
  beforeEach(() => localStorage.clear());

  it("monta sin crashear y renderiza /login", () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );
    // El formulario de login (ruta pública) debe estar presente.
    expect(screen.getByRole("button")).toBeInTheDocument();
    expect(document.querySelector("input")).not.toBeNull();
  });
});
