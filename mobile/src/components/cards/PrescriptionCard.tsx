import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { Prescription, PrescriptionStatus } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { StatusBadge } from '../ui/StatusBadge';
import { formatDate } from '../../utils/dateUtils';
import { medicalLabel } from '../../utils/medicalLabels';

interface PrescriptionCardProps {
  prescription: Prescription;
  onPress?: () => void;
}

export const PrescriptionCard: React.FC<PrescriptionCardProps> = ({
  prescription,
  onPress,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const doctorName = prescription.doctor
    ? `Dr. ${prescription.doctor.first_name} ${prescription.doctor.last_name}`
    : t('copy.prescribingDoctor');

  const itemsCount = prescription.items?.length || 0;

  return (
    <Card onPress={onPress} style={styles.card}>
      <View style={[styles.headerRow, { flexDirection }]}>
        <View style={styles.titleColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {prescription.prescription_number || t('treatment.prescriptionNumber', { number: prescription.id.slice(0, 8) })}
          </Text>
          <Text style={[typography.captionBold, { color: colors.primary, textAlign, marginTop: 2 }]}>
            {doctorName}
          </Text>
        </View>

        <StatusBadge
          label={medicalLabel(prescription.status)}
          color={prescription.status === PrescriptionStatus.ACTIVE ? colors.success : colors.textMuted}
        />
      </View>

      {prescription.diagnosis && (
        <View style={[styles.diagnosisBox, { backgroundColor: colors.inputBg, borderRadius: radii.md, marginTop: spacing.md }]}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign }]}>
            {i18n.t('copy.static_diagnosis')}{' '}{prescription.diagnosis}
          </Text>
        </View>
      )}

      <View style={[styles.metaRow, { flexDirection, marginTop: spacing.md }]}>
        <View style={[styles.metaItem, { flexDirection }]}>
          <Ionicons name="medical-outline" size={16} color={colors.textMuted} style={{ marginHorizontal: 4 }} />
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {t('treatment.medicationsCount', { count: itemsCount })}
          </Text>
        </View>

        <View style={[styles.metaItem, { flexDirection }]}>
          <Ionicons name="calendar-outline" size={16} color={colors.textMuted} style={{ marginHorizontal: 4 }} />
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {formatDate(prescription.start_date)}
            {prescription.end_date ? ` - ${formatDate(prescription.end_date)}` : ''}
          </Text>
        </View>
      </View>

      {/* Safety Notice */}
      <View style={[styles.safetyNotice, { backgroundColor: colors.primaryLight, borderRadius: radii.md, marginTop: spacing.sm }]}>
        <Ionicons name="lock-closed-outline" size={14} color={colors.primary} style={{ marginHorizontal: 4 }} />
        <Text style={[typography.tiny, { color: colors.primary, flex: 1, textAlign }]}>
          {i18n.t('copy.static_doctor_s_care_plan_source_of_truth')}</Text>
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 6,
  },
  headerRow: {
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  titleColumn: {
    flex: 1,
    paddingHorizontal: 2,
  },
  diagnosisBox: {
    padding: 8,
  },
  metaRow: {
    alignItems: 'center',
    gap: 16,
  },
  metaItem: {
    alignItems: 'center',
  },
  safetyNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 6,
  },
});
