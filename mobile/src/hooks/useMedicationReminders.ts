import { useCallback } from 'react';
import i18n from '../i18n';
import { MedicationDose, DoseStatus } from '../types';
import { useNotifications } from './useNotifications';

export const useMedicationReminders = () => {
  const { scheduleLocalReminder, cancelAllReminders } = useNotifications();

  const syncRemindersForDoses = useCallback(
    async (doses: MedicationDose[]) => {
      // Clear obsolete scheduled notifications first to prevent duplicates
      await cancelAllReminders();

      const now = new Date();

      for (const dose of doses) {
        // Only schedule for doses that haven't been completed or cancelled
        if (
          dose.status === DoseStatus.TAKEN_ON_TIME ||
          dose.status === DoseStatus.TAKEN_LATE ||
          dose.status === DoseStatus.CANCELLED ||
          dose.status === DoseStatus.MISSED
        ) {
          continue;
        }

        // Parse scheduled time for today
        const [hours, minutes] = dose.scheduled_time.split(':').map(Number);
        const scheduledDateTime = new Date();
        scheduledDateTime.setHours(hours, minutes, 0, 0);

        const medName = dose.prescription_item?.medication_name || i18n.t('copy.patient');
        const dosage = dose.prescription_item?.dosage || '';

        // 1. Initial due reminder
        if (scheduledDateTime > now) {
          await scheduleLocalReminder(
            i18n.t('notifications.medicationReminderTitle', { name: medName }),
            i18n.t('notifications.medicationReminderBody', { dosage }),
            scheduledDateTime,
            { screen: '/(tabs)/treatment', doseId: dose.id }
          );
        }

        // 2. Escalation reminders (up to max_reminders, every reminder_interval_minutes)
        const maxReminders = dose.max_reminders || 2;
        const intervalMins = dose.reminder_interval_minutes || 45;

        for (let i = 1; i <= maxReminders; i++) {
          const escalationTime = new Date(scheduledDateTime.getTime() + i * intervalMins * 60000);
          if (escalationTime > now) {
            await scheduleLocalReminder(
              i18n.t('notifications.medicationEscalationTitle', { count: i, name: medName, dosage }),
              i18n.t('notifications.medicationEscalationBody'),
              escalationTime,
              { screen: '/(tabs)/treatment', doseId: dose.id, escalationStep: i }
            );
          }
        }
      }
    },
    [scheduleLocalReminder, cancelAllReminders]
  );

  return { syncRemindersForDoses };
};
