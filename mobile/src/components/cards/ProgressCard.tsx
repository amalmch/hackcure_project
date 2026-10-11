import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { ProgressCircle } from '../ui/ProgressCircle';
import { ProgressBar } from '../ui/ProgressBar';

interface ProgressCardProps {
  medicationTaken: number;
  medicationTotal: number;
  sportCompleted: number;
  sportTotal: number;
}

export const ProgressCard: React.FC<ProgressCardProps> = ({
  medicationTaken,
  medicationTotal,
  sportCompleted,
  sportTotal,
}) => {
  const { colors, typography, spacing } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const medPercent = medicationTotal > 0 ? Math.round((medicationTaken / medicationTotal) * 100) : 0;
  const sportPercent = sportTotal > 0 ? Math.round((sportCompleted / sportTotal) * 100) : 0;

  return (
    <Card style={styles.card}>
      <Text style={[typography.h4, { color: colors.textPrimary, textAlign, marginBottom: spacing.md }]}>
        {t('home.todayProgress')}
      </Text>

      <View style={[styles.mainRow, { flexDirection }]}>
        <View style={styles.circleContainer}>
          <ProgressCircle
            percentage={medPercent}
            size={84}
            color={colors.primary}
            label={t('home.medicationsProgress')}
          />
        </View>

        <View style={styles.detailsColumn}>
          {/* Medications progress */}
          <View style={styles.metricBlock}>
            <View style={[styles.metricHeader, { flexDirection }]}>
              <Text style={[typography.captionBold, { color: colors.textPrimary }]}>
                {t('home.medicationsProgress')}
              </Text>
              <Text style={[typography.caption, { color: colors.primary, fontWeight: '700' }]}>
                {medicationTaken}/{medicationTotal}
              </Text>
            </View>
            <ProgressBar progress={medPercent} color={colors.primary} style={{ marginTop: 4 }} />
          </View>

          {/* Sport progress */}
          <View style={[styles.metricBlock, { marginTop: spacing.md }]}>
            <View style={[styles.metricHeader, { flexDirection }]}>
              <Text style={[typography.captionBold, { color: colors.textPrimary }]}>
                {t('home.sportProgress')}
              </Text>
              <Text style={[typography.caption, { color: colors.secondary, fontWeight: '700' }]}>
                {sportCompleted}/{sportTotal}
              </Text>
            </View>
            <ProgressBar progress={sportPercent} color={colors.secondary} style={{ marginTop: 4 }} />
          </View>
        </View>
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 8,
  },
  mainRow: {
    alignItems: 'center',
  },
  circleContainer: {
    paddingHorizontal: 8,
  },
  detailsColumn: {
    flex: 1,
    paddingHorizontal: 12,
  },
  metricBlock: {
    width: '100%',
  },
  metricHeader: {
    justifyContent: 'space-between',
    alignItems: 'center',
  },
});
