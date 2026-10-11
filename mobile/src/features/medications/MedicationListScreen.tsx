import i18n from '../../i18n';
import React, { useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useOfflineStore } from '../../store/offlineStore';
import { medicationsApi } from '../../services/api/medications';
import { groupDosesByTimeOfDay } from '../../utils/doseUtils';
import { useNotifications } from '../../hooks/useNotifications';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { DoseCard } from '../../components/cards/DoseCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';
import { useSettingsStore } from '../../store/settingsStore';

export const MedicationListScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { cancelDoseEscalation, rebuildAllDoseReminders } = useNotifications();
  const notificationsEnabled = useSettingsStore((state) => state.notificationsEnabled);

  const isOnline = useOfflineStore((state) => state.isOnline);
  const queueDoseTake = useOfflineStore((state) => state.queueDoseTake);

  const {
    data: doses,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['todayDoses'],
    queryFn: medicationsApi.getTodayDoses,
  });

  useEffect(() => {
    if (!doses) return;
    void rebuildAllDoseReminders(notificationsEnabled ? doses : []);
  }, [doses, notificationsEnabled, rebuildAllDoseReminders]);

  const takeDoseMutation = useMutation({
    mutationFn: async (doseId: string) => {
      if (!isOnline) {
        await queueDoseTake(doseId, doseId);
        await cancelDoseEscalation(doseId);
        return { id: doseId, status: 'TAKEN_ON_TIME' };
      }
      const updatedDose = await medicationsApi.takeDose(doseId, doseId);
      await cancelDoseEscalation(doseId);
      return updatedDose;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['todayDoses'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['adherence'] });
      queryClient.invalidateQueries({ queryKey: ['doseHistory'] });
    },
  });

  const handleTakeDose = useCallback(
    (doseId: string) => {
      takeDoseMutation.mutate(doseId);
    },
    [takeDoseMutation]
  );

  if (isLoading && !doses) {
    return (
      <ScreenContainer>
        <Header title={t('medications.title')} showBack />
        <CardSkeleton />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isError && !doses) {
    return (
      <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
        <Header title={t('medications.title')} showBack />
        <ErrorState
          title={i18n.t('copy.static_could_not_load_medication_schedule')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  const grouped = groupDosesByTimeOfDay(doses || []);

  const sections = [
    { key: 'morning', label: t('medications.morning'), items: grouped.morning },
    { key: 'afternoon', label: t('medications.afternoon'), items: grouped.afternoon },
    { key: 'evening', label: t('medications.evening'), items: grouped.evening },
    { key: 'night', label: t('medications.night'), items: grouped.night },
  ];

  const totalDoses = doses?.length || 0;

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={t('medications.title')} showBack />

      <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: spacing.sm }]}>
        {t('medications.scheduleControlled')}
      </Text>
      {Platform.OS === 'web' && (
        <Text accessibilityRole="alert" style={[typography.caption, { color: colors.warning, marginBottom: spacing.sm }]}>
          {t('medications.webReminderLimit')}
        </Text>
      )}

      {/* Missed dose warning box */}
      <View style={[styles.warningBox, { backgroundColor: colors.warningLight, borderColor: colors.warning }]}>
        <Text style={[typography.caption, { color: colors.warning, textAlign, lineHeight: 18 }]}>
          ⚠️ {t('medications.missedDoseWarning')}
        </Text>
      </View>
      {takeDoseMutation.isError && (
        <Text accessibilityRole="alert" style={[typography.caption, { color: colors.error, marginBottom: spacing.sm }]}>
          {t('medications.takeDoseError')}
        </Text>
      )}

      {/* History Button CTA */}
      <TouchableOpacity
        onPress={() => router.push('/treatment/history')}
        style={[
          styles.historyButton,
          {
            backgroundColor: colors.card,
            borderColor: colors.cardBorder,
            borderRadius: radii.md,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="time-outline" size={20} color={colors.primary} style={{ marginHorizontal: 8 }} />
        <View style={{ flex: 1 }}>
          <Text style={[typography.bodyBold, { color: colors.textPrimary, textAlign }]}>
            {i18n.t('copy.static_historique_suivi_des_prises')}</Text>
          <Text style={[typography.tiny, { color: colors.textSecondary, textAlign }]}>
            {i18n.t('copy.static_consultez_les_prises_confirmees_avec_horodatage_')}</Text>
        </View>
        <Ionicons name="chevron-forward" size={18} color={colors.textSecondary} />
      </TouchableOpacity>

      {/* Medical disclaimer */}
      <View
        style={[
          styles.disclaimerBox,
          {
            backgroundColor: colors.inputBg,
            borderColor: colors.cardBorder,
            borderRadius: radii.md,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="information-circle-outline" size={16} color={colors.textSecondary} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.tiny, { color: colors.textSecondary, flex: 1, textAlign }]}>
          {i18n.t('copy.static_cette_application_ne_remplace_pas_l_avis_de_votr')}</Text>
      </View>

      {totalDoses === 0 ? (
        <EmptyState
          icon="medkit-outline"
          title={i18n.t('copy.static_no_doses_scheduled_for_today')}
          description={i18n.t('copy.static_your_doctor_has_not_scheduled_any_medication_dos')}
        />
      ) : (
        sections.map((sec) => {
          if (sec.items.length === 0) return null;
          return (
            <View key={sec.key} style={{ marginTop: spacing.md }}>
              <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 4 }]}>
                {sec.label.toUpperCase()}
              </Text>
              {sec.items.map((dose) => (
                <DoseCard
                  key={dose.id}
                  dose={dose}
                  onTakeDose={handleTakeDose}
                  isLoading={takeDoseMutation.isPending && takeDoseMutation.variables === dose.id}
                />
              ))}
            </View>
          );
        })
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  warningBox: {
    padding: 12,
    borderWidth: 1,
    borderRadius: 12,
    marginBottom: 8,
  },
  historyButton: {
    padding: 12,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 8,
  },
  disclaimerBox: {
    padding: 8,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 8,
  },
});
