import { useEffect, useState } from 'react';
import { useOfflineStore } from '../store/offlineStore';
import { API_BASE_URL } from '../constants';

export const useNetworkStatus = () => {
  const isOnline = useOfflineStore((state) => state.isOnline);
  const setIsOnline = useOfflineStore((state) => state.setIsOnline);
  const [lastCheck, setLastCheck] = useState<Date>(new Date());

  useEffect(() => {
    let active = true;
    const checkBackend = async () => {
      let reachable = false;
      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      try {
        const controller = new AbortController();
        timeoutId = setTimeout(() => controller.abort(), 4000);
        const response = await fetch(`${API_BASE_URL}/health`, {
          method: 'GET',
          signal: controller.signal,
        });
        reachable = response.ok;
      } catch {
        reachable = false;
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
      }
      if (active) {
        if (useOfflineStore.getState().isOnline !== reachable) setIsOnline(reachable);
        setLastCheck(new Date());
      }
    };

    void checkBackend();
    const interval = setInterval(() => { void checkBackend(); }, 15000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [setIsOnline]);

  return { isOnline, lastCheck };
};
