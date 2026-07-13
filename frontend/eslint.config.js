// ESLint 9 (flat config) — cierra la brecha 5 de la DD (frontend sin lint).
// TypeScript + React Hooks + higiene básica. Reglas del contrato de diseño
// (sin hex hardcodeado en clases) como warning para no bloquear de golpe.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "*.config.js", "*.config.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: { ...globals.browser },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // Frontera de tipos: `any` explícito es warning (hay usos legítimos en catch/API),
      // no error, para no bloquear el build mientras se tipa progresivamente.
      "@typescript-eslint/no-explicit-any": "warn",
      // Variables/args sin usar: error, pero permitiendo el prefijo _ para descartes.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
      ],
    },
  },
  {
    // Contrato de diseño (DESIGN_SYSTEM.md): los colores van por tokens CSS, no hex.
    // Warning en className para no romper de entrada; se endurece a error cuando llegue a 0.
    files: ["src/**/*.tsx"],
    rules: {
      "no-restricted-syntax": [
        "warn",
        {
          selector: "Literal[value=/#[0-9a-fA-F]{3,8}\\b/]",
          message: "Color hex hardcodeado: usá los tokens CSS (var(--c...)) del design system.",
        },
      ],
    },
  },
);
