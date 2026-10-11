import { apiClient } from './client';

export interface CompanionConsent {
  chat_consent: boolean;
  share_with_doctor: boolean;
  updated_at?: string;
}
export interface CompanionConversation { id: string; created_at: string; updated_at: string }
export interface CompanionMessage {
  id: string; conversation_id: string; role: 'user' | 'assistant'; content: string;
  triage_label?: string | null; created_at: string;
  fallback?: boolean; error_code?: string | null;
}
export interface EmergencyContact { label: string; number: string }

export const companionApi = {
  consent: async () => (await apiClient.get<CompanionConsent>('/api/v1/chat/consent')).data,
  updateConsent: async (chat_consent: boolean, share_with_doctor: boolean) =>
    (await apiClient.put<CompanionConsent>('/api/v1/chat/consent', { chat_consent, share_with_doctor })).data,
  conversations: async () => (await apiClient.get<CompanionConversation[]>('/api/v1/chat/conversations')).data,
  messages: async (id: string) => (await apiClient.get<CompanionMessage[]>(`/api/v1/chat/conversations/${id}/messages`)).data,
  createConversation: async () => (await apiClient.post<CompanionConversation>('/api/v1/chat/conversations')).data,
  send: async (conversation_id: string, content: string, client_message_id: string) =>
    (await apiClient.post<CompanionMessage>(
      '/api/v1/chat/messages', { conversation_id, content, client_message_id }, { timeout: 70000 },
    )).data,
  addMood: async (mood: number) => (await apiClient.post('/api/v1/chat/moods', { mood })).data,
  emergencyContacts: async () => (await apiClient.get<{ country: string; numbers: EmergencyContact[] }>('/api/v1/chat/emergency-contacts')).data,
};
