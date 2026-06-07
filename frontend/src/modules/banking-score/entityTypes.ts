// Supervised entity types ("áreas") of the Financiero axis (SIB universe).
// `creditModel` = the 19-indicator credit-rating model applies. Exchange houses
// (cambiarias) and trusts (fiduciarias) need their own submodels (pending).
export interface EntityTypeOpt {
  value: string;
  label: string;
  creditModel: boolean;
}

export const ENTITY_TYPES: EntityTypeOpt[] = [
  { value: "", label: "Todos", creditModel: true },
  { value: "banca_multiple", label: "Banca múltiple", creditModel: true },
  { value: "aap", label: "AAyP", creditModel: true },
  { value: "banco_ahorro_credito", label: "Ahorro y crédito", creditModel: true },
  { value: "corporacion_credito", label: "Corp. de crédito", creditModel: true },
  { value: "cambiaria", label: "Cambiarias", creditModel: false },
  { value: "fiduciaria", label: "Fiduciarias", creditModel: false },
];

export const isCreditModel = (value: string): boolean =>
  ENTITY_TYPES.find((t) => t.value === value)?.creditModel ?? true;

export const entityTypeLabel = (value: string): string =>
  ENTITY_TYPES.find((t) => t.value === value)?.label ?? value;
