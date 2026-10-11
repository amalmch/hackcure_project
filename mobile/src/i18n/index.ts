import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import * as Localization from 'expo-localization';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { en } from './locales/en';
import { fr } from './locales/fr';
import { ar } from './locales/ar';
import { STORAGE_KEYS } from '../constants';

const resources = {
  en: { translation: en },
  fr: { translation: fr },
  ar: { translation: ar },
};

const initI18n = async () => {
  let savedLanguage = 'fr';
  try {
    const stored = await AsyncStorage.getItem(STORAGE_KEYS.LANGUAGE);
    if (stored && (stored === 'en' || stored === 'fr' || stored === 'ar')) {
      savedLanguage = stored;
    } else {
      const locales = Localization.getLocales();
      const deviceLang = locales[0]?.languageCode || 'en';
      if (deviceLang === 'ar') savedLanguage = 'ar';
      else if (deviceLang === 'fr') savedLanguage = 'fr';
      else savedLanguage = 'en';
    }
  } catch {
    savedLanguage = 'en';
  }

  await i18n.use(initReactI18next).init({
    resources,
    lng: savedLanguage,
    fallbackLng: 'fr',
    interpolation: {
      escapeValue: false,
    },
    compatibilityJSON: 'v4',
  });
};

initI18n();

export default i18n;
