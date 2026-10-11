import { apiClient } from './client';
import { MedicationDose, PrescriptionItem } from '../../types';

export const medicationsApi = {
  getMedications: async (): Promise<PrescriptionItem[]> => {
    const response = await apiClient.get<PrescriptionItem[]>('/api/v1/patients/me/medications');
    return response.data;
  },

  getMedicationById: async (id: string): Promise<PrescriptionItem> => {
    const response = await apiClient.get<PrescriptionItem>(`/api/v1/patients/me/medications/${id}`);
    return response.data;
  },

  getTodayDoses: async (): Promise<MedicationDose[]> => {
    const response = await apiClient.get<MedicationDose[]>('/api/v1/patients/me/doses/today');
    return response.data;
  },

  getDosesByDate: async (date: string): Promise<MedicationDose[]> => {
    const response = await apiClient.get<MedicationDose[]>('/api/v1/patients/me/doses', {
      params: { date },
    });
    return response.data;
  },

  takeDose: async (
    doseId: string,
    idempotencyKey?: string,
    takenAt?: string
  ): Promise<MedicationDose> => {
    const response = await apiClient.post<MedicationDose>(`/api/v1/medication-doses/${doseId}/take`, {
      idempotency_key: idempotencyKey,
      taken_at: takenAt || new Date().toISOString(),
    });
    return response.data;
  },

  missDose: async (doseId: string, notes?: string): Promise<MedicationDose> => {
    const response = await apiClient.post<MedicationDose>(`/api/v1/medication-doses/${doseId}/miss`, {
      notes,
    });
    return response.data;
  },

  getDoseHistory: async (days: number = 14): Promise<MedicationDose[]> => {
    const response = await apiClient.get<MedicationDose[]>('/api/v1/patients/me/doses/history', {
      params: { days },
    });
    return response.data;
  },
};

