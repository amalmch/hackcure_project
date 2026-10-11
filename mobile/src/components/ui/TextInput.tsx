import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput as RNTextInput,
  TextInputProps as RNTextInputProps,
  TouchableOpacity,
  StyleSheet,
  ViewStyle,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useTranslation } from 'react-i18next';

interface TextInputProps extends RNTextInputProps {
  label?: string;
  error?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  containerStyle?: ViewStyle;
}

export const TextInput: React.FC<TextInputProps> = ({
  label,
  error,
  leftIcon,
  rightIcon,
  containerStyle,
  secureTextEntry,
  style,
  ...rest
}) => {
  const { colors, typography, radii, spacing } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();
  const [isFocused, setIsFocused] = useState(false);
  const [isPasswordHidden, setIsPasswordHidden] = useState(secureTextEntry);

  return (
    <View style={[styles.container, containerStyle]}>
      {label && (
        <Text
          style={[
            typography.captionBold,
            styles.label,
            { color: colors.textSecondary, textAlign },
          ]}
        >
          {label}
        </Text>
      )}

      <View
        style={[
          styles.inputContainer,
          {
            backgroundColor: colors.inputBg,
            borderColor: error
              ? colors.error
              : isFocused
              ? colors.inputBorderFocus
              : colors.inputBorder,
            borderRadius: radii.lg,
            flexDirection,
          },
        ]}
      >
        {leftIcon && <View style={styles.iconContainer}>{leftIcon}</View>}

        <RNTextInput
          placeholderTextColor={colors.placeholder}
          secureTextEntry={isPasswordHidden}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          style={[
            styles.input,
            typography.body,
            {
              color: colors.textPrimary,
              textAlign,
              paddingVertical: spacing.md,
              paddingHorizontal: spacing.md,
            },
            style,
          ]}
          {...rest}
        />

        {secureTextEntry ? (
          <TouchableOpacity
            accessibilityRole="button"
            accessibilityLabel={t(isPasswordHidden ? 'common.showPassword' : 'common.hidePassword')}
            style={styles.iconContainer}
            onPress={() => setIsPasswordHidden(!isPasswordHidden)}
            activeOpacity={0.7}
          >
            <Ionicons
              name={isPasswordHidden ? 'eye-off-outline' : 'eye-outline'}
              size={20}
              color={colors.textMuted}
            />
          </TouchableOpacity>
        ) : (
          rightIcon && <View style={styles.iconContainer}>{rightIcon}</View>
        )}
      </View>

      {error && (
        <Text
          style={[
            typography.tiny,
            styles.errorText,
            { color: colors.error, textAlign },
          ]}
        >
          {error}
        </Text>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    marginVertical: 6,
  },
  label: {
    marginBottom: 6,
  },
  inputContainer: {
    borderWidth: 1,
    alignItems: 'center',
    minHeight: 50,
  },
  input: {
    flex: 1,
  },
  iconContainer: {
    paddingHorizontal: 12,
  },
  errorText: {
    marginTop: 4,
  },
});
