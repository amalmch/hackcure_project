import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ViewStyle } from 'react-native';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';

interface TabItem<T extends string = string> {
  key: T;
  label: string;
  badge?: number;
}

interface TabBarProps<T extends string = string> {
  tabs: TabItem<T>[];
  activeTab: T;
  onTabChange: (key: T) => void;
  style?: ViewStyle;
}

export const TabBar = <T extends string = string>({
  tabs,
  activeTab,
  onTabChange,
  style,
}: TabBarProps<T>) => {
  const { colors, typography, radii, spacing } = useTheme();
  const { flexDirection } = useRTL();

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: colors.inputBg,
          borderRadius: radii.xl,
          padding: 4,
          flexDirection,
        },
        style,
      ]}
    >
      {tabs.map((tab) => {
        const isActive = tab.key === activeTab;
        return (
          <TouchableOpacity
            key={tab.key}
            activeOpacity={0.8}
            onPress={() => onTabChange(tab.key)}
            style={[
              styles.tab,
              {
                backgroundColor: isActive ? colors.surface : 'transparent',
                borderRadius: radii.lg,
                paddingVertical: spacing.sm,
                minHeight: 44,
              },
            ]}
          >
            <Text
              maxFontSizeMultiplier={1.3}
              style={[
                typography.captionBold,
                {
                  color: isActive ? colors.primary : colors.textSecondary,
                  fontWeight: isActive ? '700' : '500',
                },
              ]}
            >
              {tab.label}
            </Text>
            {tab.badge !== undefined && tab.badge > 0 && (
              <View
                style={[
                  styles.badge,
                  {
                    backgroundColor: isActive ? colors.primary : colors.textMuted,
                    borderRadius: radii.full,
                  },
                ]}
              >
                <Text style={[typography.tiny, { color: '#FFFFFF', fontWeight: '700' }]}>
                  {tab.badge}
                </Text>
              </View>
            )}
          </TouchableOpacity>
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    marginVertical: 12,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    minWidth: 0,
    paddingHorizontal: 4,
  },
  badge: {
    paddingHorizontal: 6,
    paddingVertical: 1,
    marginLeft: 6,
  },
});
