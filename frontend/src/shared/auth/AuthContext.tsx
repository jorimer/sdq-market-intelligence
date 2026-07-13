import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import client from "@/shared/api/client";
import type { User, LoginResponse } from "@/types";
import { roleSatisfies } from "./roles";

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasRole: (role: string) => boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    // Migración: la sesión vive en cookies httpOnly; cualquier token legado en
    // localStorage (esquema anterior, robable por XSS) se purga.
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    try {
      // La cookie manda sola; 200 = sesión viva, 401 = no logueado.
      const { data } = await client.get<User>("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (email: string, password: string) => {
    // El backend setea las cookies httpOnly en la respuesta; los tokens del body
    // no se persisten (son para clientes de API por header Bearer).
    const { data } = await client.post<LoginResponse>("/auth/login", {
      email,
      password,
    });
    setUser({
      id: data.user_id,
      email: data.email,
      full_name: data.full_name,
      role: data.role,
      tier: data.tier,
      is_active: true,
    });
  };

  const logout = () => {
    // Solo el backend puede borrar cookies httpOnly. Best-effort: el estado local
    // se limpia igual aunque la red falle.
    client.post("/auth/logout").catch(() => undefined);
    setUser(null);
  };

  // Jerárquico: un rol superior satisface el requerimiento de uno inferior.
  const hasRole = (role: string) => roleSatisfies(user?.role, role);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
        hasRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
