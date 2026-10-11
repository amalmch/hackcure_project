import React from 'react';
import { View, Text, StyleSheet, ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../theme';
import { PrimaryButton } from './PrimaryButton';

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  style?: ViewStyle;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title,
  message,
  onRetry,
  style,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { t } = useTranslation();

  return (
    <View style={[styles.container, style]}>
      <View
        style={[
          styles.iconCircle,
          {
            backgroundColor: colors.errorLight,
            borderRadius: radii.full,
            marginBottom: spacing.base,
          },
        ]}
      >
        <Ionicons name="alert-circle-outline" size={40} color={colors.error} />
      </View>
      <Text style={[typography.h4, styles.title, { color: colors.textPrimary }]}>
        {title || t('common.error')}
      </Text>
      <Text style={[typography.body, styles.message, { color: colors.textSecondary }]}>
        {message || t('copy.unableToRetrieve')}
      </Text>
      {onRetry && (
        <PrimaryButton
          title={t('common.retry')}
          onPress={onRetry}
          style={{ marginTop: spacing.lg }}
          icon={<Ionicons name="refresh" size={18} color="#FFFFFF" />}
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    marginVertical: 20,
  },
  iconCircle: {
    width: 72,
    height: 72,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    textAlign: 'center',
    marginBottom: 8,
  },
  message: {
    textAlign: 'center',
    lineHeight: 22,
  },
});
