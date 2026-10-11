import type { TFunction } from 'i18next';

export type ApiErrorContext = 'login' | 'registration' | 'generic';

export function localizedApiError(error: unknown, t: TFunction, context: ApiErrorContext = 'generic'): string {
  const response = (error as { response?: { status?: number } } | null)?.response;
  const status = response?.status;

  if (!response) return t('common.serverUnavailable');
  if (status === 401 && context === 'login') return t('auth.loginError');
  if (status === 409 || status === 400 && context === 'registration') return t('auth.emailAlreadyRegistered');
  if (status === 422) return context === 'registration' ? t('auth.invalidRegistration') : t('common.invalidForm');
  if (context === 'registration') return t('auth.registrationError');
  if (context === 'login') return t('auth.loginError');
  return t('common.error');
}
