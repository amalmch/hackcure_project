import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Alert, Image } from 'react-native';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useAuthStore } from '../../store/authStore';
import { createLoginSchema } from '../../utils/validationSchemas';
import { localizedApiError } from '../../utils/localizedApiError';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { TextInput } from '../../components/ui/TextInput';
import { PrimaryButton } from '../../components/ui/PrimaryButton';

export const LoginScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();
  const login = useAuthStore((state) => state.login);

  const [isLoading, setIsLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(createLoginSchema(t)),
    defaultValues: {
      email: '',
      password: '',
    },
  });

  const onSubmit = async (data: { email: string; password: string }) => {
    setIsLoading(true);
    setAuthError(null);
    try {
      await login(data.email, data.password);
      router.replace('/(tabs)');
    } catch (err: any) {
      setAuthError(localizedApiError(err, t, 'login'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleDemoMohamed = () => {
    setValue('email', 'mohamed@example.com');
    setValue('password', 'Test123!@#');
  };

  return (
    <ScreenContainer withNetworkBanner={false}>
      <Header title={t('auth.login')} showBack />

      <View style={[styles.content, { paddingVertical: spacing.lg }]}>
        <View style={{ alignItems: 'center', marginBottom: spacing.md }}>
          <Image
            source={require('../../../assets/hospital_copilot_logo.png')}
            style={{ width: 68, height: 68 }}
            resizeMode="contain"
          />
        </View>
        <Text style={[typography.h2, { color: colors.textPrimary, textAlign, marginBottom: 8 }]}>
          {i18n.t('copy.static_welcome_back')}</Text>
        <Text style={[typography.body, { color: colors.textSecondary, textAlign, marginBottom: spacing.xl }]}>
          {i18n.t('copy.static_enter_your_healthcare_account_credentials_to_vie')}</Text>

        {authError && (
          <View style={[styles.errorBanner, { backgroundColor: colors.errorLight, borderRadius: radii.lg }]}>
            <Ionicons name="alert-circle" size={18} color={colors.error} style={{ marginHorizontal: 6 }} />
            <Text style={[typography.captionBold, { color: colors.error, flex: 1, textAlign }]}>
              {authError}
            </Text>
          </View>
        )}

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

        <TouchableOpacity
          onPress={() => router.push('/(auth)/forgot-password')}
          activeOpacity={0.7}
          style={[styles.forgotBtn, { alignSelf: 'flex-end', marginTop: 8 }]}
        >
          <Text style={[typography.captionBold, { color: colors.primary }]}>
            {t('auth.forgotPassword')}
          </Text>
        </TouchableOpacity>

        <PrimaryButton
          title={t('auth.login')}
          onPress={handleSubmit(onSubmit)}
          loading={isLoading}
          style={{ marginTop: spacing.xl }}
        />

        {/* Demo Fast-Fill Pill */}
        <TouchableOpacity
          onPress={handleDemoMohamed}
          activeOpacity={0.7}
          style={[styles.demoPill, { backgroundColor: colors.primaryLight, borderRadius: radii.full, marginTop: spacing.lg }]}
        >
          <Ionicons name="flash-outline" size={16} color={colors.primary} />
          <Text style={[typography.tiny, { color: colors.primary, fontWeight: '700', marginHorizontal: 6 }]}>
            {i18n.t('copy.static_fast_fill_demo_account_mohamed')}</Text>
        </TouchableOpacity>

        <View style={[styles.footerRow, { flexDirection, marginTop: spacing['2xl'] }]}>
          <Text style={[typography.body, { color: colors.textSecondary }]}>
            {t('auth.dontHaveAccount')}{' '}
          </Text>
          <TouchableOpacity onPress={() => router.push('/(auth)/register')} activeOpacity={0.7}>
            <Text style={[typography.bodyBold, { color: colors.primary }]}>
              {t('auth.register')}
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
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    marginBottom: 16,
  },
  forgotBtn: {
    paddingVertical: 4,
  },
  demoPill: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    paddingHorizontal: 16,
  },
  footerRow: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
