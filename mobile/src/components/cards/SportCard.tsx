import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { SportActivity, SportActivityStatus, Intensity } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { StatusBadge } from '../ui/StatusBadge';
import { PrimaryButton } from '../ui/PrimaryButton';

interface SportCardProps {
  activity: SportActivity;
  onStart: (id: string) => void;
  onComplete: (id: string) => void;
  isLoading?: boolean;
  allowDirectCompletion?: boolean;
}

export const SportCard: React.FC<SportCardProps> = ({
  activity,
  onStart,
  onComplete,
  isLoading = false,
  allowDirectCompletion = false,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const plan = activity.sport_plan;
  const activityName = plan?.activity_name || 'Prescribed Physical Activity';
  const duration = plan?.duration_minutes || 30;
  const intensity = plan?.intensity || Intensity.MODERATE;
  const instructions = plan?.instructions;

  const getStatusColor = () => {
    switch (activity.status) {
      case SportActivityStatus.COMPLETED:
        return colors.success;
      case SportActivityStatus.IN_PROGRESS:
        return colors.primary;
      case SportActivityStatus.MISSED:
        return colors.error;
      default:
        return colors.warning;
    }
  };

  const getStatusLabel = () => {
    switch (activity.status) {
      case SportActivityStatus.COMPLETED:
        return t('sport.completed');
      case SportActivityStatus.IN_PROGRESS:
        return t('sport.inProgress');
      default:
        return t('medications.scheduled');
    }
  };

  const getIntensityBadgeColor = () => {
    if (intensity === Intensity.LIGHT) return colors.success;
    if (intensity === Intensity.VIGOROUS) return colors.error;
    return colors.warning;
  };

  return (
    <Card style={styles.card}>
      <View style={[styles.headerRow, { flexDirection }]}>
        <View
          style={[
            styles.iconWrapper,
            { backgroundColor: colors.primaryLight, borderRadius: radii.lg },
          ]}
        >
          <Ionicons name="walk-outline" size={24} color={colors.primary} />
        </View>

        <View style={styles.titleColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {activityName}
          </Text>
          <Text style={[typography.caption, { color: colors.secondary, textAlign, fontWeight: '600' }]}>
            {t('sport.prescribedByDoctor')}
          </Text>
        </View>

        <StatusBadge
          label={getStatusLabel()}
          color={getStatusColor()}
        />
      </View>

      <View style={[styles.metaRow, { flexDirection, marginTop: spacing.md }]}>
        <View
          style={[
            styles.metaBadge,
            { backgroundColor: colors.inputBg, borderRadius: radii.md },
          ]}
        >
          <Ionicons name="timer-outline" size={16} color={colors.textSecondary} />
          <Text style={[typography.captionBold, { color: colors.textPrimary, marginHorizontal: 4 }]}>
            {duration} min
          </Text>
        </View>

        <View
          style={[
            styles.metaBadge,
            { backgroundColor: `${getIntensityBadgeColor()}15`, borderRadius: radii.md },
          ]}
        >
          <Text style={[typography.captionBold, { color: getIntensityBadgeColor() }]}>
            {intensity}
          </Text>
        </View>
      </View>

      {instructions && (
        <View
          style={[
            styles.instructionsBox,
            {
              backgroundColor: colors.inputBg,
              borderRadius: radii.md,
              marginTop: spacing.sm,
            },
          ]}
        >
          <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
            {instructions}
          </Text>
        </View>
      )}

      {activity.status === SportActivityStatus.SCHEDULED && (
        <View style={{ marginTop: spacing.base }}>
          <PrimaryButton
            title={t('sport.startActivity')}
            onPress={() => onStart(activity.id)}
            loading={isLoading}
            icon={<Ionicons name="play" size={18} color="#FFFFFF" />}
          />
        </View>
      )}

      {(activity.status === SportActivityStatus.IN_PROGRESS || (allowDirectCompletion && activity.status === SportActivityStatus.SCHEDULED)) && (
        <View style={{ marginTop: spacing.base }}>
          <PrimaryButton
            title={t('sport.completeActivity')}
            onPress={() => onComplete(activity.id)}
            loading={isLoading}
            variant="success"
            icon={<Ionicons name="checkmark-done" size={20} color="#FFFFFF" />}
          />
        </View>
      )}
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 6,
  },
  headerRow: {
    alignItems: 'center',
  },
  iconWrapper: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 8,
  },
  titleColumn: {
    flex: 1,
    paddingHorizontal: 4,
  },
  metaRow: {
    gap: 8,
  },
  metaBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  instructionsBox: {
    padding: 10,
  },
});
