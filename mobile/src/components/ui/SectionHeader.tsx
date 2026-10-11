import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ViewStyle } from 'react-native';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  actionTitle?: string;
  onAction?: () => void;
  style?: ViewStyle;
}

export const SectionHeader: React.FC<SectionHeaderProps> = ({
  title,
  subtitle,
  actionTitle,
  onAction,
  style,
}) => {
  const { colors, typography, spacing } = useTheme();
  const { flexDirection, textAlign } = useRTL();

  return (
    <View style={[styles.container, { marginBottom: spacing.sm, marginTop: spacing.md }, style]}>
      <View style={[styles.row, { flexDirection }]}>
        <View style={styles.titleColumn}>
          <Text style={[typography.h3, { color: colors.textPrimary, textAlign }]}>
            {title}
          </Text>
          {subtitle && (
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign, marginTop: 2 }]}>
              {subtitle}
            </Text>
          )}
        </View>
        {actionTitle && onAction && (
          <TouchableOpacity onPress={onAction} activeOpacity={0.7} style={styles.actionBtn}>
            <Text style={[typography.captionBold, { color: colors.primary }]}>
              {actionTitle}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    width: '100%',
  },
  row: {
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  titleColumn: {
    flex: 1,
  },
  actionBtn: {
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
});
