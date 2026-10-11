export interface ColorPalette {
  primary: string;
  primaryLight: string;
  primaryDark: string;
  secondary: string;
  secondaryLight: string;
  secondaryDark: string;
  accent: string;
  
  // Statuses
  success: string;
  successLight: string;
  warning: string;
  warningLight: string;
  error: string;
  errorLight: string;
  info: string;
  infoLight: string;
  
  // Neutral / Backgrounds
  background: string;
  surface: string;
  card: string;
  cardBorder: string;
  divider: string;
  
  // Text
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  textInverse: string;
  
  // Inputs
  inputBg: string;
  inputBorder: string;
  inputBorderFocus: string;
  placeholder: string;
  
  // Action buttons
  buttonPrimaryText: string;
  buttonSecondaryBg: string;
  buttonSecondaryText: string;

  // Medical specific
  doseTaken: string;
  doseDue: string;
  doseMissed: string;
  doseLate: string;
  pharmacyAvailable: string;
  pharmacyUnavailable: string;
  pharmacyUnknown: string;
}

export const lightColors: ColorPalette = {
  primary: '#0284C7', // Clinical Deep Cyan/Blue
  primaryLight: '#E0F2FE',
  primaryDark: '#0369A1',
  secondary: '#0D9488', // Medical Teal
  secondaryLight: '#CCFBF1',
  secondaryDark: '#0F766E',
  accent: '#6366F1',

  success: '#10B981',
  successLight: '#ECFDF5',
  warning: '#F59E0B',
  warningLight: '#FFFBEB',
  error: '#EF4444',
  errorLight: '#FEF2F2',
  info: '#3B82F6',
  infoLight: '#EFF6FF',

  background: '#F8FAFC',
  surface: '#FFFFFF',
  card: '#FFFFFF',
  cardBorder: '#E2E8F0',
  divider: '#F1F5F9',

  textPrimary: '#0F172A',
  textSecondary: '#475569',
  textMuted: '#94A3B8',
  textInverse: '#FFFFFF',

  inputBg: '#F8FAFC',
  inputBorder: '#CBD5E1',
  inputBorderFocus: '#0284C7',
  placeholder: '#94A3B8',

  buttonPrimaryText: '#FFFFFF',
  buttonSecondaryBg: '#F1F5F9',
  buttonSecondaryText: '#0F172A',

  doseTaken: '#10B981',
  doseDue: '#F59E0B',
  doseMissed: '#EF4444',
  doseLate: '#EAB308',
  pharmacyAvailable: '#10B981',
  pharmacyUnavailable: '#EF4444',
  pharmacyUnknown: '#94A3B8',
};

export const darkColors: ColorPalette = {
  primary: '#38BDF8',
  primaryLight: '#082F49',
  primaryDark: '#0284C7',
  secondary: '#2DD4BF',
  secondaryLight: '#134E4A',
  secondaryDark: '#0D9488',
  accent: '#818CF8',

  success: '#34D399',
  successLight: '#064E3B',
  warning: '#FBBF24',
  warningLight: '#451A03',
  error: '#F87171',
  errorLight: '#450A0A',
  info: '#60A5FA',
  infoLight: '#1E3A8A',

  background: '#0B0F19',
  surface: '#111827',
  card: '#1F2937',
  cardBorder: '#374151',
  divider: '#1F2937',

  textPrimary: '#F9FAFB',
  textSecondary: '#D1D5DB',
  textMuted: '#6B7280',
  textInverse: '#111827',

  inputBg: '#1F2937',
  inputBorder: '#374151',
  inputBorderFocus: '#38BDF8',
  placeholder: '#6B7280',

  buttonPrimaryText: '#0B0F19',
  buttonSecondaryBg: '#374151',
  buttonSecondaryText: '#F9FAFB',

  doseTaken: '#34D399',
  doseDue: '#FBBF24',
  doseMissed: '#F87171',
  doseLate: '#FCD34D',
  pharmacyAvailable: '#34D399',
  pharmacyUnavailable: '#F87171',
  pharmacyUnknown: '#6B7280',
};
