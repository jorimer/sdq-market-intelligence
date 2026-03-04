import { useTranslation } from "react-i18next";
import { useAuth } from "@/shared/auth/AuthContext";
import { Globe, LogOut, User } from "lucide-react";

export function Navbar() {
  const { t, i18n } = useTranslation();
  const { user, logout } = useAuth();

  const toggleLang = () => {
    const next = i18n.language === "es" ? "en" : "es";
    i18n.changeLanguage(next);
    localStorage.setItem("lang", next);
  };

  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6">
      <h1 className="text-lg font-bold text-primary">
        SDQ Market Intelligence
      </h1>

      <div className="flex items-center gap-4">
        <button
          onClick={toggleLang}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-primary transition-colors"
        >
          <Globe className="w-4 h-4" />
          {i18n.language.toUpperCase()}
        </button>

        <div className="flex items-center gap-2 text-sm text-gray-700">
          <User className="w-4 h-4" />
          <span>{user?.full_name}</span>
        </div>

        <button
          onClick={logout}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-danger transition-colors"
          title={t("auth.logout")}
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
