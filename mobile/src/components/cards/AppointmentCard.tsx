import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Appointment, AppointmentStatus, AppointmentType } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { StatusBadge } from '../ui/StatusBadge';
import { formatDate, formatTime } from '../../utils/dateUtils';
import { medicalLabel } from '../../utils/medicalLabels';

interface AppointmentCardProps {
  appointment: Appointment;
  onPress?: () => void;
}

export const AppointmentCard: React.FC<AppointmentCardProps> = ({
  appointment,
  onPress,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();

  const getStatusColor = () => {
    switch (appointment.status) {
      case AppointmentStatus.CONFIRMED:
        return colors.success;
      case AppointmentStatus.CANCELLED:
        return colors.error;
      case AppointmentStatus.COMPLETED:
        return colors.primary;
      default:
        return colors.warning;
    }
  };

  const doctorName = appointment.doctor
    ? `Dr. ${appointment.doctor.first_name} ${appointment.doctor.last_name}`
    : 'Your Doctor';

  return (
    <Card onPress={onPress} style={styles.card}>
      <View style={[styles.headerRow, { flexDirection }]}>
        <View style={[styles.dateBadge, { backgroundColor: colors.primaryLight, borderRadius: radii.md }]}>
          <Ionicons name="calendar-outline" size={16} color={colors.primary} />
          <Text style={[typography.captionBold, { color: colors.primary, marginHorizontal: 4 }]}>
            {formatDate(appointment.appointment_date)}
          </Text>
        </View>

        <StatusBadge
          label={medicalLabel(appointment.status)}
          color={getStatusColor()}
        />
      </View>

      <View style={[styles.detailsRow, { flexDirection, marginTop: spacing.md }]}>
        <View
          style={[
            styles.typeIcon,
            { backgroundColor: colors.inputBg, borderRadius: radii.lg },
          ]}
        >
          <Ionicons
            name={
              appointment.appointment_type === AppointmentType.TELECONSULTATION
                ? 'videocam-outline'
                : 'medkit-outline'
            }
            size={22}
            color={colors.primary}
          />
        </View>

        <View style={styles.infoColumn}>
          <Text style={[typography.subtitle, { color: colors.textPrimary, textAlign, fontWeight: '700' }]}>
            {doctorName}
          </Text>
          {appointment.doctor?.specialty && (
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
              {appointment.doctor.specialty}
            </Text>
          )}

          <View style={[styles.metaRow, { flexDirection, marginTop: 4 }]}>
            <Ionicons name="time-outline" size={14} color={colors.textMuted} style={{ marginHorizontal: 2 }} />
            <Text style={[typography.tiny, { color: colors.textSecondary }]}>
              {formatTime(appointment.appointment_time)} ({appointment.duration_minutes} min)
            </Text>
          </View>

          {appointment.clinic_name && (
            <View style={[styles.metaRow, { flexDirection, marginTop: 2 }]}>
              <Ionicons name="location-outline" size={14} color={colors.textMuted} style={{ marginHorizontal: 2 }} />
              <Text style={[typography.tiny, { color: colors.textMuted }]}>
                {appointment.clinic_name}
              </Text>
            </View>
          )}
        </View>
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 6,
  },
  headerRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  dateBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  detailsRow: {
    alignItems: 'center',
  },
  typeIcon: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 8,
  },
  infoColumn: {
    flex: 1,
    paddingHorizontal: 4,
  },
  metaRow: {
    alignItems: 'center',
  },
});
