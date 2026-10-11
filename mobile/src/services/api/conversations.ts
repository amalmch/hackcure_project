import { apiClient } from './client';
import { Conversation, Message, ConversationCategory } from '../../types';

export interface CreateConversationPayload {
  doctor_id: string;
  category: ConversationCategory;
  subject?: string;
  initial_message: string;
}

export const conversationsApi = {
  getConversations: async (): Promise<Conversation[]> => {
    const response = await apiClient.get<Conversation[]>('/api/v1/conversations');
    return response.data;
  },

  createConversation: async (payload: CreateConversationPayload): Promise<Conversation> => {
    const response = await apiClient.post<Conversation>('/api/v1/conversations', payload);
    return response.data;
  },

  getMessages: async (conversationId: string, page: number = 1, limit: number = 50): Promise<Message[]> => {
    const response = await apiClient.get<Message[]>(`/api/v1/conversations/${conversationId}/messages`, {
      params: { page, limit },
    });
    return response.data;
  },

  sendMessage: async (conversationId: string, content: string): Promise<Message> => {
    const response = await apiClient.post<Message>(`/api/v1/conversations/${conversationId}/messages`, {
      content,
    });
    return response.data;
  },
};
