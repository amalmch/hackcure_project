import { apiClient } from './client';
import { Pharmacy, MedicineAvailability } from '../../types';

export const pharmaciesApi = {
  getNearby: async (latitude: number, longitude: number, radiusKm: number = 10): Promise<Pharmacy[]> => {
    const response = await apiClient.get<Pharmacy[]>('/api/v1/pharmacies/nearby', {
      params: { lat: latitude, lng: longitude, radius: radiusKm },
    });
    return response.data;
  },

  getById: async (id: string): Promise<Pharmacy> => {
    const response = await apiClient.get<Pharmacy>(`/api/v1/pharmacies/${id}`);
    return response.data;
  },

  search: async (query: string): Promise<Pharmacy[]> => {
    const response = await apiClient.get<Pharmacy[]>('/api/v1/pharmacies/search', {
      params: { q: query },
    });
    return response.data;
  },

  getMedicineAvailability: async (
    medicationName: string,
    latitude?: number,
    longitude?: number
  ): Promise<MedicineAvailability[]> => {
    const response = await apiClient.get<MedicineAvailability[]>(
      `/api/v1/medicines/${encodeURIComponent(medicationName)}/availability`,
      {
        params: { lat: latitude, lng: longitude },
      }
    );
    return response.data;
  },
};
