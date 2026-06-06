import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { authApi } from "../lib/api";
import type { User } from "../lib/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  setUser: (user: User | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await authApi.me();
      setUser(me);
      return me;
    } catch (e) {
      setUser(null);
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh().catch(() => {
      /* not signed in — expected on /login */
    });
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ user, loading, refresh, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
