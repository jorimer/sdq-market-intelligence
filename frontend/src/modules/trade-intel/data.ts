import { Flow } from "./api";

// Illustrative RD trade basket.
// Datos ilustrativos — en producción provienen de BCRD (sector externo) y DGA.

export const SAMPLE_FLOWS: Flow[] = [
  { product: "Instrumentos médicos", direction: "export", value: 2100, partner: "US" },
  { product: "Ferroníquel", direction: "export", value: 1200, partner: "US" },
  { product: "Cigarros", direction: "export", value: 900, partner: "EU" },
  { product: "Oro", direction: "export", value: 1500, partner: "CH" },
  { product: "Cacao", direction: "export", value: 400, partner: "EU" },
  { product: "Bananas", direction: "export", value: 350, partner: "EU" },
  { product: "Petróleo", direction: "import", value: 3800, partner: "US" },
  { product: "Vehículos", direction: "import", value: 1600, partner: "JP" },
  { product: "Maquinaria", direction: "import", value: 1400, partner: "CN" },
];
