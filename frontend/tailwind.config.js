/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#1A365D",
          light: "#2B6CB0",
          dark: "#0F2440",
        },
        success: {
          DEFAULT: "#38A169",
          light: "#48BB78",
        },
        danger: {
          DEFAULT: "#E53E3E",
          light: "#FC8181",
        },
        warning: {
          DEFAULT: "#DD6B20",
          light: "#F6AD55",
        },
        gray: {
          50: "#F7FAFC",
          100: "#EDF2F7",
          200: "#E2E8F0",
          500: "#718096",
          700: "#4A5568",
          900: "#1A202C",
        },
      },
    },
  },
  plugins: [],
};
