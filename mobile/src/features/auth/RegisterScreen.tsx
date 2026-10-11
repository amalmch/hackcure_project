import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Alert } from 'react-native';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { authApi } from '../../services/api/auth';
import { createRegisterSchema } from '../../utils/validationSchemas';
import { localizedApiError } from '../../utils/localizedApiError';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { TextInput } from '../../components/ui/TextInput';
import { PrimaryButton } from '../../components/ui/PrimaryButton';

export const RegisterScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();

  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(createRegisterSchema(t)),
    defaultValues: {
      first_name: '',
      last_name: '',
      email: '',
      password: '',
      confirm_password: '',
    },
  });

  const onSubmit = async (data: any) => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      await authApi.register({
        email: data.email,
        password: data.password,
        first_name: data.first_name,
        last_name: data.last_name,
      });

      Alert.alert(
        i18n.t('copy.static_account_created'),
        i18n.t('copy.static_your_patient_profile_has_been_registered_you_can'),
        [{ text: t('auth.proceedToLogin'), onPress: () => router.replace('/(auth)/login') }]
      );
    } catch (err: any) {
      setErrorMsg(localizedApiError(err, t, 'registration'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <ScreenContainer withNetworkBanner={false}>
      <Header title={t('auth.register')} showBack />

      <View style={[styles.content, { paddingVertical: spacing.md }]}>
        <Text style={[typography.h2, { color: colors.textPrimary, textAlign, marginBottom: 8 }]}>
          {i18n.t('copy.static_create_patient_profile')}</Text>
        <Text style={[typography.body, { color: colors.textSecondary, textAlign, marginBottom: spacing.lg }]}>
          {i18n.t('copy.static_register_to_access_your_prescriptions_reminders_')}</Text>

        {errorMsg && (
          <View style={[styles.errorBanner, { backgroundColor: colors.errorLight, borderRadius: radii.lg }]}>
            <Ionicons name="alert-circle" size={18} color={colors.error} style={{ marginHorizontal: 6 }} />
            <Text style={[typography.captionBold, { color: colors.error, flex: 1, textAlign }]}>
              {errorMsg}
            </Text>
          </View>
        )}

        <View style={[styles.row, { flexDirection, gap: 10 }]}>
          <View style={{ flex: 1 }}>
            <Controller
              control={control}
              name="first_name"
              render={({ field: { onChange, onBlur, value } }) => (
                <TextInput
                  label={t('auth.firstName')}
                  placeholder={i18n.t('copy.static_e_g_mohamed')}
                  value={value}
                  onBlur={onBlur}
                  onChangeText={onChange}
                  error={errors.first_name?.message}
                />
              )}
            />
          </View>

          <View style={{ flex: 1 }}>
            <Controller
              control={control}
              name="last_name"
              render={({ field: { onChange, onBlur, value } }) => (
                <TextInput
                  label={t('auth.lastName')}
                  placeholder={i18n.t('copy.static_e_g_benali')}
                  value={value}
                  onBlur={onBlur}
                  onChangeText={onChange}
                  error={errors.last_name?.message}
                />
              )}
            />
          </View>
        </View>

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

        <Controller
          control={control}
          name="password"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              label={t('auth.password')}
              placeholder={t('auth.passwordPlaceholder')}
              secureTextEntry
              value={value}
              onBlur={onBlur}
              onChangeText={onChange}
              error={errors.password?.message}
              leftIcon={<Ionicons name="lock-closed-outline" size={20} color={colors.textMuted} />}
            />
          )}
        />

        <Controller
          control={control}
          name="confirm_password"
          render={({ field: { onChange, onBlur, value } }) => (
            <TextInput
              label={t('auth.confirmPassword')}
              placeholder={t('auth.confirmPassword')}
              secureTextEntry
              value={value}
              onBlur={onBlur}
              onChangeText={onChange}
              error={errors.confirm_password?.message}
              leftIcon={<Ionicons name="lock-closed-outline" size={20} color={colors.textMuted} />}
            />
          )}
        />

        <PrimaryButton
          title={t('auth.register')}
          onPress={handleSubmit(onSubmit)}
          loading={isLoading}
          style={{ marginTop: spacing.xl }}
        />

        <View style={[styles.footerRow, { flexDirection, marginTop: spacing.xl }]}>
          <Text style={[typography.body, { color: colors.textSecondary }]}>
            {t('auth.alreadyHaveAccount')}{' '}
          </Text>
          <TouchableOpacity onPress={() => router.push('/(auth)/login')} activeOpacity={0.7}>
            <Text style={[typography.bodyBold, { color: colors.primary }]}>
              {t('auth.login')}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  content: {
    flex: 1,
  },
  row: {
    alignItems: 'flex-start',
  },
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    marginBottom: 16,
  },
  footerRow: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingBottom: 24,
  },
});
