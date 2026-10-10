import { createContext, useContext, useState, type ReactNode } from 'react';

export type Persona = 'USER' | 'GOV_OFFICIAL';
export type AccountRole = 'PRODUCER' | 'RECYCLER_EMPLOYEE' | 'GOVERNMENT_OFFICER' | 'ADMINISTRATOR';

export interface AuthUser {
  id: string;
  name: string;
  username: string;
  persona: Persona;
  role: AccountRole;
  facility_ids: string[];
  organisation: string;
  department?: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  login: (user: AuthUser, token: string) => void;
  logout: () => void;
}

const TOKEN_KEY = 'chainguard_access_token';
const USER_KEY = 'chainguard_user';

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

function readStoredUser(): AuthUser | null {
  try {
    const user = localStorage.getItem(USER_KEY);
    if (!user || !getAccessToken()) return null;
    const parsed = JSON.parse(user) as Partial<AuthUser>;
    if (!parsed.id || !parsed.persona) return null;
    return { ...parsed, role: parsed.role ?? (parsed.persona === 'GOV_OFFICIAL' ? 'GOVERNMENT_OFFICER' : 'PRODUCER'),
      facility_ids: parsed.facility_ids ?? [] } as AuthUser;
  } catch {
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(TOKEN_KEY);
    return null;
  }
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(readStoredUser);
  const login = (newUser: AuthUser, token: string) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(newUser));
    setUser(newUser);
  };
  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
  };
  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
