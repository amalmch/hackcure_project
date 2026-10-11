import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { MedicationDose, DoseStatus } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { StatusBadge } from '../ui/StatusBadge';
import { PrimaryButton } from '../ui/PrimaryButton';
import { getDoseStatusColor, getDoseStatusBgColor } from '../../utils/doseUtils';
import { formatDate, formatTime } from '../../utils/dateUtils';

interface DoseCardProps {
  dose: MedicationDose;
  onTakeDose: (doseId: string) => void;
  isLoading?: boolean;
}

export const DoseCard: React.FC<DoseCardProps> = ({
  dose,
  onTakeDose,
  isLoading = false,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const isActionable =
    dose.status === DoseStatus.SCHEDULED ||
    dose.status === DoseStatus.DUE ||
    dose.status === DoseStatus.REMINDING;

  const statusColor = getDoseStatusColor(dose.status);
  const statusBg = getDoseStatusBgColor(dose.status);

  const getStatusLabel = () => {
    switch (dose.status) {
      case DoseStatus.TAKEN_ON_TIME:
        return t('medications.taken');
      case DoseStatus.TAKEN_LATE:
        return t('medications.takenLate');
      case DoseStatus.MISSED:
        return t('medications.missed');
      case DoseStatus.DUE:
        return t('medications.due');
      case DoseStatus.REMINDING:
        return t('medications.reminding');
      default:
        return t('medications.scheduled');
    }
  };

  const medName = dose.prescription_item?.medication_name || 'Prescribed Medicine';
  const dosage = dose.prescription_item?.dosage || '';
  const beforeFood = dose.prescription_item?.before_food;

  return (
    <Card style={styles.card}>
      <View style={[styles.topRow, { flexDirection }]}>
        <View style={[styles.timeBox, { backgroundColor: colors.inputBg, borderRadius: radii.md }]}>
          <Ionicons name="time-outline" size={16} color={colors.primary} />
          <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '700', marginHorizontal: 4 }]}>
            {formatDate(dose.scheduled_date)} · {formatTime(dose.scheduled_time)}
          </Text>
        </View>

        <StatusBadge
          label={getStatusLabel()}
          color={statusColor}
          bgColor={statusBg}
        />
      </View>

      <View style={[styles.bodyRow, { flexDirection, marginTop: spacing.md }]}>
        <View
          style={[
            styles.medIconWrapper,
            { backgroundColor: colors.primaryLight, borderRadius: radii.lg },
          ]}
        >
          <Ionicons name="medkit-outline" size={24} color={colors.primary} />
        </View>

        <View style={styles.contentColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {medName}
          </Text>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign }]}>
            {dosage}
          </Text>
          {beforeFood !== undefined && (
            <Text style={[typography.tiny, { color: colors.textMuted, textAlign, marginTop: 2 }]}>
              {beforeFood ? t('medications.beforeFood') : t('medications.afterFood')}
            </Text>
          )}
        </View>
      </View>

      {dose.taken_at && (
        <View style={[styles.takenAtRow, { flexDirection, marginTop: spacing.sm }]}>
          <Ionicons name="checkmark-done" size={16} color={colors.success} style={{ marginHorizontal: 4 }} />
          <Text style={[typography.tiny, { color: colors.success }]}>
            {i18n.t('copy.static_recorded')}{' '}{formatTime(dose.taken_at)}
          </Text>
        </View>
      )}

      {isActionable && (
        <View style={{ marginTop: spacing.base }}>
          <PrimaryButton
            title={t('medications.iTookIt')}
            onPress={() => onTakeDose(dose.id)}
            loading={isLoading}
            variant="success"
            icon={<Ionicons name="checkmark-circle-outline" size={20} color="#FFFFFF" />}
            style={styles.actionBtn}
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
  topRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  timeBox: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  bodyRow: {
    alignItems: 'center',
  },
  medIconWrapper: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 8,
  },
  contentColumn: {
    flex: 1,
    paddingHorizontal: 4,
  },
  takenAtRow: {
    alignItems: 'center',
  },
  actionBtn: {
    width: '100%',
  },
});
