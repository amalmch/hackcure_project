import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, StyleSheet, Alert } from 'react-native';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { authApi } from '../../services/api/auth';
import { createForgotPasswordSchema } from '../../utils/validationSchemas';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { TextInput } from '../../components/ui/TextInput';
import { PrimaryButton } from '../../components/ui/PrimaryButton';

export const ForgotPasswordScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing } = useTheme();
  const { textAlign } = useRTL();
  const { t } = useTranslation();

  const [isLoading, setIsLoading] = useState(false);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(createForgotPasswordSchema(t)),
    defaultValues: { email: '' },
  });

  const onSubmit = async (data: { email: string }) => {
    setIsLoading(true);
    try {
      await authApi.forgotPassword(data.email);
      Alert.alert(
        i18n.t('copy.static_check_your_email'),
        i18n.t('copy.static_if_an_account_is_associated_with_this_email_we_h'),
        [{ text: t('auth.backToLoginButton'), onPress: () => router.back() }]
      );
    } catch {
      Alert.alert(
        i18n.t('copy.static_request_submitted'),
        i18n.t('copy.static_if_an_account_is_associated_with_this_email_inst'),
        [{ text: t('auth.backToLoginButton'), onPress: () => router.back() }]
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <ScreenContainer withNetworkBanner={false}>
      <Header title={t('auth.forgotPassword')} showBack />

      <View style={[styles.content, { paddingVertical: spacing.lg }]}>
        <Text style={[typography.h2, { color: colors.textPrimary, textAlign, marginBottom: 8 }]}>
          {t('auth.forgotPasswordTitle')}
        </Text>
        <Text style={[typography.body, { color: colors.textSecondary, textAlign, marginBottom: spacing.xl }]}>
          {t('auth.forgotPasswordDesc')}
        </Text>

        <Controller
          control={control}
          name="email"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              label={t('auth.email')}
              placeholder={t('auth.emailPlaceholder')}
              keyboardType="email-address"
              autoCapitalize="none"
              value={value}
              onBlur={onBlur}
              onChangeText={onChange}
              error={errors.email?.message}
              leftIcon={<Ionicons name="mail-outline" size={20} color={colors.textMuted} />}
            />
          )}
        />

        <PrimaryButton
          title={t('auth.sendResetLink')}
          onPress={handleSubmit(onSubmit)}
          loading={isLoading}
          style={{ marginTop: spacing.xl }}
        />
      </View>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  content: {
    flex: 1,
  },
});
