import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert, Switch } from 'react-native';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useAuthStore } from '../../store/authStore';
import { useSettingsStore } from '../../store/settingsStore';
import { formatDate } from '../../utils/dateUtils';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { Card } from '../../components/ui/Card';
import { Avatar } from '../../components/ui/Avatar';
import { ListItem } from '../../components/ui/ListItem';
import { ConfirmationDialog } from '../../components/ui/ConfirmationDialog';

export const ProfileScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, isDark, mode, setMode } = useTheme();
  const { textAlign, flexDirection, language, changeLanguage } = useRTL();
  const { t } = useTranslation();

  const user = useAuthStore((state) => state.user);
  const patient = useAuthStore((state) => state.patient);
  const logout = useAuthStore((state) => state.logout);

  const notificationsEnabled = useSettingsStore((state) => state.notificationsEnabled);
  const setNotificationsEnabled = useSettingsStore((state) => state.setNotificationsEnabled);

  const [logoutModalVisible, setLogoutModalVisible] = useState(false);

  const fullName = patient
    ? `${patient.first_name} ${patient.last_name}`
    : user?.email?.split('@')[0] || t('copy.patient');

  const handleLogoutConfirm = async () => {
    setLogoutModalVisible(false);
    await logout();
    router.replace('/(auth)/welcome');
  };

  return (
    <ScreenContainer>
      <Header title={t('profile.title')} />

      {/* Patient Identity Card */}
      <Card style={styles.userCard}>
        <View style={[styles.userRow, { flexDirection }]}>
          <Avatar name={fullName} url={patient?.avatar_url} size={64} />
          <View style={styles.userInfoCol}>
            <Text style={[typography.h3, { color: colors.textPrimary, textAlign }]}>
              {fullName}
            </Text>
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign, marginTop: 2 }]}>
              {user?.email}
            </Text>
            <View style={[styles.badgePill, { backgroundColor: colors.primaryLight, marginTop: 6 }]}>
              <Text style={[typography.tiny, { color: colors.primary, fontWeight: '700' }]}>
                {i18n.t('copy.static_verified_patient_portal')}</Text>
            </View>
          </View>
        </View>
      </Card>

      {/* Clinical Profile (Protected) */}
      <View style={{ marginTop: spacing.base }}>
        <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
          {i18n.t('copy.static_clinical_profile_verified_by_healthcare_system')}</Text>

        <Card style={styles.clinicalCard}>
          <View style={[styles.metricRow, { flexDirection }]}>
            <View style={styles.metricItem}>
              <Text style={[typography.caption, { color: colors.textMuted }]}>
                {t('profile.bloodType')}
              </Text>
              <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '700' }]}>
                {patient?.blood_type || 'A+'}
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={[typography.caption, { color: colors.textMuted }]}>
                {i18n.t('copy.static_date_of_birth')}</Text>
              <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '700' }]}>
                {patient?.date_of_birth ? formatDate(patient.date_of_birth) : '1990-05-15'}
              </Text>
            </View>

            <View style={styles.metricItem}>
              <Text style={[typography.caption, { color: colors.textMuted }]}>
                {i18n.t('copy.static_height_weight')}</Text>
              <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '700' }]}>
                {patient?.height_cm || 178} cm • {patient?.weight_kg || 75} kg
              </Text>
            </View>
          </View>

          {/* Emergency Contact */}
          <View style={[styles.divider, { backgroundColor: colors.cardBorder }]} />
          <View style={[styles.metaBlock, { flexDirection }]}>
            <Ionicons name="call-outline" size={18} color={colors.primary} style={{ marginHorizontal: 4 }} />
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {t('profile.emergencyContact')} :{' '}
              <Text style={{ fontWeight: '700', color: colors.textPrimary }}>
                {patient?.emergency_contact_name || t('copy.familyContact')} {' '}{patient?.emergency_contact_phone || '+216 98 000 000'}
              </Text>
            </Text>
          </View>
        </Card>
      </View>

      {/* App Preferences */}
      <View style={{ marginTop: spacing.lg }}>
        <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
          {i18n.t('copy.static_preferences')}</Text>

        <ListItem
          title={t('profile.language')}
          subtitle={language === 'ar' ? 'العربية' : language === 'fr' ? 'Français' : 'English'}
          leftIcon={<Ionicons name="globe-outline" size={22} color={colors.primary} />}
          onPress={() => router.push('/settings/language')}
        />

        <ListItem
          title={t('profile.theme')}
          subtitle={mode === 'dark' ? t('profile.darkMode') : mode === 'light' ? t('profile.lightMode') : t('profile.systemMode')}
          leftIcon={<Ionicons name="moon-outline" size={22} color={colors.secondary} />}
          onPress={() => router.push('/settings/theme')}
        />

        <ListItem
          title={t('profile.notifications')}
          subtitle={notificationsEnabled ? t('copy.enabled') : t('copy.disabled')}
          leftIcon={<Ionicons name="notifications-outline" size={22} color={colors.accent} />}
          showChevron={false}
          rightElement={
            <Switch
              value={notificationsEnabled}
              onValueChange={setNotificationsEnabled}
              trackColor={{ false: colors.cardBorder, true: colors.primary }}
            />
          }
        />
      </View>

      {/* Logout Action */}
      <View style={{ marginTop: spacing.xl, marginBottom: spacing['3xl'] }}>
        <ListItem
          title={t('auth.logout')}
          leftIcon={<Ionicons name="log-out-outline" size={22} color={colors.error} />}
          showChevron={false}
          onPress={() => setLogoutModalVisible(true)}
          style={{ borderColor: `${colors.error}30`, backgroundColor: colors.errorLight }}
        />
      </View>

      <ConfirmationDialog
        visible={logoutModalVisible}
        title={t('auth.logout')}
        message={t('auth.logoutConfirm')}
        confirmText={t('auth.logout')}
        isDestructive
        onConfirm={handleLogoutConfirm}
        onCancel={() => setLogoutModalVisible(false)}
      />
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  userCard: {
    marginVertical: 8,
    padding: 16,
  },
  userRow: {
    alignItems: 'center',
  },
  userInfoCol: {
    flex: 1,
    paddingHorizontal: 12,
  },
  badgePill: {
    alignSelf: 'flex-start',
    paddingVertical: 3,
    paddingHorizontal: 8,
    borderRadius: 8,
  },
  clinicalCard: {
    padding: 16,
  },
  metricRow: {
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  metricItem: {
    flex: 1,
  },
  divider: {
    height: 1,
    marginVertical: 12,
  },
  metaBlock: {
    alignItems: 'center',
  },
});
