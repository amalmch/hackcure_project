import React, { useCallback } from 'react';
import { Alert, View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useAuthStore } from '../../store/authStore';
import { useOfflineStore } from '../../store/offlineStore';
import { useGreeting } from '../../hooks/useGreeting';
import { patientApi } from '../../services/api/patient';
import { medicationsApi } from '../../services/api/medications';
import { sportApi } from '../../services/api/sport';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { ProgressCard } from '../../components/cards/ProgressCard';
import { DoseCard } from '../../components/cards/DoseCard';
import { SportCard } from '../../components/cards/SportCard';
import { AppointmentCard } from '../../components/cards/AppointmentCard';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';
import { SectionHeader } from '../../components/ui/SectionHeader';

export const HomeScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();
  const greeting = useGreeting();
  const queryClient = useQueryClient();

  const user = useAuthStore((state) => state.user);
  const patient = useAuthStore((state) => state.patient);
  const isOnline = useOfflineStore((state) => state.isOnline);
  const queueDoseTake = useOfflineStore((state) => state.queueDoseTake);

  const patientName = patient?.first_name || user?.email?.split('@')[0] || t('copy.patient');

  // Fetch Dashboard
  const {
    data: dashboard,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['dashboard'],
    queryFn: patientApi.getDashboard,
    staleTime: 30000,
  });

  // Dose Take Mutation
  const takeDoseMutation = useMutation({
    mutationFn: async (doseId: string) => {
      const idempotencyKey = doseId;
      if (!isOnline) {
        await queueDoseTake(doseId, idempotencyKey);
        return { id: doseId, status: 'TAKEN_ON_TIME' };
      }
      return await medicationsApi.takeDose(doseId, idempotencyKey);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['todayDoses'] });
      queryClient.invalidateQueries({ queryKey: ['adherence'] });
    },
    onError: () => Alert.alert(t('common.error'), t('medications.takeDoseError')),
  });

  const completeSportMutation = useMutation({
    mutationFn: (activityId: string) => sportApi.completeActivity(activityId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['todaySportActivities'] });
    },
    onError: () => Alert.alert(t('common.error'), t('sport.completeActivityError')),
  });

  const handleTakeDose = useCallback(
    (doseId: string) => {
      takeDoseMutation.mutate(doseId);
    },
    [takeDoseMutation]
  );

  const quickActions = [
    {
      id: 'treatment',
      title: t('home.myTreatment'),
      icon: 'medkit' as const,
      color: colors.primary,
      bg: colors.primaryLight,
      route: '/(tabs)/treatment',
    },
    {
      id: 'sport',
      title: t('home.sport'),
      icon: 'walk' as const,
      color: colors.secondary,
      bg: colors.secondaryLight,
      route: '/treatment/sport',
    },
    {
      id: 'nutrition',
      title: t('home.nutrition'),
      icon: 'nutrition' as const,
      color: '#EA580C',
      bg: '#FFEDD5',
      route: '/treatment/nutrition',
    },
    {
      id: 'pharmacy',
      title: t('home.pharmacy'),
      icon: 'business' as const,
      color: colors.success,
      bg: colors.successLight,
      route: '/(tabs)/pharmacy',
    },
    {
      id: 'doctor',
      title: t('home.myDoctor'),
      icon: 'person' as const,
      color: colors.accent,
      bg: '#EEF2FF',
      route: '/(tabs)/doctor',
    },
    {
      id: 'appointments',
      title: t('home.appointments'),
      icon: 'calendar' as const,
      color: colors.warning,
      bg: colors.warningLight,
      route: '/appointment/list',
    },
    {
      id: 'medical-records',
      title: t('home.medicalRecords'),
      icon: 'folder-open-outline' as const,
      color: colors.primary,
      bg: colors.primaryLight,
      route: '/medical-records',
      tunisian: true,
    },
  ];

  if (isLoading && !dashboard) {
    return (
      <ScreenContainer>
        <View style={{ marginVertical: spacing.lg }}>
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </View>
      </ScreenContainer>
    );
  }

  if (isError && !dashboard) {
    return (
      <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
        <ErrorState
          title={t('copy.loadDashboard')}
          message={t('copy.backendRefresh')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  const medProgress = dashboard?.medication_progress || { taken: 0, total: 0 };
  const sportProgress = dashboard?.sport_progress || { completed: 0, total: 0 };

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      {/* Header Greeting */}
      <View style={[styles.headerContainer, { marginTop: spacing.base }]}>
        <View style={[styles.greetingRow, { flexDirection }]}>
          <View style={{ flex: 1 }}>
            <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign }]}>
              {greeting}
            </Text>
            <Text style={[typography.h2, { color: colors.textPrimary, textAlign }]}>
              {patientName}
            </Text>
          </View>

          <TouchableOpacity
            activeOpacity={0.7}
            onPress={() => router.push('/notifications')}
            style={[styles.notifButton, { backgroundColor: colors.surface, borderColor: colors.cardBorder }]}
          >
            <Ionicons name="notifications-outline" size={22} color={colors.textPrimary} />
            {(dashboard?.unread_notifications_count || 0) > 0 && (
              <View style={[styles.badgeDot, { backgroundColor: colors.error }]} />
            )}
          </TouchableOpacity>
        </View>

        {/* Source of Truth Banner */}
        <View style={[styles.truthBanner, { backgroundColor: colors.primaryLight, borderRadius: radii.lg, flexDirection }]}>
          <Ionicons name="shield-checkmark" size={18} color={colors.primary} style={{ marginHorizontal: 6 }} />
          <Text style={[typography.captionBold, { color: colors.primary, flex: 1, textAlign }]}>
            {t('home.sourceOfTruthBanner')}
          </Text>
        </View>
      </View>

      {/* Progress Card */}
      <ProgressCard
        medicationTaken={medProgress.taken}
        medicationTotal={medProgress.total}
        sportCompleted={sportProgress.completed}
        sportTotal={sportProgress.total}
      />

      {/* Quick Action Grid */}
      <View style={[styles.grid, { flexDirection, flexWrap: 'wrap' }]}>
        {quickActions.map((action) => (
          <TouchableOpacity
            key={action.id}
            activeOpacity={0.7}
            onPress={() => router.push(action.route as any)}
            accessibilityRole="button"
            accessibilityLabel={action.tunisian ? t('copy.countryFlagLabel', { title: action.title }) : action.title}
            style={[
              styles.gridItem,
              {
                backgroundColor: colors.card,
                borderColor: colors.cardBorder,
                borderRadius: radii.xl,
              },
            ]}
          >
            <View style={[styles.actionIconWrapper, { backgroundColor: action.bg, borderRadius: radii.lg }]}>
              <Ionicons name={action.icon} size={22} color={action.color} />
              {action.tunisian && (
                <Text accessible={false} style={styles.countryFlag}>
                  🇹🇳
                </Text>
              )}
            </View>
            <Text style={[typography.captionBold, { color: colors.textPrimary, textAlign, marginTop: 8 }]}>
              {action.title}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Today's doses: each check-in is saved through the patient-scoped medication API. */}
      {(dashboard?.today_doses?.length || 0) > 0 && (
        <View style={{ marginTop: spacing.base }}>
          <SectionHeader
            title={t('medications.todayDoses')}
            actionTitle={t('common.viewAll')}
            onAction={() => router.push('/(tabs)/treatment')}
          />
          {dashboard?.today_doses.map((dose) => (
            <DoseCard key={dose.id} dose={dose} onTakeDose={handleTakeDose} isLoading={takeDoseMutation.isPending} />
          ))}
        </View>
      )}

      {(dashboard?.today_sport_activities?.length || 0) > 0 && (
        <View style={{ marginTop: spacing.base }}>
          <SectionHeader title={t('home.sportProgress')} actionTitle={t('common.viewAll')} onAction={() => router.push('/treatment/sport')} />
          {dashboard?.today_sport_activities.map((activity) => (
            <SportCard
              key={activity.id}
              activity={activity}
              onStart={() => router.push('/treatment/sport')}
              onComplete={(id) => completeSportMutation.mutate(id)}
              isLoading={completeSportMutation.isPending}
              allowDirectCompletion
            />
          ))}
        </View>
      )}

      {/* Next Appointment Section */}
      {dashboard?.next_appointment && (
        <View style={{ marginTop: spacing.base }}>
          <SectionHeader
            title={t('home.nextAppointment')}
            actionTitle={t('common.viewAll')}
            onAction={() => router.push('/appointment/list')}
          />
          <AppointmentCard
            appointment={dashboard.next_appointment}
            onPress={() => router.push(`/appointment/${dashboard.next_appointment?.id}` as any)}
          />
        </View>
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  headerContainer: {
    marginBottom: 12,
  },
  greetingRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  notifButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    position: 'relative',
  },
  badgeDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    position: 'absolute',
    top: 10,
    right: 10,
  },
  truthBanner: {
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginTop: 12,
  },
  grid: {
    marginVertical: 10,
    gap: 10,
  },
  gridItem: {
    width: '31%',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    paddingHorizontal: 8,
    borderWidth: 1,
  },
  actionIconWrapper: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  countryFlag: {
    position: 'absolute',
    top: -7,
    right: -10,
    fontSize: 13,
    overflow: 'hidden',
  },
});
