import { useState, useEffect } from "react";
import { Search, Building2, ChevronDown } from "lucide-react";
import { listBanks, BankRef } from "../api";
import { ENTITY_TYPES } from "../entityTypes";

interface Props {
  value: string; // bank id
  onChange: (id: string, name: string) => void;
  placeholder?: string;
}

export function BankSelector({ value, onChange, placeholder }: Props) {
  const [banks, setBanks] = useState<BankRef[]>([]);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState(""); // entity_type ("área")
  const [open, setOpen] = useState(false);

  useEffect(() => {
    listBanks()
      .then(setBanks)
      .catch(() => setBanks([]));
  }, []);

  const filtered = banks.filter(
    (b) =>
      b.name.toLowerCase().includes(search.toLowerCase()) &&
      (!typeFilter || b.bank_type === typeFilter),
  );
  const selectedName = banks.find((b) => b.id === value)?.name;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="field flex items-center gap-2 text-left"
      >
        <Building2 className="w-4 h-4 text-faint shrink-0" />
        <span className={`min-w-0 flex-1 truncate ${selectedName ? "text-ink" : "text-faint"}`}>
          {selectedName || placeholder || "Seleccionar entidad"}
        </span>
        <ChevronDown className="w-4 h-4 text-faint shrink-0" />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full bg-surface rounded-[10px] shadow-pop border border-line max-h-72 overflow-hidden">
          <div className="p-2 border-b border-line space-y-2">
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="field text-sm py-1.5"
            >
              {ENTITY_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.value === "" ? "Todos los tipos" : t.label}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-2 px-2">
              <Search className="w-4 h-4 text-faint" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full text-sm outline-none bg-transparent text-ink py-1"
                placeholder="Buscar…"
                autoFocus
              />
            </div>
          </div>
          <ul className="overflow-y-auto max-h-56">
            {filtered.map((bank) => (
              <li key={bank.id}>
                <button
                  onClick={() => {
                    onChange(bank.id, bank.name);
                    setOpen(false);
                    setSearch("");
                  }}
                  className={`w-full text-left px-4 py-2 text-sm hover:bg-surface2 truncate ${
                    bank.id === value ? "bg-accent-soft text-accent-ink font-medium" : "text-body"
                  }`}
                >
                  {bank.name}
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-4 py-3 text-sm text-faint text-center">Sin resultados</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
