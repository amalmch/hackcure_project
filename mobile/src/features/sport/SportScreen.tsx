import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { sportApi } from '../../services/api/sport';
import { patientApi } from '../../services/api/patient';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { SportCard } from '../../components/cards/SportCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

export const SportScreen: React.FC = () => {
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const {
    data: activities,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['todaySport'],
    queryFn: sportApi.getTodayActivities,
  });

  const { data: summary } = useQuery({
    queryKey: ['treatmentSummary'],
    queryFn: patientApi.getTreatmentSummary,
  });

  const sportReco = summary?.sport_recommendations;

  const startMutation = useMutation({
    mutationFn: (id: string) => sportApi.startActivity(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['todaySport'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => sportApi.completeActivity(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['todaySport'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  if (isLoading && !activities) {
    return (
      <ScreenContainer>
        <Header title={t('sport.title')} showBack />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isError && !activities) {
    return (
      <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
        <Header title={t('sport.title')} showBack />
        <ErrorState
          title={t('copy.loadSport')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={t('sport.title')} showBack />

      {/* Doctor Supervised Warning Banner */}
      <View
        style={[
          styles.warningBanner,
          {
            backgroundColor: colors.warningLight,
            borderColor: colors.warning,
            borderRadius: radii.md,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="information-circle" size={20} color={colors.warning} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.caption, { color: colors.warning, flex: 1, textAlign, lineHeight: 18 }]}>
          {t('sport.doctorWarning')}
        </Text>
      </View>

      {/* Medical Disclaimer */}
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
        <Ionicons name="shield-checkmark" size={16} color={colors.textSecondary} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.tiny, { color: colors.textSecondary, flex: 1, textAlign }]}>
          {t('copy.sportNotice')}
        </Text>
      </View>

      {/* Recommendations Extracted from Doctor's Report */}
      {sportReco && (
        <View
          style={[
            styles.recoCard,
            {
              backgroundColor: colors.card,
              borderColor: colors.cardBorder,
              borderRadius: radii.md,
            },
          ]}
        >
          <Text style={[typography.bodyBold, { color: colors.textPrimary, textAlign, marginBottom: 8 }]}>
            {t('copy.doctorAdvice')}
          </Text>

          {sportReco.recommande && sportReco.recommande.length > 0 && (
            <View style={{ marginBottom: 8 }}>
              <Text style={[typography.captionBold, { color: colors.success, textAlign, marginBottom: 4 }]}>
                {t('copy.recommendedActivities')}
              </Text>
              <View style={[styles.badgeWrap, { flexDirection }]}>
                {sportReco.recommande.map((rec, i) => (
                  <View key={i} style={[styles.tag, { backgroundColor: colors.successLight }]}>
                    <Text style={[typography.tiny, { color: colors.success, fontWeight: '600' }]}>
                      ✓ {rec}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}

          {sportReco.a_eviter && sportReco.a_eviter.length > 0 && (
            <View style={{ marginBottom: 8 }}>
              <Text style={[typography.captionBold, { color: colors.error, textAlign, marginBottom: 4 }]}>
                {t('copy.contraindicatedActivities')}
              </Text>
              <View style={[styles.badgeWrap, { flexDirection }]}>
                {sportReco.a_eviter.map((ev, i) => (
                  <View key={i} style={[styles.tag, { backgroundColor: colors.errorLight }]}>
                    <Text style={[typography.tiny, { color: colors.error, fontWeight: '600' }]}>
                      ✕ {ev}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}

          {sportReco.frequence && (
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign, marginTop: 4 }]}>
              {t('copy.prescribedFrequency')} <Text style={{ color: colors.textPrimary, fontWeight: '600' }}>{sportReco.frequence}</Text>
            </Text>
          )}

          {sportReco.restrictions && sportReco.restrictions.length > 0 && (
            <View style={{ marginTop: 6 }}>
              {sportReco.restrictions.map((r, i) => (
                <Text key={i} style={[typography.tiny, { color: colors.warning, marginTop: 2 }]}>
                  ⚠️ {r}
                </Text>
              ))}
            </View>
          )}
        </View>
      )}

      <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginVertical: 8 }]}>
        {t('sport.todayActivity').toUpperCase()}
      </Text>

      {(!activities || activities.length === 0) ? (
        <EmptyState
          icon="walk-outline"
          title={t('sport.noActivitiesToday')}
          description={t('copy.noActivitiesDescription')}
        />
      ) : (
        activities.map((activity) => (
          <View key={activity.id} style={{ marginBottom: spacing.md }}>
            <SportCard
              activity={activity}
              onStart={() => startMutation.mutate(activity.id)}
              onComplete={() => completeMutation.mutate(activity.id)}
              isLoading={startMutation.isPending || completeMutation.isPending}
            />
          </View>
        ))
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  warningBanner: {
    padding: 12,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 8,
  },
  disclaimerBox: {
    padding: 8,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 10,
  },
  recoCard: {
    padding: 12,
    borderWidth: 1,
    marginBottom: 12,
  },
  badgeWrap: {
    flexWrap: 'wrap',
    gap: 6,
  },
  tag: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
});
