import i18n from '../i18n';

const LABEL_KEYS: Record<string, string> = {
  ACTIVE: 'labels.active', COMPLETED: 'labels.completed', CANCELLED: 'labels.cancelled', MODIFIED: 'labels.modified',
  SCHEDULED: 'labels.scheduled', CONFIRMED: 'labels.confirmed', NO_SHOW: 'labels.noShow', DUE: 'labels.due',
  REMINDING: 'labels.reminding', TAKEN_ON_TIME: 'labels.takenOnTime', TAKEN_LATE: 'labels.takenLate', MISSED: 'labels.missed',
  IN_PROGRESS: 'labels.inProgress', MEDICATION: 'labels.medication', MEDICATIONS: 'labels.medications',
  SPORT: 'labels.sport', NUTRITION: 'labels.nutrition', APPOINTMENT: 'labels.appointment', MEDICAL_RECORD: 'labels.medicalRecord', OTHER: 'labels.other',
  DIAGNOSIS: 'labels.diagnosis', LAB_RESULT: 'labels.labResult', IMAGING: 'labels.imaging', PROCEDURE: 'labels.procedure',
  VISIT_NOTE: 'labels.visitNote', DOCUMENT: 'labels.document',
};

export function medicalLabel(value?: string | null): string {
  if (!value) return '';
  const key = LABEL_KEYS[value.toUpperCase()];
  return key ? i18n.t(key) : value;
}
