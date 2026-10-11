import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { AppNotification, NotificationCategory } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { formatDateTime } from '../../utils/dateUtils';
import { localizedNotificationText } from '../../utils/localizedNotification';

interface NotificationCardProps {
  notification: AppNotification;
  onPress?: () => void;
}

export const NotificationCard: React.FC<NotificationCardProps> = ({
  notification,
  onPress,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const localizedText = localizedNotificationText(notification);

  const getCategoryIcon = (): keyof typeof Ionicons.glyphMap => {
    switch (notification.category) {
      case NotificationCategory.MEDICATION:
        return 'medkit';
      case NotificationCategory.DOCTOR:
        return 'chatbubble-ellipses';
      case NotificationCategory.PRESCRIPTION:
        return 'document-text';
      case NotificationCategory.APPOINTMENT:
        return 'calendar';
      case NotificationCategory.PHARMACY:
        return 'business';
      default:
        return 'notifications';
    }
  };

  return (
    <Card
      onPress={onPress}
      style={[
        styles.card,
        {
          backgroundColor: notification.is_read ? colors.card : colors.primaryLight,
          borderLeftColor: notification.is_read ? colors.cardBorder : colors.primary,
          borderLeftWidth: 4,
        },
      ]}
    >
      <View style={[styles.mainRow, { flexDirection }]}>
        <View
          style={[
            styles.iconWrapper,
            {
              backgroundColor: notification.is_read ? colors.inputBg : colors.surface,
              borderRadius: radii.full,
            },
          ]}
        >
          <Ionicons
            name={getCategoryIcon()}
            size={22}
            color={notification.is_read ? colors.textMuted : colors.primary}
          />
        </View>

        <View style={styles.contentColumn}>
          <Text
            style={[
              typography.subtitle,
              {
                color: colors.textPrimary,
                textAlign,
                fontWeight: notification.is_read ? '500' : '700',
              },
            ]}
          >
            {localizedText.title}
          </Text>
          {localizedText.body && (
            <Text
              style={[
                typography.caption,
                { color: colors.textSecondary, textAlign, marginTop: 2 },
              ]}
            >
              {localizedText.body}
            </Text>
          )}
          <Text
            style={[
              typography.tiny,
              { color: colors.textMuted, textAlign, marginTop: 4 },
            ]}
          >
            {formatDateTime(notification.created_at)}
          </Text>
        </View>
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 4,
    paddingVertical: 12,
  },
  mainRow: {
    alignItems: 'flex-start',
  },
  iconWrapper: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 8,
  },
  contentColumn: {
    flex: 1,
    paddingHorizontal: 4,
  },
});
