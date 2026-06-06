/** @type {import('tailwindcss').Config} */
// SDQ·MIP — dirección "Claro & Vivo". Colores mapeados a CSS vars (ver src/index.css)
// para que el modo claro/oscuro funcione sin tocar el marcado.
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Plus Jakarta Sans", "Inter", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        surface2: "var(--surface-2)",
        ink: "var(--ink)",
        body: "var(--body)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        line: "var(--border)",
        linestrong: "var(--border-strong)",
        accent: {
          DEFAULT: "var(--accent)",
          soft: "var(--accent-soft)",
          hover: "var(--accent-hover)",
          ink: "var(--accent-ink)",
        },
        teal: { DEFAULT: "var(--teal)", soft: "var(--teal-soft)" },
        ok: { DEFAULT: "var(--ok)", soft: "var(--ok-soft)" },
        warn: { DEFAULT: "var(--warn)", soft: "var(--warn-soft)" },
        alert: { DEFAULT: "var(--alert)", soft: "var(--alert-soft)" },
        // data-viz
        c1: "var(--c1)", c2: "var(--c2)", c3: "var(--c3)",
        c4: "var(--c4)", c5: "var(--c5)", c6: "var(--c6)",
      },
      borderRadius: { xl: "12px", "2xl": "16px" },
      boxShadow: {
        card: "var(--shadow-card)",
        pop: "var(--shadow-pop)",
      },
    },
  },
  plugins: [],
};
