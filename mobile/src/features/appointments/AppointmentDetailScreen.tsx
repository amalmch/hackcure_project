import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, StyleSheet, Alert } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { appointmentsApi } from '../../services/api/appointments';
import { AppointmentStatus, AppointmentType } from '../../types';
import { formatDate, formatTime } from '../../utils/dateUtils';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { Card } from '../../components/ui/Card';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { PrimaryButton } from '../../components/ui/PrimaryButton';
import { ConfirmationDialog } from '../../components/ui/ConfirmationDialog';
import { LoadingScreen } from '../../components/ui/LoadingScreen';
import { ErrorState } from '../../components/ui/ErrorState';
import { medicalLabel } from '../../utils/medicalLabels';

export const AppointmentDetailScreen: React.FC = () => {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [confirmModalVisible, setConfirmModalVisible] = useState(false);

  const {
    data: appointment,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['appointment', id],
    queryFn: () => appointmentsApi.getById(id as string),
    enabled: !!id,
  });

  const cancelMutation = useMutation({
    mutationFn: (reason?: string) => appointmentsApi.cancelAppointment(id as string, reason),
    onSuccess: () => {
      setConfirmModalVisible(false);
      queryClient.invalidateQueries({ queryKey: ['appointments'] });
      queryClient.invalidateQueries({ queryKey: ['appointment', id] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      Alert.alert(i18n.t('copy.static_cancellation_requested'), i18n.t('copy.static_your_doctor_s_office_has_been_notified_of_your_c'));
    },
  });

  if (isLoading) return <LoadingScreen />;

  if (isError || !appointment) {
    return (
      <ScreenContainer>
        <Header title={t('appointments.title')} showBack />
        <ErrorState
          title={i18n.t('copy.static_appointment_not_found')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  const doctorName = appointment.doctor
    ? `Dr. ${appointment.doctor.first_name} ${appointment.doctor.last_name}`
    : t('copy.yourDoctor');

  const canCancel = appointment.status === AppointmentStatus.SCHEDULED || appointment.status === AppointmentStatus.CONFIRMED;

  return (
    <ScreenContainer>
      <Header title={i18n.t('copy.static_consultation_details')} showBack />

      <Card style={styles.mainCard}>
        <View style={[styles.headerRow, { flexDirection }]}>
          <Text style={[typography.h3, { color: colors.textPrimary, textAlign }]}>
            {doctorName}
          </Text>
          <StatusBadge
            label={medicalLabel(appointment.status)}
            color={appointment.status === AppointmentStatus.CONFIRMED ? colors.success : colors.warning}
          />
        </View>

        {appointment.doctor?.specialty && (
          <Text style={[typography.captionBold, { color: colors.primary, textAlign, marginTop: 4 }]}>
            {appointment.doctor.specialty}
          </Text>
        )}

        <View style={[styles.divider, { backgroundColor: colors.cardBorder }]} />

        {/* Date & Time */}
        <View style={[styles.infoRow, { flexDirection }]}>
          <Ionicons name="calendar-outline" size={20} color={colors.primary} style={{ marginHorizontal: 8 }} />
          <View style={{ flex: 1 }}>
            <Text style={[typography.caption, { color: colors.textMuted }]}>
              {t('appointments.date')} • {t('appointments.time')}
            </Text>
            <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '700' }]}>
              {formatDate(appointment.appointment_date)} {' '}{i18n.t('copy.static_at')}{' '}{formatTime(appointment.appointment_time)}
            </Text>
          </View>
        </View>

        {/* Type */}
        <View style={[styles.infoRow, { flexDirection, marginTop: spacing.md }]}>
          <Ionicons
            name={appointment.appointment_type === AppointmentType.TELECONSULTATION ? 'videocam-outline' : 'medkit-outline'}
            size={20}
            color={colors.primary}
            style={{ marginHorizontal: 8 }}
          />
          <View style={{ flex: 1 }}>
            <Text style={[typography.caption, { color: colors.textMuted }]}>
              {i18n.t('copy.static_consultation_format')}</Text>
            <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '600' }]}>
              {appointment.appointment_type === AppointmentType.TELECONSULTATION
                ? t('appointments.teleconsultation')
                : t('appointments.inPerson')}
            </Text>
          </View>
        </View>

        {/* Clinic info */}
        {appointment.clinic_name && (
          <View style={[styles.infoRow, { flexDirection, marginTop: spacing.md }]}>
            <Ionicons name="business-outline" size={20} color={colors.primary} style={{ marginHorizontal: 8 }} />
            <View style={{ flex: 1 }}>
              <Text style={[typography.caption, { color: colors.textMuted }]}>
                {i18n.t('copy.static_clinic_location')}</Text>
              <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '600' }]}>
                {appointment.clinic_name}
              </Text>
              {appointment.clinic_address && (
                <Text style={[typography.caption, { color: colors.textSecondary }]}>
                  {appointment.clinic_address}
                </Text>
              )}
            </View>
          </View>
        )}

        {/* Reason */}
        {appointment.reason && (
          <View style={[styles.infoRow, { flexDirection, marginTop: spacing.md }]}>
            <Ionicons name="document-text-outline" size={20} color={colors.primary} style={{ marginHorizontal: 8 }} />
            <View style={{ flex: 1 }}>
              <Text style={[typography.caption, { color: colors.textMuted }]}>
                {i18n.t('copy.static_reason_for_visit')}</Text>
              <Text style={[typography.body, { color: colors.textPrimary }]}>
                {appointment.reason}
              </Text>
            </View>
          </View>
        )}
      </Card>

      {canCancel && (
        <View style={{ marginTop: spacing.xl }}>
          <PrimaryButton
            title={t('appointments.requestCancellation')}
            onPress={() => setConfirmModalVisible(true)}
            variant="danger"
            icon={<Ionicons name="close-circle-outline" size={20} color="#FFFFFF" />}
          />
        </View>
      )}

      <ConfirmationDialog
        visible={confirmModalVisible}
        title={i18n.t('copy.static_cancel_appointment')}
        message={t('appointments.cancelConfirm')}
        confirmText={i18n.t('copy.static_confirm_cancellation')}
        isDestructive
        onConfirm={() => cancelMutation.mutate('Patient requested cancellation')}
        onCancel={() => setConfirmModalVisible(false)}
        loading={cancelMutation.isPending}
      />
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  mainCard: {
    marginVertical: 8,
    padding: 16,
  },
  headerRow: {
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  divider: {
    height: 1,
    marginVertical: 14,
  },
  infoRow: {
    alignItems: 'flex-start',
  },
});
