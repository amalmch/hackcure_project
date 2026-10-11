import React from 'react';
import { View, Text, StyleSheet, Image, useWindowDimensions } from 'react-native';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { PrimaryButton } from '../../components/ui/PrimaryButton';
import { SecondaryButton } from '../../components/ui/SecondaryButton';

export const WelcomeScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing } = useTheme();
  const { textAlign } = useRTL();
  const { t } = useTranslation();
  const { height, width } = useWindowDimensions();

  const logoSize = Math.min(Math.max(width * 0.24, 75), 105);
  const isSmallHeight = height < 680;

  return (
    <ScreenContainer scrollable={true} withNetworkBanner={false} withPadding={false} contentContainerStyle={{ flexGrow: 1 }}>
      <View
        style={[
          styles.container,
          {
            backgroundColor: colors.background,
            paddingHorizontal: spacing.xl,
            paddingTop: isSmallHeight ? spacing.md : spacing['2xl'],
            paddingBottom: spacing.lg,
          },
        ]}
      >
        <View style={styles.heroSection}>
          <View
            style={[
              styles.iconCircle,
              {
                width: logoSize + 24,
                height: logoSize + 24,
                backgroundColor: '#ffffff',
                borderRadius: 28,
                marginBottom: isSmallHeight ? 14 : 22,
                overflow: 'hidden',
                shadowColor: '#000',
                shadowOffset: { width: 0, height: 6 },
                shadowOpacity: 0.12,
                shadowRadius: 14,
                elevation: 5,
              },
            ]}
          >
            <Image
              source={require('../../../assets/hospital_copilot_logo.png')}
              style={{ width: logoSize + 12, height: logoSize + 12 }}
              resizeMode="contain"
            />
          </View>

          <Text
            style={[
              typography.h1,
              styles.brandName,
              {
                color: colors.primary,
                textAlign,
                fontSize: isSmallHeight ? 26 : 30,
              },
            ]}
          >
            Hospital Copilot
          </Text>

          <Text
            style={[
              typography.h3,
              styles.title,
              {
                color: colors.textPrimary,
                textAlign,
                fontSize: isSmallHeight ? 17 : 20,
              },
            ]}
          >
            {t('auth.welcomeTitle')}
          </Text>

          <Text
            style={[
              typography.body,
              styles.subtitle,
              {
                color: colors.textSecondary,
                textAlign,
                fontSize: isSmallHeight ? 13 : 14,
              },
            ]}
          >
            {t('auth.welcomeSubtitle')}
          </Text>
        </View>

        <View style={[styles.actionSection, { paddingTop: isSmallHeight ? 12 : 28 }]}>
          <PrimaryButton
            title={t('auth.login')}
            onPress={() => router.push('/(auth)/login')}
            style={{ marginBottom: spacing.md }}
          />

          <SecondaryButton
            title={t('auth.register')}
            onPress={() => router.push('/(auth)/register')}
            variant="outline"
          />
        </View>
      </View>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    minHeight: '100%',
    justifyContent: 'space-between',
  },
  heroSection: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 8,
    minHeight: 280,
  },
  iconCircle: {
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 10,
    elevation: 3,
  },
  brandName: {
    fontWeight: '800',
    letterSpacing: -0.5,
    marginBottom: 8,
  },
  title: {
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    maxWidth: 320,
    lineHeight: 22,
    textAlign: 'center',
  },
  actionSection: {
    width: '100%',
    paddingBottom: 16,
  },
});
