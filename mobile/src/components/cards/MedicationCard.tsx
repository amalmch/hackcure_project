import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { PrescriptionItem } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';

interface MedicationCardProps {
  medication: PrescriptionItem;
  onPress?: () => void;
}

export const MedicationCard: React.FC<MedicationCardProps> = ({
  medication,
  onPress,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  return (
    <Card onPress={onPress} style={styles.card}>
      <View style={[styles.headerRow, { flexDirection }]}>
        <View
          style={[
            styles.iconWrapper,
            { backgroundColor: colors.primaryLight, borderRadius: radii.lg },
          ]}
        >
          <Ionicons name="medical" size={24} color={colors.primary} />
        </View>

        <View style={styles.titleColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {medication.medication_name}
          </Text>
          {medication.active_ingredient && (
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
              {medication.active_ingredient}
            </Text>
          )}
        </View>

        <View
          style={[
            styles.dosageBadge,
            { backgroundColor: colors.surface, borderColor: colors.cardBorder, borderRadius: radii.full },
          ]}
        >
          <Text style={[typography.captionBold, { color: colors.primary }]}>
            {medication.dosage}
          </Text>
        </View>
      </View>

      <View style={[styles.metaRow, { flexDirection, marginTop: spacing.md }]}>
        <View style={[styles.metaItem, { flexDirection }]}>
          <Ionicons name="repeat-outline" size={16} color={colors.textMuted} style={{ marginHorizontal: 4 }} />
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {medication.frequency}
          </Text>
        </View>

        {medication.before_food !== undefined && (
          <View style={[styles.metaItem, { flexDirection }]}>
            <Ionicons name="restaurant-outline" size={16} color={colors.textMuted} style={{ marginHorizontal: 4 }} />
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {medication.before_food ? t('medications.beforeFood') : t('medications.afterFood')}
            </Text>
          </View>
        )}
      </View>

      {medication.instructions && (
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
            {medication.instructions}
          </Text>
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
  dosageBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
  },
  metaRow: {
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 12,
  },
  metaItem: {
    alignItems: 'center',
  },
  instructionsBox: {
    padding: 10,
  },
});
