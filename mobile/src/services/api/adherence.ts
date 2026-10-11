import { apiClient } from './client';
import { AdherenceStats } from '../../types';

export const adherenceApi = {
  getStats: async (): Promise<AdherenceStats> => {
    const response = await apiClient.get<AdherenceStats>('/api/v1/patients/me/adherence');
    return response.data;
  },

  getHistory: async (period: 'week' | 'month' = 'week'): Promise<AdherenceStats['weekly']['daily_breakdown']> => {
    const response = await apiClient.get<AdherenceStats['weekly']['daily_breakdown']>(
      '/api/v1/patients/me/adherence/history',
      {
        params: { period },
      }
    );
    return response.data;
  },
};
