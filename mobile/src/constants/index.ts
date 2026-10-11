import Constants from 'expo-constants';
import { Platform } from 'react-native';

// In development, auto-detect host PC IP for physical devices via Expo hostUri on proxy port 8088
const getDevApiUrl = () => {
  if (process.env.EXPO_PUBLIC_API_URL) {
    return process.env.EXPO_PUBLIC_API_URL;
  }
  const hostUri = Constants.expoConfig?.hostUri;
  if (hostUri) {
    const ip = hostUri.split(':')[0];
    if (ip && ip !== 'localhost' && ip !== '127.0.0.1') {
      return `http://${ip}:8088`;
    }
  }

  // Fallback to active LAN IP for physical phone and dev machines
  return 'http://172.20.10.13:8088';
};

export const API_BASE_URL = getDevApiUrl();
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws');

export const STORAGE_KEYS = {
  ACCESS_TOKEN: 'hackcure_access_token',
  REFRESH_TOKEN: 'hackcure_refresh_token',
  USER_DATA: 'hackcure_user_data',
  SETTINGS: 'hackcure_settings',
  OFFLINE_QUEUE: 'hackcure_offline_queue',
  LANGUAGE: 'hackcure_language',
  THEME: 'hackcure_theme',
};

export const DEFAULT_PAGE_SIZE = 20;

export const DOSE_STATUS_CONFIG = {
  SCHEDULED: {
    color: '#3B82F6',
    bgColor: '#EFF6FF',
    labelKey: 'medications.scheduled',
    icon: 'clock',
  },
  DUE: {
    color: '#F59E0B',
    bgColor: '#FFFBEB',
    labelKey: 'medications.due',
    icon: 'alert-circle',
  },
  REMINDING: {
    color: '#D97706',
    bgColor: '#FEF3C7',
    labelKey: 'medications.reminding',
    icon: 'bell',
  },
  TAKEN_ON_TIME: {
    color: '#10B981',
    bgColor: '#ECFDF5',
    labelKey: 'medications.taken',
    icon: 'check-circle',
  },
  TAKEN_LATE: {
    color: '#EAB308',
    bgColor: '#FEFCE8',
    labelKey: 'medications.takenLate',
    icon: 'clock-alert',
  },
  MISSED: {
    color: '#EF4444',
    bgColor: '#FEF2F2',
    labelKey: 'medications.missed',
    icon: 'x-circle',
  },
  CANCELLED: {
    color: '#9CA3AF',
    bgColor: '#F3F4F6',
    labelKey: 'medications.cancelled',
    icon: 'slash',
  },
};
