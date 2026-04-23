import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  login: (token: string, refresh: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      refreshToken: null,
      login: (token, refreshToken) => set({ token, refreshToken }),
      logout: () => set({ token: null, refreshToken: null }),
    }),
    { name: "auth" }
  )
);

interface TickerState {
  prices: Record<string, number>;
  setPrice: (symbol: string, price: number) => void;
}

export const useTickerStore = create<TickerState>((set) => ({
  prices: {},
  setPrice: (symbol, price) =>
    set((s) => ({ prices: { ...s.prices, [symbol]: price } })),
}));
