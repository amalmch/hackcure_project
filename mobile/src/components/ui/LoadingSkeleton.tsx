import React from 'react';
import { View, StyleSheet, ViewStyle } from 'react-native';
import { useTheme } from '../../theme';

interface LoadingSkeletonProps {
  width?: number | `${number}%` | 'auto';
  height?: number;
  borderRadius?: number;
  style?: ViewStyle;
}

export const LoadingSkeleton: React.FC<LoadingSkeletonProps> = ({
  width = '100%',
  height = 20,
  borderRadius = 8,
  style,
}) => {
  const { colors } = useTheme();

  return (
    <View
      style={[
        styles.skeleton,
        {
          width,
          height,
          borderRadius,
          backgroundColor: colors.cardBorder,
        },
        style,
      ]}
    />
  );
};

export const CardSkeleton: React.FC<{ style?: ViewStyle }> = ({ style }) => {
  const { colors, radii, spacing } = useTheme();

  return (
    <View
      style={[
        styles.cardContainer,
        {
          backgroundColor: colors.card,
          borderRadius: radii.xl,
          padding: spacing.base,
          borderColor: colors.cardBorder,
          borderWidth: 1,
        },
        style,
      ]}
    >
      <View style={styles.row}>
        <LoadingSkeleton width={48} height={48} borderRadius={24} />
        <View style={styles.column}>
          <LoadingSkeleton width="70%" height={16} borderRadius={6} />
          <LoadingSkeleton width="45%" height={12} borderRadius={4} style={{ marginTop: 8 }} />
        </View>
      </View>
      <LoadingSkeleton width="100%" height={12} borderRadius={4} style={{ marginTop: 16 }} />
      <LoadingSkeleton width="85%" height={12} borderRadius={4} style={{ marginTop: 8 }} />
    </View>
  );
};

const styles = StyleSheet.create({
  skeleton: {
    opacity: 0.6,
  },
  cardContainer: {
    marginVertical: 8,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  column: {
    marginLeft: 12,
    flex: 1,
  },
});
