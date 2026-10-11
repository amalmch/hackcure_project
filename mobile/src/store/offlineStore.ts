import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { PendingDoseRecord, PendingMessage } from '../types';
import { STORAGE_KEYS } from '../constants';
import { medicationsApi } from '../services/api/medications';
import { conversationsApi } from '../services/api/conversations';

interface OfflineState {
  isOnline: boolean;
  isSyncing: boolean;
  pendingDoses: PendingDoseRecord[];
  pendingMessages: PendingMessage[];

  setIsOnline: (online: boolean) => void;
  loadQueue: () => Promise<void>;
  queueDoseTake: (doseId: string, idempotencyKey: string) => Promise<void>;
  queueMessage: (conversationId: string, content: string, localId: string) => Promise<void>;
  syncAll: () => Promise<{ syncedDoses: number; syncedMessages: number }>;
}

export const useOfflineStore = create<OfflineState>((set, get) => ({
  isOnline: true,
  isSyncing: false,
  pendingDoses: [],
  pendingMessages: [],

  setIsOnline: (online: boolean) => {
    set({ isOnline: online });
    if (online) {
      get().syncAll();
    }
  },

  loadQueue: async () => {
    try {
      const stored = await AsyncStorage.getItem(STORAGE_KEYS.OFFLINE_QUEUE);
      if (stored) {
        const parsed = JSON.parse(stored);
        set({
          pendingDoses: parsed.pendingDoses || [],
          pendingMessages: parsed.pendingMessages || [],
        });
      }
    } catch {
      // Ignored
    }
  },

  queueDoseTake: async (doseId: string, idempotencyKey: string) => {
    const newRecord: PendingDoseRecord = {
      dose_id: doseId,
      taken_at: new Date().toISOString(),
      idempotency_key: idempotencyKey,
      created_at: new Date().toISOString(),
    };

    const updated = [...get().pendingDoses, newRecord];
    set({ pendingDoses: updated });

    await AsyncStorage.setItem(
      STORAGE_KEYS.OFFLINE_QUEUE,
      JSON.stringify({
        pendingDoses: updated,
        pendingMessages: get().pendingMessages,
      })
    );
  },

  queueMessage: async (conversationId: string, content: string, localId: string) => {
    const newMsg: PendingMessage = {
      conversation_id: conversationId,
      content,
      local_id: localId,
      created_at: new Date().toISOString(),
    };

    const updated = [...get().pendingMessages, newMsg];
    set({ pendingMessages: updated });

    await AsyncStorage.setItem(
      STORAGE_KEYS.OFFLINE_QUEUE,
      JSON.stringify({
        pendingDoses: get().pendingDoses,
        pendingMessages: updated,
      })
    );
  },

  syncAll: async () => {
    const { isSyncing, pendingDoses, pendingMessages } = get();
    if (isSyncing || (!pendingDoses.length && !pendingMessages.length)) {
      return { syncedDoses: 0, syncedMessages: 0 };
    }

    set({ isSyncing: true });
    let syncedDoses = 0;
    let syncedMessages = 0;

    const remainingDoses: PendingDoseRecord[] = [];
    for (const dose of pendingDoses) {
      try {
        await medicationsApi.takeDose(dose.dose_id, dose.idempotency_key, dose.taken_at);
        syncedDoses += 1;
      } catch (err: any) {
        // If 409 conflict, it means already recorded on server via idempotency
        if (err?.response?.status === 409) {
          syncedDoses += 1;
        } else {
          remainingDoses.push(dose);
        }
      }
    }

    const remainingMessages: PendingMessage[] = [];
    for (const msg of pendingMessages) {
      try {
        await conversationsApi.sendMessage(msg.conversation_id, msg.content);
        syncedMessages += 1;
      } catch {
        remainingMessages.push(msg);
      }
    }

    set({
      pendingDoses: remainingDoses,
      pendingMessages: remainingMessages,
      isSyncing: false,
    });

    await AsyncStorage.setItem(
      STORAGE_KEYS.OFFLINE_QUEUE,
      JSON.stringify({
        pendingDoses: remainingDoses,
        pendingMessages: remainingMessages,
      })
    );

    return { syncedDoses, syncedMessages };
  },
}));
