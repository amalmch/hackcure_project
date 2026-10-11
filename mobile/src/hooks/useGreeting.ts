import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

export const useGreeting = () => {
  const { t } = useTranslation();

  return useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 12) {
      return t('home.goodMorning');
    }
    if (hour < 18) {
      return t('home.goodAfternoon');
    }
    return t('home.goodEvening');
  }, [t]);
};
