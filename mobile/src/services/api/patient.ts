import { apiClient } from './client';
import { Patient, DashboardData, TreatmentSummary } from '../../types';

export interface UpdatePatientPayload {
  first_name?: string;
  last_name?: string;
  emergency_contact_name?: string;
  emergency_contact_phone?: string;
  address?: string;
  avatar_url?: string;
}

export const patientApi = {
  getProfile: async (): Promise<Patient> => {
    const response = await apiClient.get<Patient>('/api/v1/patients/me');
    return response.data;
  },

  updateProfile: async (payload: UpdatePatientPayload): Promise<Patient> => {
    const response = await apiClient.put<Patient>('/api/v1/patients/me', payload);
    return response.data;
  },

  getDashboard: async (): Promise<DashboardData> => {
    const response = await apiClient.get<DashboardData>('/api/v1/patients/me/dashboard');
    return response.data;
  },

  getTreatmentSummary: async (): Promise<TreatmentSummary | null> => {
    try {
      const response = await apiClient.get<TreatmentSummary>('/api/v1/patients/me/treatment-summary');
      return response.data;
    } catch (e: any) {
      if (e?.response?.status === 404) return null;
      throw e;
    }
  },

  getAutomationDrafts: async (): Promise<any[]> => {
    try {
      const response = await apiClient.get<any[]>('/api/v1/patients/me/automation/drafts');
      return response.data;
    } catch {
      return [];
    }
  },

  applyAutomationDrafts: async (documentSourceIds: string[]): Promise<any> => {
    const response = await apiClient.post<any>('/api/v1/patients/me/automation/apply', {
      document_source_ids: documentSourceIds,
      confirmed_by: 'patient',
    });
    return response.data;
  },
};

