import React, { useCallback } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { adherenceApi } from '../../services/api/adherence';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { Card } from '../../components/ui/Card';
import { ProgressCircle } from '../../components/ui/ProgressCircle';
import { ProgressBar } from '../../components/ui/ProgressBar';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';
import { useFocusEffect } from 'expo-router';

export const AdherenceScreen: React.FC = () => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const {
    data: stats,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['adherence'],
    queryFn: adherenceApi.getStats,
  });

  useFocusEffect(useCallback(() => {
    void refetch();
  }, [refetch]));

  if (isLoading && !stats) {
    return (
      <ScreenContainer>
        <Header title={t('adherence.title')} showBack />
        <CardSkeleton />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isError && !stats) {
    return (
      <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
        <Header title={t('adherence.title')} showBack />
        <ErrorState
          title={t('copy.loadAdherence')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  const weekly = stats?.weekly || { total: 0, taken_on_time: 0, taken_late: 0, missed: 0, percentage: 100, daily_breakdown: [] };
  const daily = stats?.daily || { total: 0, taken_on_time: 0, taken_late: 0, missed: 0, pending: 0, percentage: 100 };

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={t('adherence.title')} showBack />

      {/* Main Weekly Adherence Ring */}
      <Card style={styles.mainCard}>
        <Text style={[typography.h4, { color: colors.textPrimary, textAlign, marginBottom: spacing.md }]}>
          {t('adherence.weeklyAdherence')}
        </Text>

        <View style={[styles.ringRow, { flexDirection }]}>
          <ProgressCircle
            percentage={weekly.percentage}
            size={110}
            strokeWidth={10}
            color={weekly.percentage >= 80 ? colors.success : colors.warning}
            label={t('adherence.overallAdherence')}
          />

          <View style={styles.statsSummaryCol}>
            <View style={[styles.statRow, { flexDirection }]}>
              <View style={[styles.bullet, { backgroundColor: colors.success }]} />
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {t('adherence.dosesTakenOnTime')} :{' '}
              </Text>
              <Text style={[typography.captionBold, { color: colors.textPrimary }]}>
                {weekly.taken_on_time}
              </Text>
            </View>

            <View style={[styles.statRow, { flexDirection, marginTop: 6 }]}>
              <View style={[styles.bullet, { backgroundColor: colors.warning }]} />
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {t('adherence.dosesTakenLate')} :{' '}
              </Text>
              <Text style={[typography.captionBold, { color: colors.textPrimary }]}>
                {weekly.taken_late}
              </Text>
            </View>

            <View style={[styles.statRow, { flexDirection, marginTop: 6 }]}>
              <View style={[styles.bullet, { backgroundColor: colors.error }]} />
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {t('adherence.dosesMissed')} :{' '}
              </Text>
              <Text style={[typography.captionBold, { color: colors.textPrimary }]}>
                {weekly.missed}
              </Text>
            </View>
          </View>
        </View>

        <Text style={[typography.tiny, { color: colors.textMuted, textAlign, marginTop: spacing.md }]}>
          {t('adherence.adherenceDescription')}
        </Text>
      </Card>

      {/* Today Breakdown */}
      <View style={{ marginTop: spacing.base }}>
        <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
          {t('copy.intakeDetails')}
        </Text>

        <Card>
          <View style={[styles.metricGrid, { flexDirection }]}>
            <View style={[styles.gridCell, { backgroundColor: colors.successLight, borderRadius: radii.lg }]}>
              <Text style={[typography.h3, { color: colors.success }]}>{daily.taken_on_time}</Text>
              <Text style={[typography.tiny, { color: colors.success, fontWeight: '700' }]}>{t('copy.onTime')}</Text>
            </View>

            <View style={[styles.gridCell, { backgroundColor: colors.warningLight, borderRadius: radii.lg }]}>
              <Text style={[typography.h3, { color: colors.warning }]}>{daily.taken_late}</Text>
              <Text style={[typography.tiny, { color: colors.warning, fontWeight: '700' }]}>{t('copy.late')}</Text>
            </View>

            <View style={[styles.gridCell, { backgroundColor: colors.errorLight, borderRadius: radii.lg }]}>
              <Text style={[typography.h3, { color: colors.error }]}>{daily.missed}</Text>
              <Text style={[typography.tiny, { color: colors.error, fontWeight: '700' }]}>{t('copy.missed')}</Text>
            </View>

            <View style={[styles.gridCell, { backgroundColor: colors.inputBg, borderRadius: radii.lg }]}>
              <Text style={[typography.h3, { color: colors.textSecondary }]}>{daily.pending}</Text>
              <Text style={[typography.tiny, { color: colors.textMuted, fontWeight: '700' }]}>{t('copy.pending')}</Text>
            </View>
          </View>
        </Card>
      </View>

      {/* Daily Breakdown for Past 7 Days */}
      {weekly.daily_breakdown && weekly.daily_breakdown.length > 0 && (
        <View style={{ marginTop: spacing.base }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
            {t('adherence.weeklyTrend').toUpperCase()}
          </Text>

          <Card>
            {weekly.daily_breakdown.map((item, idx) => (
              <View key={idx} style={{ marginVertical: 6 }}>
                <View style={[styles.barHeader, { flexDirection }]}>
                  <Text style={[typography.captionBold, { color: colors.textPrimary }]}>
                    {item.date}
                  </Text>
                  <Text style={[typography.captionBold, { color: colors.primary }]}>
                    {item.taken}/{item.total} {t('copy.doses')} ({item.percentage} %)
                  </Text>
                </View>
                <ProgressBar
                  progress={item.percentage}
                  color={item.percentage >= 80 ? colors.success : colors.warning}
                  style={{ marginTop: 4 }}
                />
              </View>
            ))}
          </Card>
        </View>
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  mainCard: {
    marginVertical: 6,
  },
  ringRow: {
    alignItems: 'center',
    justifyContent: 'space-around',
  },
  statsSummaryCol: {
    paddingHorizontal: 12,
  },
  statRow: {
    alignItems: 'center',
  },
  bullet: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginHorizontal: 6,
  },
  metricGrid: {
    gap: 8,
  },
  gridCell: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
  },
  barHeader: {
    justifyContent: 'space-between',
    alignItems: 'center',
  },
});
