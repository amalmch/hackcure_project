import i18n from '../i18n';
import { AppNotification } from '../types';

export function localizedNotificationText(notification: AppNotification): { title: string; body: string } {
  const { title, body = '' } = notification;

  if (title === 'Daily wellbeing check-in') {
    return { title: i18n.t('notifications.dailyCheckInTitle'), body: i18n.t('notifications.dailyCheckInBody') };
  }
  if (title === 'Active Prescription Ready') {
    const count = Number(body.match(/(\d+) medications prescribed/i)?.[1] || 0);
    return { title: i18n.t('notifications.prescriptionReadyTitle'), body: i18n.t('notifications.prescriptionReadyBody', { count }) };
  }
  const reminder = title.match(/^Medication Reminder:\s*(.+)$/i);
  if (reminder) {
    const mealDose = body.match(/^Your (.+?) dose is due\./i);
    const fullDose = body.match(/^It is time to take your (.+?) with (.+)\.$/i);
    if (mealDose) return { title: i18n.t('notifications.medicationReminderTitle', { name: reminder[1] }), body: i18n.t('notifications.medicationMealReminderBody', { meal: mealDose[1] }) };
    if (fullDose) return { title: i18n.t('notifications.medicationReminderTitle', { name: reminder[1] }), body: i18n.t('notifications.medicationWithMealBody', { dose: fullDose[1], meal: fullDose[2] }) };
  }
  const newMessage = title.match(/^New message from (.+)$/i);
  if (newMessage) {
    const knownBody = body === 'Your doctor has replied to your message. Open the app to read their response.'
      ? i18n.t('notifications.newDoctorMessageBody')
      : body;
    return { title: i18n.t('notifications.newDoctorMessageTitle', { doctor: newMessage[1] }), body: knownBody };
  }
  const confirmed = title === 'Upcoming Appointment Confirmed';
  if (confirmed) {
    const appointment = body.match(/^Your appointment with (.+) is confirmed for (.+)\.$/i);
    if (appointment) return { title: i18n.t('notifications.appointmentConfirmedTitle'), body: i18n.t('notifications.appointmentConfirmedBody', { doctor: appointment[1], date: appointment[2] }) };
  }
  return { title, body };
}
