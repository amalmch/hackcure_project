import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';

interface ListItemProps {
  title: string;
  subtitle?: string;
  leftIcon?: React.ReactNode;
  rightElement?: React.ReactNode;
  showChevron?: boolean;
  onPress?: () => void;
  style?: ViewStyle;
}

export const ListItem: React.FC<ListItemProps> = ({
  title,
  subtitle,
  leftIcon,
  rightElement,
  showChevron = true,
  onPress,
  style,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign, isRTL } = useRTL();

  const content = (
    <View
      style={[
        styles.container,
        {
          backgroundColor: colors.card,
          borderRadius: radii.lg,
          padding: spacing.md,
          borderColor: colors.cardBorder,
          borderWidth: 1,
          flexDirection,
        },
        style,
      ]}
    >
      {leftIcon && <View style={styles.leftIcon}>{leftIcon}</View>}
      <View style={styles.textContainer}>
        <Text style={[typography.subtitle, { color: colors.textPrimary, textAlign }]}>
          {title}
        </Text>
        {subtitle && (
          <Text style={[typography.caption, { color: colors.textSecondary, textAlign, marginTop: 2 }]}>
            {subtitle}
          </Text>
        )}
      </View>
      {rightElement ||
        (showChevron && (
          <Ionicons
            name={isRTL ? 'chevron-back' : 'chevron-forward'}
            size={20}
            color={colors.textMuted}
          />
        ))}
    </View>
  );

  if (onPress) {
    return (
      <TouchableOpacity activeOpacity={0.7} onPress={onPress}>
        {content}
      </TouchableOpacity>
    );
  }

  return content;
};

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    marginVertical: 4,
  },
  leftIcon: {
    marginHorizontal: 12,
  },
  textContainer: {
    flex: 1,
    paddingHorizontal: 4,
  },
});
