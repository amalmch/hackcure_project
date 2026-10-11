import { create } from 'zustand';
import { storage } from '../utils/storage';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { User, Patient, AuthTokens } from '../types';
import { STORAGE_KEYS } from '../constants';
import { authApi } from '../services/api/auth';
import { patientApi } from '../services/api/patient';

interface AuthState {
  user: User | null;
  patient: Patient | null;
  tokens: AuthTokens | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isInitialized: boolean;
  
  initialize: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  expireSession: () => Promise<void>;
  updatePatientProfile: (patient: Patient) => void;
  setUser: (user: User) => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  patient: null,
  tokens: null,
  isLoading: false,
  isAuthenticated: false,
  isInitialized: false,

  initialize: async () => {
    try {
      set({ isLoading: true });
      const accessToken = await storage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
      const refreshToken = await storage.getItem(STORAGE_KEYS.REFRESH_TOKEN);
      const cachedUserData = await AsyncStorage.getItem(STORAGE_KEYS.USER_DATA);

      if (accessToken && refreshToken) {
        let user: User | null = null;
        if (cachedUserData) {
          try {
            user = JSON.parse(cachedUserData);
          } catch {
            user = null;
          }
        }

        set({
          tokens: { access_token: accessToken, refresh_token: refreshToken, token_type: 'bearer' },
          user,
          isAuthenticated: true,
        });

        // Fetch fresh profile in background
        try {
          const patientProfile = await patientApi.getProfile();
          set({ patient: patientProfile });
        } catch {
          // If network is offline, continue with cached state
        }
      }
    } catch {
      set({ isAuthenticated: false, user: null, patient: null, tokens: null });
    } finally {
      set({ isLoading: false, isInitialized: true });
    }
  },

  login: async (email: string, password: string) => {
    set({ isLoading: true });
    try {
      const data = await authApi.login({ email, password });
      await storage.setItem(STORAGE_KEYS.ACCESS_TOKEN, data.access_token);
      await storage.setItem(STORAGE_KEYS.REFRESH_TOKEN, data.refresh_token);
      await AsyncStorage.setItem(STORAGE_KEYS.USER_DATA, JSON.stringify(data.user));

      set({
        tokens: {
          access_token: data.access_token,
          refresh_token: data.refresh_token,
          token_type: data.token_type,
        },
        user: data.user,
        isAuthenticated: true,
      });

      // Retrieve full patient record
      try {
        const patientProfile = await patientApi.getProfile();
        set({ patient: patientProfile });
      } catch {
        // Fallback
      }
    } finally {
      set({ isLoading: false });
    }
  },

  expireSession: async () => {
    await Promise.allSettled([
      storage.deleteItem(STORAGE_KEYS.ACCESS_TOKEN),
      storage.deleteItem(STORAGE_KEYS.REFRESH_TOKEN),
      AsyncStorage.removeItem(STORAGE_KEYS.USER_DATA),
    ]);
    set({ user: null, patient: null, tokens: null, isAuthenticated: false });
  },

  logout: async () => {
    try {
      await authApi.logout();
    } catch {
      // Ignore network errors on logout
    }
    await get().expireSession();
  },

  updatePatientProfile: (patient: Patient) => {
    set({ patient });
  },

  setUser: (user: User) => {
    set({ user });
  },
}));
