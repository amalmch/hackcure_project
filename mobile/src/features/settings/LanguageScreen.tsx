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
import { useRTL, SupportedLanguage } from '../../i18n/RTLContext';

interface LanguageOption {
  code: SupportedLanguage;
  name: string;
  nativeName: string;
  flag: string;
}

const LANGUAGES: LanguageOption[] = [
  { code: 'en', name: 'English', nativeName: 'English', flag: '🇬🇧' },
  { code: 'fr', name: 'French', nativeName: 'Français', flag: '🇫🇷' },
  { code: 'ar', name: 'Arabic', nativeName: 'العربية (RTL)', flag: '🇹🇳' },
];

export const LanguageScreen: React.FC = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { language, changeLanguage, isRTL, textAlign, flexDirection } = useRTL();

  const handleSelectLanguage = async (code: SupportedLanguage) => {
    if (code !== language) {
      await changeLanguage(code);
    }
  };

  return (
    <ScreenContainer scrollable>
      <Header
        title={t('profile.language')}
        showBack
        onBack={() => router.back()}
      />

      <View style={{ marginTop: spacing.md, marginBottom: spacing.lg }}>
        <Text style={[typography.body, { color: colors.textSecondary, textAlign }]}>
          {i18n.t('copy.static_select_your_preferred_application_language_right')}</Text>
      </View>

      <View style={{ gap: spacing.md }}>
        {LANGUAGES.map((lang) => {
          const isSelected = language === lang.code;
          return (
            <TouchableOpacity
              key={lang.code}
              activeOpacity={0.7}
              onPress={() => handleSelectLanguage(lang.code)}
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
                  <Text style={styles.flagText}>{lang.flag}</Text>
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
                      {lang.nativeName}
                    </Text>
                    <Text
                      style={[
                        typography.caption,
                        { color: colors.textSecondary, textAlign },
                      ]}
                    >
                      {lang.name}
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
  flagText: {
    fontSize: 28,
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
