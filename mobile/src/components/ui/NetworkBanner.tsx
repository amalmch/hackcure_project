import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useOfflineSync } from '../../hooks/useOfflineSync';

export const NetworkBanner: React.FC = () => {
  const { colors, typography, spacing } = useTheme();
  const { isRTL, flexDirection } = useRTL();
  const { isOnline, isSyncing, pendingDosesCount, pendingMessagesCount } = useOfflineSync();
  const { t } = useTranslation();

  if (isOnline && pendingDosesCount === 0 && pendingMessagesCount === 0 && !isSyncing) {
    return null;
  }

  const isSyncingPending = isOnline && (pendingDosesCount > 0 || pendingMessagesCount > 0 || isSyncing);

  return (
    <View
      style={[
        styles.banner,
        {
          backgroundColor: isSyncingPending ? colors.infoLight : colors.warningLight,
          borderColor: isSyncingPending ? colors.info : colors.warning,
          paddingVertical: spacing.sm,
          paddingHorizontal: spacing.base,
          flexDirection,
        },
      ]}
    >
      <Ionicons
        name={isSyncingPending ? 'sync-outline' : 'cloud-offline-outline'}
        size={18}
        color={isSyncingPending ? colors.info : colors.warning}
        style={styles.icon}
      />
      <Text
        style={[
          typography.captionBold,
          styles.text,
          {
            color: isSyncingPending ? colors.info : colors.warning,
            textAlign: isRTL ? 'right' : 'left',
          },
        ]}
      >
        {isSyncingPending
          ? `Syncing ${pendingDosesCount + pendingMessagesCount} offline action(s)...`
          : t('common.offline')}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  banner: {
    borderBottomWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
  },
  icon: {
    marginHorizontal: 8,
  },
  text: {
    flex: 1,
  },
});
