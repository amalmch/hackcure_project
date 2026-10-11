import { apiClient } from './client';
import { AppNotification, PaginatedResponse } from '../../types';

export const notificationsApi = {
  getNotifications: async (page: number = 1, limit: number = 20): Promise<PaginatedResponse<AppNotification>> => {
    const response = await apiClient.get<PaginatedResponse<AppNotification>>('/api/v1/notifications', {
      params: { page, limit },
    });
    return response.data;
  },

  markAsRead: async (id: string): Promise<AppNotification> => {
    const response = await apiClient.put<AppNotification>(`/api/v1/notifications/${id}/read`);
    return response.data;
  },

  markAllAsRead: async (): Promise<{ count: number }> => {
    const response = await apiClient.put<{ count: number }>('/api/v1/notifications/read-all');
    return response.data;
  },

  getUnreadCount: async (): Promise<{ unread_count: number }> => {
    const response = await apiClient.get<{ unread_count: number }>('/api/v1/notifications/unread-count');
    return response.data;
  },
};
