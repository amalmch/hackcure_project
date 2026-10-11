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
import { useTranslation } from 'react-i18next';

interface PrimaryButtonProps {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
  style?: ViewStyle;
  textStyle?: TextStyle;
  variant?: 'primary' | 'danger' | 'success';
}

export const PrimaryButton: React.FC<PrimaryButtonProps> = ({
  title,
  onPress,
  loading = false,
  disabled = false,
  icon,
  style,
  textStyle,
  variant = 'primary',
}) => {
  const { colors, typography, radii, spacing } = useTheme();
  const { flexDirection } = useRTL();
  const { t } = useTranslation();

  const getBgColor = () => {
    if (disabled) return colors.cardBorder;
    if (variant === 'danger') return colors.error;
    if (variant === 'success') return colors.success;
    return colors.primary;
  };

  return (
    <TouchableOpacity
      activeOpacity={0.8}
      onPress={onPress}
      disabled={disabled || loading}
      style={[
        styles.button,
        {
          backgroundColor: getBgColor(),
          borderRadius: radii.lg,
          paddingVertical: spacing.md + 2,
          paddingHorizontal: spacing.xl,
        },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color="#FFFFFF" size="small" accessibilityLabel={t('common.loading')} />
      ) : (
        <View style={[styles.contentRow, { flexDirection }]}>
          {icon && <View style={styles.iconWrapper}>{icon}</View>}
          <Text
            maxFontSizeMultiplier={1.3}
            style={[
              typography.subtitle,
              styles.text,
              { color: disabled ? colors.textMuted : '#FFFFFF' },
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
    minHeight: 52,
  },
  contentRow: {
    alignItems: 'center',
    justifyContent: 'center',
    flexWrap: 'wrap',
    flex: 1,
  },
  iconWrapper: {
    marginHorizontal: 8,
  },
  text: {
    fontWeight: '600',
    flexShrink: 1,
    textAlign: 'center',
  },
});
