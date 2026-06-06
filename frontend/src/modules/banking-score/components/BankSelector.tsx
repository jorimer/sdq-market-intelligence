import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Search, Building2 } from "lucide-react";
import client from "@/shared/api/client";

interface Props {
  value: string;
  onChange: (bank: string) => void;
  placeholder?: string;
}

export function BankSelector({ value, onChange, placeholder }: Props) {
  const { t } = useTranslation();
  const [banks, setBanks] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    client
      .get<string[]>("/banking-score/data/banks")
      .then((r) => setBanks(r.data))
      .catch(() => setBanks([]));
  }, []);

  const filtered = banks.filter((b) =>
    b.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="field flex items-center gap-2 text-left"
      >
        <Building2 className="w-4 h-4 text-faint" />
        <span className={value ? "text-ink" : "text-faint"}>
          {value || placeholder || t("scoring.selectBank")}
        </span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full bg-surface rounded-lg shadow-lg border border-line max-h-60 overflow-hidden">
          <div className="p-2 border-b border-line">
            <div className="flex items-center gap-2 px-2">
              <Search className="w-4 h-4 text-faint" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full text-sm outline-none"
                placeholder={t("common.search")}
                autoFocus
              />
            </div>
          </div>
          <ul className="overflow-y-auto max-h-48">
            {filtered.map((bank) => (
              <li key={bank}>
                <button
                  onClick={() => {
                    onChange(bank);
                    setOpen(false);
                    setSearch("");
                  }}
                  className={`w-full text-left px-4 py-2 text-sm hover:bg-surface2 ${
                    bank === value ? "bg-accent-soft text-ink font-medium" : ""
                  }`}
                >
                  {bank}
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="px-4 py-3 text-sm text-faint text-center">
                {t("common.noData")}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
