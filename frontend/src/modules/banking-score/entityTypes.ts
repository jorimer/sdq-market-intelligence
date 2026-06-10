// Supervised entity types ("áreas") of the Financiero axis (SIB universe).
// `creditModel` = the 19-indicator credit-rating model applies (Scoring page).
// `submodelReady` = a working rating submodel exists, so ranking/dashboard show
//   real data. Cambiarias use their own (EIC) submodel; fiduciarias use the
//   audited-PDF submodel (SIB supervised portal); public trusts are on a separate
//   health index ("Fideicomisos públicos" page).
export interface EntityTypeOpt {
  value: string;
  label: string;
  creditModel: boolean;
  submodelReady: boolean;
}

export const ENTITY_TYPES: EntityTypeOpt[] = [
  { value: "", label: "Todos", creditModel: true, submodelReady: true },
  { value: "banca_multiple", label: "Banca múltiple", creditModel: true, submodelReady: true },
  { value: "aap", label: "AAyP", creditModel: true, submodelReady: true },
  { value: "banco_ahorro_credito", label: "Ahorro y crédito", creditModel: true, submodelReady: true },
  { value: "corporacion_credito", label: "Corp. de crédito", creditModel: true, submodelReady: true },
  { value: "cambiaria", label: "Cambiarias", creditModel: false, submodelReady: true },
  { value: "fiduciaria", label: "Fiduciarias", creditModel: false, submodelReady: true },
];

export const isCreditModel = (value: string): boolean =>
  ENTITY_TYPES.find((t) => t.value === value)?.creditModel ?? true;

export const isSubmodelReady = (value: string): boolean =>
  ENTITY_TYPES.find((t) => t.value === value)?.submodelReady ?? true;

export const entityTypeLabel = (value: string): string =>
  ENTITY_TYPES.find((t) => t.value === value)?.label ?? value;
