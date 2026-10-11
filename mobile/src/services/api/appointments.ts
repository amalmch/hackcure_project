import { apiClient } from './client';
import { Appointment } from '../../types';

export const appointmentsApi = {
  getAppointments: async (): Promise<Appointment[]> => {
    const response = await apiClient.get<Appointment[]>('/api/v1/appointments');
    return response.data;
  },

  getById: async (id: string): Promise<Appointment> => {
    const response = await apiClient.get<Appointment>(`/api/v1/appointments/${id}`);
    return response.data;
  },

  cancelAppointment: async (id: string, reason?: string): Promise<Appointment> => {
    const response = await apiClient.post<Appointment>(`/api/v1/appointments/${id}/cancel`, {
      cancellation_reason: reason,
    });
    return response.data;
  },
};
