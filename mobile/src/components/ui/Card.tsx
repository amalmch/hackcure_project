import React from 'react';
import { View, TouchableOpacity, StyleSheet, ViewStyle, StyleProp } from 'react-native';
import { useTheme } from '../../theme';

interface CardProps {
  children: React.ReactNode;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  variant?: 'elevated' | 'outlined' | 'flat';
}

export const Card: React.FC<CardProps> = ({
  children,
  onPress,
  style,
  variant = 'elevated',
}) => {
  const { colors, radii, shadows, spacing } = useTheme();

  const getStyle = (): ViewStyle => {
    const base: ViewStyle = {
      backgroundColor: colors.card,
      borderRadius: radii.xl,
      padding: spacing.base,
    };

    if (variant === 'elevated') {
      return {
        ...base,
        ...shadows.sm,
        borderColor: colors.cardBorder,
        borderWidth: 1,
      };
    }

    if (variant === 'outlined') {
      return {
        ...base,
        borderColor: colors.cardBorder,
        borderWidth: 1,
      };
    }

    return base;
  };

  if (onPress) {
    return (
      <TouchableOpacity
        activeOpacity={0.8}
        onPress={onPress}
        style={[getStyle(), style]}
      >
        {children}
      </TouchableOpacity>
    );
  }

  return <View style={[getStyle(), style]}>{children}</View>;
};
