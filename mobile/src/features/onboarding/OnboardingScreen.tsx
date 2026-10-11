import React, { useState } from 'react';
import { Platform, View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import * as Location from 'expo-location';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import { useTheme } from '../../theme';
import { useRTL, SupportedLanguage } from '../../i18n/RTLContext';
import { useSettingsStore } from '../../store/settingsStore';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { PrimaryButton } from '../../components/ui/PrimaryButton';

export const OnboardingScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection, changeLanguage, language } = useRTL();
  const { t } = useTranslation();
  const setOnboardingCompleted = useSettingsStore((state) => state.setOnboardingCompleted);
  const setNotificationsEnabled = useSettingsStore((state) => state.setNotificationsEnabled);
  const setLocationPermissionGranted = useSettingsStore((state) => state.setLocationPermissionGranted);

  const [currentStep, setCurrentStep] = useState(0);

  const requestOptionalPermissions = async () => {
    const isExpoGo = Constants.appOwnership === 'expo' || Constants.executionEnvironment === ExecutionEnvironment.StoreClient;
    if (Platform.OS === 'web' || isExpoGo) {
      await setNotificationsEnabled(false);
    } else {
      try {
        const Notifications = await import('expo-notifications');
        const notifStatus = await Notifications.requestPermissionsAsync();
        await setNotificationsEnabled(notifStatus.status === 'granted');
      } catch {
        await setNotificationsEnabled(false);
      }
    }
    try {
      const locStatus = await Location.requestForegroundPermissionsAsync();
      await setLocationPermissionGranted(locStatus.status === 'granted');
    } catch {
      // Location remains optional; the related feature can request permission when used.
    }
  };

  const completeOnboarding = async () => {
    await setOnboardingCompleted(true);
    router.replace('/');
    void requestOptionalPermissions();
  };

  const steps = [
    {
      icon: 'shield-checkmark' as const,
      color: colors.primary,
      bg: colors.primaryLight,
      title: t('onboarding.step1Title'),
      desc: t('onboarding.step1Desc'),
    },
    {
      icon: 'alarm' as const,
      color: '#EA580C',
      bg: '#FFEDD5',
      title: t('onboarding.step2Title'),
      desc: t('onboarding.step2Desc'),
    },
    {
      icon: 'fitness' as const,
      color: colors.secondary,
      bg: colors.secondaryLight,
      title: t('onboarding.step3Title'),
      desc: t('onboarding.step3Desc'),
    },
    {
      icon: 'business' as const,
      color: colors.success,
      bg: colors.successLight,
      title: t('onboarding.step4Title'),
      desc: t('onboarding.step4Desc'),
    },
    {
      icon: 'chatbubbles' as const,
      color: colors.accent,
      bg: '#EEF2FF',
      title: t('onboarding.step5Title'),
      desc: t('onboarding.step5Desc'),
    },
  ];

  const handleNext = async () => {
    if (currentStep < steps.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      await completeOnboarding();
    }
  };

  const handleSkip = async () => {
    await completeOnboarding();
  };

  const step = steps[currentStep];

  return (
    <ScreenContainer scrollable={false} withNetworkBanner={false} withPadding={false}>
      <View style={[styles.container, { backgroundColor: colors.background, padding: spacing.xl }]}>
        {/* Top Language Bar & Skip */}
        <View style={[styles.topBar, { flexDirection }]}>
          {/* Language selector pills */}
          <View style={[styles.langSelector, { backgroundColor: colors.inputBg, borderRadius: radii.full }]}>
            {(['en', 'fr', 'ar'] as SupportedLanguage[]).map((lang) => (
              <TouchableOpacity
                key={lang}
                onPress={() => changeLanguage(lang)}
                style={[
                  styles.langBtn,
                  language === lang && { backgroundColor: colors.primary, borderRadius: radii.full },
                ]}
              >
                <Text
                  style={[
                    typography.tiny,
                    { color: language === lang ? '#FFFFFF' : colors.textSecondary, fontWeight: '700' },
                  ]}
                >
                  {lang.toUpperCase()}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <TouchableOpacity onPress={handleSkip} activeOpacity={0.7} style={styles.skipBtn}>
            <Text style={[typography.captionBold, { color: colors.textMuted }]}>
              {t('onboarding.skip')}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Step Content */}
        <View style={styles.body}>
          <View
            style={[
              styles.iconWrapper,
              { backgroundColor: step.bg, borderRadius: radii.full },
            ]}
          >
            <Ionicons name={step.icon} size={72} color={step.color} />
          </View>

          <Text style={[typography.h2, styles.title, { color: colors.textPrimary, textAlign }]}>
            {step.title}
          </Text>

          <Text style={[typography.body, styles.desc, { color: colors.textSecondary, textAlign }]}>
            {step.desc}
          </Text>
        </View>

        {/* Pagination Dots & Navigation */}
        <View style={styles.footer}>
          <View style={[styles.dotsRow, { flexDirection }]}>
            {steps.map((_, idx) => (
              <View
                key={idx}
                style={[
                  styles.dot,
                  {
                    backgroundColor: idx === currentStep ? colors.primary : colors.cardBorder,
                    width: idx === currentStep ? 24 : 8,
                    borderRadius: radii.full,
                  },
                ]}
              />
            ))}
          </View>

          <PrimaryButton
            title={currentStep === steps.length - 1 ? t('onboarding.getStarted') : t('onboarding.next')}
            onPress={handleNext}
          />
        </View>
      </View>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'space-between',
  },
  topBar: {
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 8,
  },
  langSelector: {
    flexDirection: 'row',
    padding: 3,
  },
  langBtn: {
    paddingVertical: 4,
    paddingHorizontal: 10,
  },
  skipBtn: {
    padding: 8,
  },
  body: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  iconWrapper: {
    width: 140,
    height: 140,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 32,
  },
  title: {
    marginBottom: 12,
  },
  desc: {
    maxWidth: 320,
    lineHeight: 24,
  },
  footer: {
    paddingBottom: 24,
  },
  dotsRow: {
    justifyContent: 'center',
    alignItems: 'center',
    gap: 6,
    marginBottom: 24,
  },
  dot: {
    height: 8,
  },
});
