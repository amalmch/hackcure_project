import { useEffect, useState, useCallback } from 'react';
import { Platform } from 'react-native';
import Constants, { ExecutionEnvironment } from 'expo-constants';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
import { medicationsApi } from '../services/api/medications';
import { MedicationDose } from '../types';
import i18n from '../i18n';

// expo-notifications has no web implementation. Local notifications are supported
// in Expo Go on native platforms, so keep this import available there.
const isExpoGo =
  Constants.appOwnership === 'expo' ||
  Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

const loadNotifications = async () => {
  if (Platform.OS === 'web' || isExpoGo) return null;
  try {
    return await import('expo-notifications');
  } catch {
    return null;
  }
};

const DOSE_CATEGORY_ID = 'DOSE_REMINDER_CATEGORY';
const ACTION_TAKE_DOSE = 'TAKE_DOSE';
const ACTION_SKIP_DOSE = 'SKIP_DOSE';

export const useNotifications = () => {
  const [permissionGranted, setPermissionGranted] = useState(false);
  const router = useRouter();

  const cancelDoseEscalation = useCallback(async (doseId: string) => {
    try {
      const Notifications = await loadNotifications();
      if (!Notifications) return;
      const stored = await AsyncStorage.getItem(`@hackcure_escalation_${doseId}`);
      if (stored) {
        const ids: string[] = JSON.parse(stored);
        await Promise.all(ids.map(async (id) => {
          try { await Notifications.cancelScheduledNotificationAsync(id); } catch { /* Ignore individual cancel errors */ }
        }));
        await AsyncStorage.removeItem(`@hackcure_escalation_${doseId}`);
      }
    } catch {
      // Ignore
    }
  }, []);

  useEffect(() => {
    let subscription: { remove: () => void } | null = null;

    const setupNotifications = async () => {
      try {
        const Notifications = await loadNotifications();
        if (!Notifications) return;

        Notifications.setNotificationHandler({
          handleNotification: async () => ({
            shouldShowAlert: true,
            shouldPlaySound: true,
            shouldSetBadge: true,
            shouldPresentAlert: true,
            shouldPresentBadge: true,
            shouldPresentSound: true,
            shouldShowBanner: true,
            shouldShowList: true,
          }),
        });

        const { status: existingStatus } = await Notifications.getPermissionsAsync();
        let finalStatus = existingStatus;
        if (existingStatus !== 'granted') {
          const { status } = await Notifications.requestPermissionsAsync();
          finalStatus = status;
        }
        setPermissionGranted(finalStatus === 'granted');

        if (Platform.OS === 'android') {
          await Notifications.setNotificationChannelAsync('medication_reminders', {
            name: i18n.t('notifications.channelName'),
            description: i18n.t('notifications.channelDescription'),
            importance: Notifications.AndroidImportance.MAX,
            vibrationPattern: [0, 500, 250, 500],
            lightColor: '#0284C7',
            sound: 'default',
            enableVibrate: true,
            bypassDnd: true,
          });
        }

        // Register an action button to mark the dose as taken.
        try {
          await Notifications.setNotificationCategoryAsync(DOSE_CATEGORY_ID, [
            {
              identifier: ACTION_TAKE_DOSE,
              buttonTitle: "✅ J'ai pris ma dose",
              options: { opensAppToForeground: false },
            },
            {
              identifier: ACTION_SKIP_DOSE,
              buttonTitle: i18n.t('notifications.skipDose'),
              options: { opensAppToForeground: false },
            },
          ]);
        } catch {
          // Ignore if unsupported
        }
      } catch {
        // Notifications might be restricted in Expo Go on Android
      }
    };

    setupNotifications();

    // Listen for notification interactions (taps on notification or buttons)
    const addResponseListener = async () => {
      const Notifications = await loadNotifications();
      if (!Notifications) return;
      subscription = Notifications.addNotificationResponseReceivedListener(async (response) => {
        const actionId = response.actionIdentifier;
        const data = response?.notification?.request?.content?.data as any;
        const doseId = data?.doseId;

        if (actionId === ACTION_TAKE_DOSE && doseId) {
          try {
            await medicationsApi.takeDose(doseId, doseId);
            await cancelDoseEscalation(doseId);
          } catch {
            // Offline or error
          }
          return;
        }

        if (actionId === ACTION_SKIP_DOSE && doseId) {
          try {
            await cancelDoseEscalation(doseId);
          } catch {
            // Ignore
          }
          return;
        }

        // Default: Open relevant screen
        if (data?.screen) {
          router.push(data.screen as any);
        } else {
          router.push('/treatment/medications' as any);
        }
      });
    };
    void addResponseListener().catch(() => {
      // Notifications are optional in Expo Go and may be unavailable on some devices.
    });

    return () => {
      subscription?.remove();
    };
  }, [router, cancelDoseEscalation]);

  /**
   * Schedules a single notification at triggerDate
   */
  const scheduleLocalReminder = async (
    title: string,
    body: string,
    triggerDate: Date,
    data?: Record<string, unknown>
  ): Promise<string> => {
    try {
      const Notifications = await loadNotifications();
      if (!Notifications) return '';
      return await Notifications.scheduleNotificationAsync({
        content: {
          title,
          body,
          sound: true,
          priority: Notifications.AndroidNotificationPriority.MAX,
          categoryIdentifier: DOSE_CATEGORY_ID,
          data: data || {},
        },
        trigger: {
          type: Notifications.SchedulableTriggerInputTypes.DATE,
          date: triggerDate,
          channelId: Platform.OS === 'android' ? 'medication_reminders' : undefined,
        },
      });
    } catch {
      return '';
    }
  };

  /**
   * Schedules a dose with 30-minute repeat escalation:
   * Alert 0: At scheduled dose time
   * Alerts 1..16: Every 30 minutes thereafter (up to 8 hours maximum)
   * All IDs are tracked in AsyncStorage under `@hackcure_escalation_${doseId}`
   */
  const scheduleDoseWithEscalation = useCallback(
    async (
      doseId: string,
      medicationName: string,
      dosage: string,
      scheduledDateTime: Date,
      maxRepeats: number = 16
    ): Promise<string[]> => {
      const scheduledIds: string[] = [];
      const now = new Date();

      for (let i = 0; i <= maxRepeats; i++) {
        const triggerTime = new Date(scheduledDateTime.getTime() + i * 30 * 60 * 1000);
        // Only schedule if in the future
        if (triggerTime > now) {
          const isRepeat = i > 0;
          const title = isRepeat
            ? `⚠️ Rappel (${i * 30} min): ${medicationName} ${dosage}`
            : `💊 Heure de votre médicament: ${medicationName} ${dosage}`;

          const body = isRepeat
            ? `Vous n'avez pas encore confirmé la prise de ${medicationName}. Prenez votre dose dès que possible.`
            : `Il est temps de prendre ${medicationName} (${dosage}). Touchez pour confirmer.`;

          const notifId = await scheduleLocalReminder(title, body, triggerTime, {
            doseId,
            repeatIndex: i,
            screen: '/treatment/medications',
          });

          if (notifId) {
            scheduledIds.push(notifId);
          }
        }
      }

      if (scheduledIds.length > 0) {
        await AsyncStorage.setItem(
          `@hackcure_escalation_${doseId}`,
          JSON.stringify(scheduledIds)
        );
      }

      return scheduledIds;
    },
    []
  );

  /**
   * Cancels all repeating notifications for a given dose (called when marked taken or skipped)
   */
  /**
   * Rebuilds all dose reminders from scratch when a new prescription is applied
   */
  const rebuildAllDoseReminders = useCallback(
    async (doses: MedicationDose[]) => {
      try {
        const Notifications = await loadNotifications();
        if (!Notifications) return;
        const doseReminderKeys = (await AsyncStorage.getAllKeys()).filter((key) => key.startsWith('@hackcure_escalation_'));
        for (const key of doseReminderKeys) {
          try {
            const stored = await AsyncStorage.getItem(key);
            const ids: string[] = stored ? JSON.parse(stored) : [];
            await Promise.all(ids.map((id) => Notifications.cancelScheduledNotificationAsync(id).catch(() => undefined)));
          } catch {
            // Continue rebuilding the remaining dose reminders.
          }
        }
        if (doseReminderKeys.length) await AsyncStorage.multiRemove(doseReminderKeys);
        const now = new Date();

        for (const dose of doses) {
          if (dose.status === 'SCHEDULED' || dose.status === 'DUE' || dose.status === 'REMINDING') {
            const medName = dose.prescription_item?.medication_name || 'Médicament';
            const dosage = dose.prescription_item?.dosage || '';
            const [hours, minutes] = (dose.scheduled_time || '08:00').split(':').map(Number);
            const [year, month, day] = dose.scheduled_date.split('-').map(Number);
            const doseDate = new Date(year, month - 1, day, hours, minutes, 0, 0);

            // If scheduled within the next 7 days and not more than 8h in the past
            if (doseDate.getTime() + 8 * 3600 * 1000 > now.getTime()) {
              await scheduleDoseWithEscalation(dose.id, medName, dosage, doseDate);
            }
          }
        }
      } catch {
        // Ignore
      }
    },
    [scheduleDoseWithEscalation]
  );

  const cancelReminder = async (notificationId: string) => {
    try {
      const Notifications = await loadNotifications();
      if (!Notifications) return;
      await Notifications.cancelScheduledNotificationAsync(notificationId);
    } catch {
      // Ignored
    }
  };

  const cancelAllReminders = async () => {
    try {
      const Notifications = await loadNotifications();
      if (!Notifications) return;
      await Notifications.cancelAllScheduledNotificationsAsync();
    } catch {
      // Ignored
    }
  };

  return {
    permissionGranted,
    scheduleLocalReminder,
    scheduleDoseWithEscalation,
    cancelDoseEscalation,
    rebuildAllDoseReminders,
    cancelReminder,
    cancelAllReminders,
  };
};
