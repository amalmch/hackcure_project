import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Doctor } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { Avatar } from '../ui/Avatar';
import { SecondaryButton } from '../ui/SecondaryButton';

interface DoctorCardProps {
  doctor: Doctor;
  onMessage?: () => void;
  onCall?: () => void;
}

export const DoctorCard: React.FC<DoctorCardProps> = ({
  doctor,
  onMessage,
  onCall,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();

  const fullName = `Dr. ${doctor.first_name} ${doctor.last_name}`;

  return (
    <Card style={styles.card}>
      <View style={[styles.mainRow, { flexDirection }]}>
        <Avatar
          url={doctor.avatar_url}
          name={fullName}
          size={56}
          style={{ marginHorizontal: 8 }}
        />

        <View style={styles.infoColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {fullName}
          </Text>
          <Text style={[typography.captionBold, { color: colors.primary, textAlign, marginTop: 2 }]}>
            {doctor.specialty}
          </Text>
          {doctor.clinic_name && (
            <View style={[styles.metaRow, { flexDirection, marginTop: 4 }]}>
              <Ionicons name="business-outline" size={14} color={colors.textMuted} style={{ marginHorizontal: 2 }} />
              <Text style={[typography.tiny, { color: colors.textSecondary }]}>
                {doctor.clinic_name}
              </Text>
            </View>
          )}
        </View>
      </View>

      {onMessage && (
        <View style={{ marginTop: spacing.base }}>
          <SecondaryButton
            title={i18n.t('copy.static_send_message')}
            onPress={onMessage}
            variant="tint"
            icon={<Ionicons name="chatbubble-ellipses-outline" size={18} color={colors.primary} />}
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
  mainRow: {
    alignItems: 'center',
  },
  infoColumn: {
    flex: 1,
    paddingHorizontal: 4,
  },
  metaRow: {
    alignItems: 'center',
  },
});
