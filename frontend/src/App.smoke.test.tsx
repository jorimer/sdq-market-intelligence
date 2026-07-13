import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mockea el cliente HTTP: el smoke no debe pegarle a la red. /auth/me rechaza
// (sesión por cookie ausente → anónimo); el resto resuelve vacío.
vi.mock("@/shared/api/client", () => ({
  default: {
    get: vi.fn((url: string) =>
      url.includes("/auth/me")
        ? Promise.reject(Object.assign(new Error("401"), { response: { status: 401 } }))
        : Promise.resolve({ data: {} })),
    post: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

import "@/shared/i18n/config"; // i18n real (registra recursos ES/EN/FR)
import App from "@/App";
import { AuthProvider } from "@/shared/auth/AuthContext";

// Las páginas ahora cargan con React.lazy (code-splitting); solo LoginPage queda
// eager. El smoke verifica: (a) /login renderiza síncrono sin crashear, y (b) una
// ruta LAZY resuelve su chunk y monta (atrapa errores de import/módulo que
// producirían "pantalla blanca" o un Suspense que nunca resuelve).
describe("App — smoke de montaje", () => {
  beforeEach(() => localStorage.clear());

  it("monta sin crashear y renderiza /login (eager)", () => {
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

  it("resuelve una ruta lazy sin token → redirige a /login", async () => {
    render(
      <MemoryRouter initialEntries={["/insurance-intel"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );
    // Sin sesión, ProtectedRoute redirige a /login; findBy espera el ciclo lazy.
    expect(await screen.findByRole("button")).toBeInTheDocument();
    expect(document.querySelector("input")).not.toBeNull();
  });
});
