import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../../theme';

interface ProgressCircleProps {
  percentage: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  label?: string;
}

export const ProgressCircle: React.FC<ProgressCircleProps> = ({
  percentage,
  size = 80,
  strokeWidth = 8,
  color,
  label,
}) => {
  const { colors, typography } = useTheme();
  const activeColor = color || colors.primary;

  return (
    <View style={[styles.container, { width: size, height: size }]}>
      {/* Outer border representation */}
      <View
        style={[
          styles.circle,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            borderWidth: strokeWidth,
            borderColor: colors.cardBorder,
          },
        ]}
      />
      {/* Percentage fill representation */}
      <View
        style={[
          styles.circle,
          styles.progressOverlay,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            borderWidth: strokeWidth,
            borderColor: activeColor,
            opacity: Math.max(0.2, percentage / 100),
          },
        ]}
      />
      <View style={styles.content}>
        <Text style={[typography.h4, { color: colors.textPrimary }]}>
          {Math.round(percentage)} %
        </Text>
        {label && (
          <Text style={[typography.tiny, { color: colors.textSecondary }]}>
            {label}
          </Text>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  circle: {
    position: 'absolute',
  },
  progressOverlay: {
    transform: [{ rotate: '-90deg' }],
  },
  content: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
