import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { notificationsApi } from '../../services/api/notifications';
import { NotificationCategory } from '../../types';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { NotificationCard } from '../../components/cards/NotificationCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

export const NotificationScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing } = useTheme();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const {
    data: paginated,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => notificationsApi.getNotifications(1, 50),
  });

  const markAllMutation = useMutation({
    mutationFn: notificationsApi.markAllAsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const markOneMutation = useMutation({
    mutationFn: (id: string) => notificationsApi.markAsRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const handleNotificationPress = (notif: any) => {
    if (!notif.is_read) {
      markOneMutation.mutate(notif.id);
    }
    // Deep link based on category
    if (notif.category === NotificationCategory.MEDICATION) router.push('/(tabs)/treatment');
    else if (notif.category === NotificationCategory.DOCTOR) router.push('/(tabs)/doctor');
    else if (notif.category === NotificationCategory.PRESCRIPTION) router.push('/(tabs)/treatment');
    else if (notif.category === NotificationCategory.APPOINTMENT) router.push('/appointment/list');
    else if (notif.category === NotificationCategory.PHARMACY) router.push('/(tabs)/pharmacy');
  };

  const notifications = paginated?.items || [];

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header
        title={t('notifications.title')}
        showBack
        rightAction={
          notifications.length > 0 ? (
            <TouchableOpacity
              onPress={() => markAllMutation.mutate()}
              activeOpacity={0.7}
              style={{ padding: 4 }}
            >
              <Text style={[typography.captionBold, { color: colors.primary }]}>
                {t('notifications.markAllAsRead')}
              </Text>
            </TouchableOpacity>
          ) : undefined
        }
      />

      {isLoading && !paginated ? (
        <View style={{ marginTop: spacing.md }}>
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </View>
      ) : isError && !paginated ? (
        <ErrorState
          title={t('copy.loadNotifications')}
          onRetry={refetch}
        />
      ) : notifications.length === 0 ? (
        <EmptyState
          icon="notifications-outline"
          title={t('notifications.noNotifications')}
          description={t('copy.notificationsDescription')}
        />
      ) : (
        <View style={{ marginTop: spacing.sm }}>
          {notifications.map((notif) => (
            <NotificationCard
              key={notif.id}
              notification={notif}
              onPress={() => handleNotificationPress(notif)}
            />
          ))}
        </View>
      )}
    </ScreenContainer>
  );
};
