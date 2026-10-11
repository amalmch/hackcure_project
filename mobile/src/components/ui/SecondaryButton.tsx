import React from 'react';
import {
  TouchableOpacity,
  Text,
  ActivityIndicator,
  StyleSheet,
  ViewStyle,
  TextStyle,
  View,
} from 'react-native';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';

interface SecondaryButtonProps {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
  style?: ViewStyle;
  textStyle?: TextStyle;
  variant?: 'outline' | 'ghost' | 'tint';
}

export const SecondaryButton: React.FC<SecondaryButtonProps> = ({
  title,
  onPress,
  loading = false,
  disabled = false,
  icon,
  style,
  textStyle,
  variant = 'outline',
}) => {
  const { colors, typography, radii, spacing } = useTheme();
  const { flexDirection } = useRTL();

  const getBgColor = () => {
    if (variant === 'tint') return colors.primaryLight;
    if (variant === 'ghost') return 'transparent';
    return colors.card;
  };

  const getBorderColor = () => {
    if (variant === 'outline') return colors.cardBorder;
    return 'transparent';
  };

  return (
    <TouchableOpacity
      activeOpacity={0.7}
      onPress={onPress}
      disabled={disabled || loading}
      style={[
        styles.button,
        {
          backgroundColor: getBgColor(),
          borderColor: getBorderColor(),
          borderWidth: variant === 'outline' ? 1 : 0,
          borderRadius: radii.lg,
          paddingVertical: spacing.md,
          paddingHorizontal: spacing.xl,
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={colors.primary} size="small" />
      ) : (
        <View style={[styles.contentRow, { flexDirection }]}>
          {icon && <View style={styles.iconWrapper}>{icon}</View>}
          <Text
            style={[
              typography.subtitle,
              styles.text,
              { color: disabled ? colors.textMuted : colors.textPrimary },
              textStyle,
            ]}
          >
            {title}
          </Text>
        </View>
      )}
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 48,
  },
  contentRow: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconWrapper: {
    marginHorizontal: 8,
  },
  text: {
    fontWeight: '600',
  },
});
