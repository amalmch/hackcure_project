import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { STORAGE_KEYS } from '../constants';

interface SettingsState {
  hasCompletedOnboarding: boolean;
  notificationsEnabled: boolean;
  locationPermissionGranted: boolean;
  isReady: boolean;

  loadSettings: () => Promise<void>;
  setOnboardingCompleted: (completed: boolean) => Promise<void>;
  setNotificationsEnabled: (enabled: boolean) => Promise<void>;
  setLocationPermissionGranted: (granted: boolean) => Promise<void>;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  hasCompletedOnboarding: false,
  notificationsEnabled: true,
  locationPermissionGranted: false,
  isReady: false,

  loadSettings: async () => {
    try {
      const stored = await AsyncStorage.getItem(STORAGE_KEYS.SETTINGS);
      if (stored) {
        const parsed = JSON.parse(stored);
        set({
          hasCompletedOnboarding: !!parsed.hasCompletedOnboarding,
          notificationsEnabled: parsed.notificationsEnabled !== false,
          locationPermissionGranted: !!parsed.locationPermissionGranted,
        });
      }
    } catch {
      // Default values
    } finally {
      set({ isReady: true });
    }
  },

  setOnboardingCompleted: async (completed: boolean) => {
    set({ hasCompletedOnboarding: completed });
    const stored = await AsyncStorage.getItem(STORAGE_KEYS.SETTINGS);
    const parsed = stored ? JSON.parse(stored) : {};
    parsed.hasCompletedOnboarding = completed;
    await AsyncStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(parsed));
  },

  setNotificationsEnabled: async (enabled: boolean) => {
    set({ notificationsEnabled: enabled });
    const stored = await AsyncStorage.getItem(STORAGE_KEYS.SETTINGS);
    const parsed = stored ? JSON.parse(stored) : {};
    parsed.notificationsEnabled = enabled;
    await AsyncStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(parsed));
  },

  setLocationPermissionGranted: async (granted: boolean) => {
    set({ locationPermissionGranted: granted });
    const stored = await AsyncStorage.getItem(STORAGE_KEYS.SETTINGS);
    const parsed = stored ? JSON.parse(stored) : {};
    parsed.locationPermissionGranted = granted;
    await AsyncStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(parsed));
  },
}));
