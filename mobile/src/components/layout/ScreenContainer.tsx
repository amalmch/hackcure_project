import React from 'react';
import {
  View,
  ScrollView,
  RefreshControl,
  StyleSheet,
  ViewStyle,
  StatusBar,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useTheme } from '../../theme';
import { NetworkBanner } from '../ui/NetworkBanner';
import { useResponsiveLayout } from '../../hooks/useResponsiveLayout';

interface ScreenContainerProps {
  children: React.ReactNode;
  scrollable?: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
  style?: ViewStyle;
  contentContainerStyle?: ViewStyle;
  withPadding?: boolean;
  withNetworkBanner?: boolean;
}

export const ScreenContainer: React.FC<ScreenContainerProps> = ({
  children,
  scrollable = true,
  onRefresh,
  refreshing = false,
  style,
  contentContainerStyle,
  withPadding = true,
  withNetworkBanner = true,
}) => {
  const { colors, isDark, spacing } = useTheme();
  const { contentMaxWidth, horizontalPadding } = useResponsiveLayout();
  const contentWidthStyle = contentMaxWidth ? { width: '100%' as const, maxWidth: contentMaxWidth, alignSelf: 'center' as const } : undefined;

  return (
    <SafeAreaView
      edges={['top', 'left', 'right', 'bottom']}
      style={[styles.safeArea, { backgroundColor: colors.background }, style]}
    >
      <StatusBar
        barStyle={isDark ? 'light-content' : 'dark-content'}
        backgroundColor={colors.background}
      />
      {withNetworkBanner && <NetworkBanner />}

      <KeyboardAvoidingView
        style={styles.keyboard}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
      {scrollable ? (
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={[
            styles.scrollContent,
            withPadding && { paddingHorizontal: horizontalPadding || spacing.base, paddingBottom: spacing['3xl'] },
            contentContainerStyle,
          ]}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          refreshControl={
            onRefresh ? (
              <RefreshControl
                refreshing={refreshing}
                onRefresh={onRefresh}
                tintColor={colors.primary}
                colors={[colors.primary]}
              />
            ) : undefined
          }
        >
          <View style={[styles.contentWidth, contentWidthStyle]}>{children}</View>
        </ScrollView>
      ) : (
        <View
          style={[
            styles.nonScroll,
            withPadding && { paddingHorizontal: horizontalPadding || spacing.base },
            contentContainerStyle,
          ]}
        >
          <View style={[styles.contentWidth, styles.nonScrollContent, contentWidthStyle]}>{children}</View>
        </View>
      )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  keyboard: {
    flex: 1,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  nonScroll: {
    flex: 1,
  },
  nonScrollContent: {
    flex: 1,
    width: '100%',
  },
  contentWidth: {
    width: '100%',
  },
});
