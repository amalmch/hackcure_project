import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { prescriptionsApi } from '../../services/api/prescriptions';
import { formatDate } from '../../utils/dateUtils';
import { medicalLabel } from '../../utils/medicalLabels';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { Card } from '../../components/ui/Card';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { PrimaryButton } from '../../components/ui/PrimaryButton';
import { MedicationCard } from '../../components/cards/MedicationCard';
import { LoadingScreen } from '../../components/ui/LoadingScreen';
import { ErrorState } from '../../components/ui/ErrorState';

export const PrescriptionDetailScreen: React.FC = () => {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const {
    data: prescription,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['prescription', id],
    queryFn: () => prescriptionsApi.getPrescriptionById(id as string),
    enabled: !!id,
  });

  if (isLoading) return <LoadingScreen />;

  if (isError || !prescription) {
    return (
      <ScreenContainer>
        <Header title={t('prescription.title')} showBack />
        <ErrorState
          title={i18n.t('copy.static_prescription_not_found')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  const doctorName = prescription.doctor
    ? `Dr. ${prescription.doctor.first_name} ${prescription.doctor.last_name}`
    : t('copy.prescribingDoctor');

  return (
    <ScreenContainer>
      <Header title={t('prescription.title')} showBack />

      {/* Source of Truth Protection Banner */}
      <View
        style={[
          styles.lockBanner,
          {
            backgroundColor: colors.primaryLight,
            borderColor: colors.primary,
            borderRadius: radii.lg,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="lock-closed" size={20} color={colors.primary} style={{ marginHorizontal: 6 }} />
        <View style={{ flex: 1 }}>
          <Text style={[typography.captionBold, { color: colors.primary, textAlign }]}>
            {i18n.t('copy.static_medical_source_of_truth')}</Text>
          <Text style={[typography.tiny, { color: colors.primary, textAlign, marginTop: 2, lineHeight: 16 }]}>
            {t('treatment.cannotModifyNotice')}
          </Text>
        </View>
      </View>

      {/* Prescription Meta Card */}
      <Card style={styles.card}>
        <View style={[styles.headerRow, { flexDirection }]}>
          <View style={{ flex: 1 }}>
            <Text style={[typography.h3, { color: colors.textPrimary, textAlign }]}>
              {prescription.prescription_number || `Prescription #${prescription.id.slice(0, 8)}`}
            </Text>
            <Text style={[typography.captionBold, { color: colors.primary, textAlign, marginTop: 2 }]}>
              {doctorName}
            </Text>
          </View>

          <StatusBadge
            label={medicalLabel(prescription.status)}
            color={colors.success}
          />
        </View>

        <View style={[styles.divider, { backgroundColor: colors.cardBorder }]} />

        {/* Diagnosis */}
        {prescription.diagnosis && (
          <View style={{ marginVertical: 4 }}>
            <Text style={[typography.caption, { color: colors.textMuted }]}>
              {i18n.t('copy.static_clinical_diagnosis')}</Text>
            <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '600', marginTop: 2 }]}>
              {prescription.diagnosis}
            </Text>
          </View>
        )}

        {/* Date validity */}
        <View style={[styles.dateRow, { flexDirection, marginTop: spacing.sm }]}>
          <Ionicons name="calendar-outline" size={16} color={colors.textMuted} style={{ marginHorizontal: 4 }} />
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {i18n.t('copy.static_valid')}{' '}{formatDate(prescription.start_date)}
            {prescription.end_date ? ` to ${formatDate(prescription.end_date)}` : ' (Ongoing)'}
          </Text>
        </View>

        {/* Notes */}
        {prescription.notes && (
          <View style={[styles.notesBox, { backgroundColor: colors.inputBg, borderRadius: radii.md, marginTop: spacing.md }]}>
            <Text style={[typography.captionBold, { color: colors.textSecondary, marginBottom: 2 }]}>
              {i18n.t('copy.static_doctor_instructions')}</Text>
            <Text style={[typography.caption, { color: colors.textPrimary, lineHeight: 20 }]}>
              {prescription.notes}
            </Text>
          </View>
        )}
      </Card>

      {/* Prescribed Medications */}
      <View style={{ marginTop: spacing.lg }}>
        <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
          {t('copy.prescribedMedicines')}{prescription.items?.length || 0})
        </Text>

        {prescription.items?.map((item) => (
          <MedicationCard
            key={item.id}
            medication={item}
            onPress={() => router.push(`/treatment/medication/${item.id}` as any)}
          />
        ))}
      </View>

      {/* Contact Doctor button */}
      <View style={{ marginTop: spacing.xl, marginBottom: spacing['2xl'] }}>
        <PrimaryButton
          title={i18n.t('copy.static_contact_prescribing_doctor')}
          onPress={() => router.push('/(tabs)/doctor')}
          icon={<Ionicons name="chatbubble-ellipses-outline" size={20} color="#FFFFFF" />}
        />
      </View>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  lockBanner: {
    borderWidth: 1,
    padding: 12,
    alignItems: 'center',
    marginVertical: 8,
  },
  card: {
    marginVertical: 6,
    padding: 16,
  },
  headerRow: {
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  divider: {
    height: 1,
    marginVertical: 12,
  },
  dateRow: {
    alignItems: 'center',
  },
  notesBox: {
    padding: 10,
  },
});
