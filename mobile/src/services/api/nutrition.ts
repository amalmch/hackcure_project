import { apiClient } from './client';
import { NutritionPlan } from '../../types';

export const nutritionApi = {
  getPlans: async (): Promise<NutritionPlan[]> => {
    const response = await apiClient.get<NutritionPlan[]>('/api/v1/patients/me/nutrition');
    return response.data;
  },

  getPlanById: async (id: string): Promise<NutritionPlan> => {
    const response = await apiClient.get<NutritionPlan>(`/api/v1/patients/me/nutrition/${id}`);
    return response.data;
  },
};
