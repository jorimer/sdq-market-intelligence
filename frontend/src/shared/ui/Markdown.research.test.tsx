/**
 * El informe de Research a la Medida salía en pantalla con `#` y `*` crudos y las tablas
 * rotas: `ResearchPage` tenía su propio renderer mínimo (solo ##/###, viñetas y **negrita**)
 * en vez de usar este componente compartido, que ya soportaba todo eso.
 *
 * Se fija con el markdown REAL del informe del 2026-08-14.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

const INFORME = `# Importaciones de República Dominicana: Composición por Origen

Cobertura del sistema: qué está computado y qué no

---

## China: composición y riesgo de sustitución

Con USD 5,987.94 MM importados en 2025, China presenta la canasta más **concentrada**.

| Cap. | Descripción | USD MM | % del total China |
|------|-------------|--------|-------------------|
| 85 | Aparatos eléctricos y electrónicos | 1,039.52 | 17.36% |
| 84 | Máquinas y aparatos mecánicos | 945.89 | 15.80% |

* Cap. 84 (maquinaria): presente en EE.UU., China, Italia.
* Cap. 85 (electrónica): la mayor posición individual de China.
`;

describe("Markdown en el informe de Research", () => {
  it("renderiza el título de un solo # sin dejar el numeral crudo", () => {
    render(<Markdown text={INFORME} />);
    expect(
      screen.getByText(/Importaciones de República Dominicana/),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("# Importaciones");
  });

  it("renderiza la tabla como tabla, no como texto con pipes", () => {
    const { container } = render(<Markdown text={INFORME} />);
    const tabla = container.querySelector("table");
    expect(tabla).toBeTruthy();
    expect(tabla!.querySelectorAll("tbody tr").length).toBe(2);
    expect(screen.getByText("Aparatos eléctricos y electrónicos")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("|------");
  });

  it("no deja asteriscos ni numerales sueltos en pantalla", () => {
    render(<Markdown text={INFORME} />);
    const txt = document.body.textContent || "";
    expect(txt).not.toContain("**");
    expect(txt).not.toContain("---");
    expect(txt).not.toMatch(/^#/m);
  });

  it("aplica la negrita en vez de mostrar sus asteriscos", () => {
    const { container } = render(<Markdown text={INFORME} />);
    expect(container.querySelector("strong")?.textContent).toBe("concentrada");
  });

  it("convierte las viñetas con * en una lista", () => {
    const { container } = render(<Markdown text={INFORME} />);
    expect(container.querySelectorAll("li").length).toBe(2);
  });
});
