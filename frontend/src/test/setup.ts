import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Desmonta el árbol de React entre tests (evita fugas de DOM entre casos).
afterEach(() => cleanup());
