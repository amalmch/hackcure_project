import { apiClient } from './client';

export interface SakinaMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface SakinaEmergencyNumber {
  label: string;
  number: string;
}

export interface SakinaReply {
  reply: string;
  crisis: boolean;
  fallback: boolean;
  emergency_numbers: SakinaEmergencyNumber[];
}

export const sakinaApi = {
  send: async (history: SakinaMessage[]) =>
    (await apiClient.post<SakinaReply>('/api/chat', { history }, { timeout: 70000 })).data,
};
