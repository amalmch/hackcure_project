import { format, parseISO, isToday as isDateToday, isPast as isDatePast, isFuture as isDateFuture } from 'date-fns';
import { fr } from 'date-fns/locale/fr';
import { enUS } from 'date-fns/locale/en-US';
import { arSA } from 'date-fns/locale/ar-SA';
import i18n from '../i18n';

const getDateLocale = () => {
  const language = i18n.language?.split('-')[0];
  if (language === 'fr') return fr;
  if (language === 'ar') return arSA;
  return enUS;
};

export const formatDate = (dateString?: string | null, formatStr: string = 'd MMMM yyyy'): string => {
  if (!dateString) return '';
  try {
    const parsed = typeof dateString === 'string' ? parseISO(dateString) : dateString;
    return format(parsed, formatStr, { locale: getDateLocale() });
  } catch {
    return dateString;
  }
};

export const formatTime = (timeString?: string | null): string => {
  if (!timeString) return '';
  // Check if it's already HH:mm
  if (/^\d{2}:\d{2}(:\d{2})?$/.test(timeString)) {
    const normalized = timeString.substring(0, 5);
    return i18n.language?.startsWith('fr') ? normalized.replace(':', 'h') : normalized;
  }
  try {
    const parsed = parseISO(timeString);
    const formatted = format(parsed, 'HH:mm', { locale: getDateLocale() });
    return i18n.language?.startsWith('fr') ? formatted.replace(':', 'h') : formatted;
  } catch {
    return timeString;
  }
};

export const formatDateTime = (dateString?: string | null): string => {
  if (!dateString) return '';
  try {
    const parsed = parseISO(dateString);
    const date = format(parsed, 'd MMMM yyyy', { locale: getDateLocale() });
    const time = format(parsed, 'HH:mm', { locale: getDateLocale() });
    return i18n.language?.startsWith('fr') ? `${date} à ${time.replace(':', 'h')}` : `${date}, ${time}`;
  } catch {
    return dateString;
  }
};

const TUNIS_TIME_ZONE = 'Africa/Tunis';

const parseUtcTimestamp = (value: string): Date => {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T12:00:00Z`);
  // Older companion rows are naive UTC: companion timestamps have always been
  // created with datetime.utcnow() and SQLite discarded timezone metadata.
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasOffset ? value : `${value}Z`);
};

const zonedDateParts = (date: Date) => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TUNIS_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '0';
  const year = Number(get('year'));
  const month = Number(get('month'));
  const day = Number(get('day'));
  return { year, month, day, key: `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}` };
};

export const formatCompanionDateTime = (value?: string | null, now = new Date()): string => {
  if (!value) return '';
  const parsed = parseUtcTimestamp(value);
  if (!Number.isFinite(parsed.getTime())) return value;
  const locale = i18n.language?.startsWith('fr') ? 'fr-FR' : i18n.language?.startsWith('ar') ? 'ar-TN' : 'en-GB';
  const targetParts = zonedDateParts(parsed);
  const todayParts = zonedDateParts(now);
  const targetDay = Date.UTC(targetParts.year, targetParts.month - 1, targetParts.day);
  const today = Date.UTC(todayParts.year, todayParts.month - 1, todayParts.day);
  const dayOffset = Math.round((today - targetDay) / 86_400_000);
  const time = new Intl.DateTimeFormat(locale, {
    timeZone: TUNIS_TIME_ZONE, hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(parsed).replace(':', i18n.language?.startsWith('fr') ? 'h' : ':');
  const relative = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  const dayLabel = dayOffset >= 0 && dayOffset <= 1
    ? relative.format(-dayOffset, 'day')
    : new Intl.DateTimeFormat(locale, {
      timeZone: TUNIS_TIME_ZONE, day: 'numeric', month: 'long', year: 'numeric',
    }).format(parsed);
  return `${dayLabel} · ${time}`;
};

export const isToday = (dateString?: string | null): boolean => {
  if (!dateString) return false;
  try {
    return isDateToday(parseISO(dateString));
  } catch {
    return false;
  }
};

export const isPast = (dateString?: string | null): boolean => {
  if (!dateString) return false;
  try {
    return isDatePast(parseISO(dateString));
  } catch {
    return false;
  }
};

export const isFuture = (dateString?: string | null): boolean => {
  if (!dateString) return false;
  try {
    return isDateFuture(parseISO(dateString));
  } catch {
    return false;
  }
};

export const getTimeOfDay = (timeString: string): 'morning' | 'afternoon' | 'evening' | 'night' => {
  const hours = parseInt(timeString.split(':')[0], 10);
  if (hours >= 5 && hours < 12) return 'morning';
  if (hours >= 12 && hours < 17) return 'afternoon';
  if (hours >= 17 && hours < 22) return 'evening';
  return 'night';
};
