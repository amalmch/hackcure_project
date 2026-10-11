import React, { useEffect } from 'react';
import { Stack } from 'expo-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from '../src/theme/ThemeContext';
import { RTLProvider } from '../src/i18n/RTLContext';
import { useAuthStore } from '../src/store/authStore';
import { useSettingsStore } from '../src/store/settingsStore';
import '../src/i18n'; // Init i18n
import { LoadingScreen } from '../src/components/ui/LoadingScreen';
import { useTranslation } from 'react-i18next';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 1000 * 30, // 30 seconds
    },
  },
});

function RootNavigation() {
  const { t } = useTranslation();
  const isInitialized = useAuthStore((state) => state.isInitialized);
  const initializeAuth = useAuthStore((state) => state.initialize);
  const isSettingsReady = useSettingsStore((state) => state.isReady);
  const loadSettings = useSettingsStore((state) => state.loadSettings);

  useEffect(() => {
    initializeAuth();
    loadSettings();
  }, [initializeAuth, loadSettings]);

  if (!isInitialized || !isSettingsReady) {
    return <LoadingScreen message={t('copy.loadingPortal')} />;
  }

  return (
    <Stack screenOptions={{ headerShown: false, animation: 'fade' }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="onboarding" />
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="treatment/medications" />
      <Stack.Screen name="treatment/medication/[id]" />
      <Stack.Screen name="treatment/adherence" />
      <Stack.Screen name="treatment/sport" />
      <Stack.Screen name="treatment/nutrition" />
      <Stack.Screen name="prescription/[id]" />
      <Stack.Screen name="conversation/[id]" />
      <Stack.Screen name="appointment/list" />
      <Stack.Screen name="appointment/[id]" />
      <Stack.Screen name="medical-records/index" />
      <Stack.Screen name="medical-records/[id]" />
      <Stack.Screen name="notifications" />
      <Stack.Screen name="settings/language" />
      <Stack.Screen name="settings/theme" />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RTLProvider>
          <RootNavigation />
        </RTLProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
