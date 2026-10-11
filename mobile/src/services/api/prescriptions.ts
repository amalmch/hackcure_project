import { apiClient } from './client';
import { Prescription } from '../../types';

export const prescriptionsApi = {
  getPrescriptions: async (): Promise<Prescription[]> => {
    const response = await apiClient.get<Prescription[]>('/api/v1/patients/me/prescriptions');
    return response.data;
  },

  getActivePrescriptions: async (): Promise<Prescription[]> => {
    const response = await apiClient.get<Prescription[]>('/api/v1/patients/me/prescriptions/active');
    return response.data;
  },

  getPrescriptionById: async (id: string): Promise<Prescription> => {
    const response = await apiClient.get<Prescription>(`/api/v1/prescriptions/${id}`);
    return response.data;
  },
};
