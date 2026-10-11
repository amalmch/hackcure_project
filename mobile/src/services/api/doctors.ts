import { apiClient } from './client';
import { Doctor } from '../../types';

export const doctorsApi = {
  getMyDoctors: async (): Promise<Doctor[]> => {
    const response = await apiClient.get<Doctor[]>('/api/v1/patients/me/doctors');
    return response.data;
  },

  getById: async (id: string): Promise<Doctor> => {
    const response = await apiClient.get<Doctor>(`/api/v1/doctors/${id}`);
    return response.data;
  },
};
