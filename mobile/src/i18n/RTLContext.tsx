import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';
import { I18nManager, ViewStyle, TextStyle } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import i18n from './index';
import { STORAGE_KEYS } from '../constants';

export type SupportedLanguage = 'en' | 'fr' | 'ar';

interface RTLContextType {
  language: SupportedLanguage;
  isRTL: boolean;
  changeLanguage: (lang: SupportedLanguage) => Promise<void>;
  textAlign: TextStyle['textAlign'];
  flexDirection: ViewStyle['flexDirection'];
  rowReverse: ViewStyle['flexDirection'];
  transformFlip: ViewStyle['transform'];
}

const RTLContext = createContext<RTLContextType | undefined>(undefined);

export const RTLProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguageState] = useState<SupportedLanguage>(() => {
    const currentLang = i18n.language?.substring(0, 2);
    return currentLang === 'ar' || currentLang === 'fr' ? currentLang : 'en';
  });

  useEffect(() => {
    const updateLanguage = (value: string) => {
      const currentLang = value.substring(0, 2);
      setLanguageState(currentLang === 'ar' || currentLang === 'fr' ? currentLang : 'en');
    };
    i18n.on('languageChanged', updateLanguage);
    return () => { i18n.off('languageChanged', updateLanguage); };
  }, []);

  const isRTL = useMemo(() => language === 'ar', [language]);

  const changeLanguage = async (newLang: SupportedLanguage) => {
    setLanguageState(newLang);
    await i18n.changeLanguage(newLang);
    await AsyncStorage.setItem(STORAGE_KEYS.LANGUAGE, newLang);
    
    // In React Native Expo, we ensure I18nManager matches if reload occurs
    const shouldBeRTL = newLang === 'ar';
    if (I18nManager.isRTL !== shouldBeRTL) {
      I18nManager.allowRTL(shouldBeRTL);
      I18nManager.forceRTL(shouldBeRTL);
    }
  };

  const textAlign: TextStyle['textAlign'] = isRTL ? 'right' : 'left';
  const flexDirection: ViewStyle['flexDirection'] = isRTL ? 'row-reverse' : 'row';
  const rowReverse: ViewStyle['flexDirection'] = isRTL ? 'row' : 'row-reverse';
  const transformFlip: ViewStyle['transform'] = isRTL ? [{ scaleX: -1 }] : [];

  return (
    <RTLContext.Provider
      value={{
        language,
        isRTL,
        changeLanguage,
        textAlign,
        flexDirection,
        rowReverse,
        transformFlip,
      }}
    >
      {children}
    </RTLContext.Provider>
  );
};

export const useRTL = (): RTLContextType => {
  const context = useContext(RTLContext);
  if (!context) {
    throw new Error('useRTL must be used within an RTLProvider');
  }
  return context;
};
