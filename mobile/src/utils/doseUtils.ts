import { MedicationDose, DoseStatus } from '../types';
import { DOSE_STATUS_CONFIG } from '../constants';

export const getDoseStatusColor = (status: DoseStatus): string => {
  return DOSE_STATUS_CONFIG[status]?.color || '#94A3B8';
};

export const getDoseStatusBgColor = (status: DoseStatus): string => {
  return DOSE_STATUS_CONFIG[status]?.bgColor || '#F1F5F9';
};

export const getDoseStatusIcon = (status: DoseStatus): string => {
  return DOSE_STATUS_CONFIG[status]?.icon || 'help-circle';
};

export const groupDosesByTimeOfDay = (doses: MedicationDose[]) => {
  const groups: {
    morning: MedicationDose[];
    afternoon: MedicationDose[];
    evening: MedicationDose[];
    night: MedicationDose[];
  } = {
    morning: [],
    afternoon: [],
    evening: [],
    night: [],
  };

  doses.forEach((dose) => {
    const hours = parseInt(dose.scheduled_time.split(':')[0], 10);
    if (hours >= 5 && hours < 12) {
      groups.morning.push(dose);
    } else if (hours >= 12 && hours < 17) {
      groups.afternoon.push(dose);
    } else if (hours >= 17 && hours < 22) {
      groups.evening.push(dose);
    } else {
      groups.night.push(dose);
    }
  });

  return groups;
};

export const calculateAdherencePercentage = (doses: MedicationDose[]): number => {
  if (!doses || doses.length === 0) return 100;
  const taken = doses.filter(
    (d) => d.status === DoseStatus.TAKEN_ON_TIME || d.status === DoseStatus.TAKEN_LATE
  ).length;
  return Math.round((taken / doses.length) * 100);
};
