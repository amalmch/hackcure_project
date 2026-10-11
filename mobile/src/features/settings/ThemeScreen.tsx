import i18n from '../../i18n';
import React from 'react';
import { View, StyleSheet, TouchableOpacity, Text } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { Card } from '../../components/ui/Card';
import { useTheme } from '../../theme/ThemeContext';
import { useRTL } from '../../i18n/RTLContext';

type ThemeOption = {
  key: 'light' | 'dark' | 'system';
  titleKey: string;
  descKey: string;
  icon: keyof typeof Ionicons.glyphMap;
};

const THEMES: ThemeOption[] = [
  {
    key: 'system',
    titleKey: 'profile.systemMode',
    descKey: 'profile.systemModeDesc',
    icon: 'phone-portrait-outline',
  },
  {
    key: 'light',
    titleKey: 'profile.lightMode',
    descKey: 'profile.lightModeDesc',
    icon: 'sunny-outline',
  },
  {
    key: 'dark',
    titleKey: 'profile.darkMode',
    descKey: 'profile.darkModeDesc',
    icon: 'moon-outline',
  },
];

export const ThemeScreen: React.FC = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const { mode, setMode, colors, typography, spacing } = useTheme();
  const { textAlign, flexDirection } = useRTL();

  return (
    <ScreenContainer scrollable>
      <Header
        title={t('profile.theme')}
        showBack
        onBack={() => router.back()}
      />

      <View style={{ marginTop: spacing.md, marginBottom: spacing.lg }}>
        <Text style={[typography.body, { color: colors.textSecondary, textAlign }]}>
          {i18n.t('copy.static_choose_your_visual_appearance_preference_for_hac')}</Text>
      </View>

      <View style={{ gap: spacing.md }}>
        {THEMES.map((item) => {
          const isSelected = mode === item.key;
          return (
            <TouchableOpacity
              key={item.key}
              activeOpacity={0.7}
              onPress={() => setMode(item.key)}
            >
              <Card
                variant={isSelected ? 'elevated' : 'outlined'}
                style={[
                  styles.optionCard,
                  {
                    borderColor: isSelected ? colors.primary : colors.cardBorder,
                    borderWidth: isSelected ? 2 : 1,
                    backgroundColor: isSelected ? `${colors.primary}10` : colors.card,
                  },
                ]}
              >
                <View style={[styles.cardContent, { flexDirection }]}>
                  <View
                    style={[
                      styles.iconCircle,
                      {
                        backgroundColor: isSelected ? colors.primary : colors.surface,
                      },
                    ]}
                  >
                    <Ionicons
                      name={item.icon}
                      size={24}
                      color={isSelected ? '#FFFFFF' : colors.textSecondary}
                    />
                  </View>

                  <View style={styles.textContainer}>
                    <Text
                      style={[
                        typography.subtitle,
                        {
                          color: isSelected ? colors.primary : colors.textPrimary,
                          textAlign,
                          fontWeight: isSelected ? '700' : '500',
                        },
                      ]}
                    >
                      {t(item.titleKey)}
                    </Text>
                    <Text
                      style={[
                        typography.caption,
                        { color: colors.textSecondary, textAlign },
                      ]}
                    >
                        {t(item.descKey)}
                    </Text>
                  </View>

                  <View
                    style={[
                      styles.radioCircle,
                      {
                        borderColor: isSelected ? colors.primary : colors.textMuted,
                        backgroundColor: isSelected ? colors.primary : 'transparent',
                      },
                    ]}
                  >
                    {isSelected && (
                      <Ionicons name="checkmark" size={14} color="#FFFFFF" />
                    )}
                  </View>
                </View>
              </Card>
            </TouchableOpacity>
          );
        })}
      </View>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  optionCard: {
    padding: 16,
  },
  cardContent: {
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  iconCircle: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 8,
  },
  textContainer: {
    flex: 1,
    marginHorizontal: 12,
  },
  radioCircle: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
