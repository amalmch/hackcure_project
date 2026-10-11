import React from 'react';
import { View, StyleSheet, ViewStyle } from 'react-native';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';

interface ProgressBarProps {
  progress: number; // 0 to 100
  color?: string;
  height?: number;
  style?: ViewStyle;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  progress,
  color,
  height = 8,
  style,
}) => {
  const { colors, radii } = useTheme();
  const { isRTL } = useRTL();

  const clamped = Math.max(0, Math.min(100, progress));

  return (
    <View
      style={[
        styles.track,
        {
          backgroundColor: colors.cardBorder,
          height,
          borderRadius: radii.full,
        },
        style,
      ]}
    >
      <View
        style={[
          styles.fill,
          {
            backgroundColor: color || colors.primary,
            width: `${clamped}%`,
            height,
            borderRadius: radii.full,
            alignSelf: isRTL ? 'flex-end' : 'flex-start',
          },
        ]}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  track: {
    width: '100%',
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
  },
});
