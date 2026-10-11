import React from 'react';
import { View, TextInput, TouchableOpacity, StyleSheet, ViewStyle } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useTranslation } from 'react-i18next';

interface SearchBarProps {
  value: string;
  onChangeText: (text: string) => void;
  onClear?: () => void;
  placeholder?: string;
  style?: ViewStyle;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  value,
  onChangeText,
  onClear,
  placeholder,
  style,
}) => {
  const { colors, typography, radii, spacing } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: colors.inputBg,
          borderColor: colors.cardBorder,
          borderRadius: radii.xl,
          paddingHorizontal: spacing.md,
          flexDirection,
        },
        style,
      ]}
    >
      <Ionicons name="search" size={20} color={colors.textMuted} style={styles.icon} />
      <TextInput
        accessibilityLabel={t('common.search')}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder || t('copy.search')}
        placeholderTextColor={colors.placeholder}
        style={[
          styles.input,
          typography.body,
          {
            color: colors.textPrimary,
            textAlign,
            paddingVertical: spacing.md,
          },
        ]}
      />
      {value.length > 0 && (
        <TouchableOpacity
          accessibilityRole="button"
          accessibilityLabel={t('common.clearSearch')}
          onPress={() => {
            onChangeText('');
            onClear?.();
          }}
          activeOpacity={0.7}
          style={styles.clearBtn}
        >
          <Ionicons name="close-circle" size={18} color={colors.textMuted} />
        </TouchableOpacity>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    borderWidth: 1,
    alignItems: 'center',
    marginVertical: 8,
  },
  icon: {
    marginHorizontal: 8,
  },
  input: {
    flex: 1,
  },
  clearBtn: {
    padding: 6,
  },
});
