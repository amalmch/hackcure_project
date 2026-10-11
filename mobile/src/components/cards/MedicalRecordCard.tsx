import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { MedicalRecord, MedicalRecordType } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { formatDate } from '../../utils/dateUtils';

interface MedicalRecordCardProps {
  record: MedicalRecord;
  onPress?: () => void;
}

export const MedicalRecordCard: React.FC<MedicalRecordCardProps> = ({
  record,
  onPress,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();

  const getRecordIcon = (): keyof typeof Ionicons.glyphMap => {
    switch (record.record_type) {
      case MedicalRecordType.LAB_RESULT:
        return 'flask-outline';
      case MedicalRecordType.IMAGING:
        return 'scan-outline';
      case MedicalRecordType.PROCEDURE:
        return 'bandage-outline';
      case MedicalRecordType.DOCUMENT:
        return 'document-text-outline';
      default:
        return 'folder-outline';
    }
  };

  return (
    <Card onPress={onPress} style={styles.card}>
      <View style={[styles.mainRow, { flexDirection }]}>
        <View
          style={[
            styles.iconWrapper,
            { backgroundColor: colors.primaryLight, borderRadius: radii.lg },
          ]}
        >
          <Ionicons name={getRecordIcon()} size={24} color={colors.primary} />
        </View>

        <View style={styles.contentColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {record.title}
          </Text>

          {record.description && (
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign, marginTop: 2 }]}>
              {record.description}
            </Text>
          )}

          <View style={[styles.metaRow, { flexDirection, marginTop: 4 }]}>
            <Ionicons name="calendar-outline" size={14} color={colors.textMuted} style={{ marginHorizontal: 2 }} />
            <Text style={[typography.tiny, { color: colors.textMuted }]}>
              {formatDate(record.record_date)}
            </Text>
            {record.doctor && (
              <Text style={[typography.tiny, { color: colors.textMuted, marginHorizontal: 6 }]}>
                • Dr. {record.doctor.last_name}
              </Text>
            )}
          </View>
        </View>
      </View>
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
  iconWrapper: {
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
  metaRow: {
    alignItems: 'center',
  },
});
