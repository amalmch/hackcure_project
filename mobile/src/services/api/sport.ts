import { apiClient } from './client';
import { SportPlan, SportActivity } from '../../types';

export const sportApi = {
  getPlans: async (): Promise<SportPlan[]> => {
    const response = await apiClient.get<SportPlan[]>('/api/v1/patients/me/sport/plans');
    return response.data;
  },

  getTodayActivities: async (): Promise<SportActivity[]> => {
    const response = await apiClient.get<SportActivity[]>('/api/v1/patients/me/sport/today');
    return response.data;
  },

  startActivity: async (activityId: string): Promise<SportActivity> => {
    const response = await apiClient.post<SportActivity>(`/api/v1/sport-activities/${activityId}/start`);
    return response.data;
  },

  completeActivity: async (activityId: string, durationMinutes?: number, notes?: string): Promise<SportActivity> => {
    const response = await apiClient.post<SportActivity>(`/api/v1/sport-activities/${activityId}/complete`, {
      duration_minutes: durationMinutes,
      notes,
    });
    return response.data;
  },
};
