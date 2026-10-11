import { apiClient } from './client';
import { MedicalRecord } from '../../types';

export const medicalRecordsApi = {
  getRecords: async (): Promise<MedicalRecord[]> => {
    const response = await apiClient.get<MedicalRecord[]>('/api/v1/medical-records');
    return response.data;
  },

  getById: async (id: string): Promise<MedicalRecord> => {
    const response = await apiClient.get<MedicalRecord>(`/api/v1/medical-records/${id}`);
    return response.data;
  },
};
