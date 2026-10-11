import { useEffect } from 'react';
import { useOfflineStore } from '../store/offlineStore';
import { useNetworkStatus } from './useNetworkStatus';

export const useOfflineSync = () => {
  const { isOnline } = useNetworkStatus();
  const syncAll = useOfflineStore((state) => state.syncAll);
  const isSyncing = useOfflineStore((state) => state.isSyncing);
  const pendingDoses = useOfflineStore((state) => state.pendingDoses);
  const pendingMessages = useOfflineStore((state) => state.pendingMessages);

  useEffect(() => {
    if (isOnline && (pendingDoses.length > 0 || pendingMessages.length > 0)) {
      syncAll();
    }
  }, [isOnline, pendingDoses.length, pendingMessages.length, syncAll]);

  return {
    isOnline,
    isSyncing,
    pendingDosesCount: pendingDoses.length,
    pendingMessagesCount: pendingMessages.length,
    syncNow: syncAll,
  };
};
