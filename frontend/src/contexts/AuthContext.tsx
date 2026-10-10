import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

export type UserRole = 'USER' | 'GOVERNMENT_OFFICIAL';

export interface AuthUser {
  name: string;
  email: string;
  role: UserRole;
}

interface AuthContextType {
  user: AuthUser | null;
  login: (name: string, email: string, role: UserRole) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => {
    const stored = localStorage.getItem('chainguard_user');
    return stored ? JSON.parse(stored) : null;
  });

  const login = useCallback((name: string, email: string, role: UserRole) => {
    const newUser: AuthUser = { name, email, role };
    setUser(newUser);
    localStorage.setItem('chainguard_user', JSON.stringify(newUser));
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem('chainguard_user');
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
