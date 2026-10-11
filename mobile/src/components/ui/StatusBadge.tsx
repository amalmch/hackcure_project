import React from 'react';
import { View, Text, StyleSheet, ViewStyle, TextStyle } from 'react-native';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';

interface StatusBadgeProps {
  label: string;
  color: string;
  bgColor?: string;
  icon?: React.ReactNode;
  style?: ViewStyle;
  textStyle?: TextStyle;
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  label,
  color,
  bgColor,
  icon,
  style,
  textStyle,
  size = 'md',
}) => {
  const { radii, typography } = useTheme();
  const { flexDirection } = useRTL();

  return (
    <View
      style={[
        styles.badge,
        {
          backgroundColor: bgColor || `${color}15`,
          borderColor: `${color}30`,
          borderWidth: 1,
          borderRadius: radii.full,
          paddingVertical: size === 'sm' ? 2 : 4,
          paddingHorizontal: size === 'sm' ? 8 : 12,
          flexDirection,
        },
        style,
      ]}
    >
      {icon && <View style={styles.icon}>{icon}</View>}
      <Text
        style={[
          size === 'sm' ? typography.tiny : typography.captionBold,
          styles.text,
          { color },
          textStyle,
        ]}
      >
        {label}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  badge: {
    alignSelf: 'flex-start',
    alignItems: 'center',
    justifyContent: 'center',
  },
  icon: {
    marginHorizontal: 4,
  },
  text: {
    fontWeight: '600',
  },
});
