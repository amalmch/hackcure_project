import { z } from 'zod';
import type { TFunction } from 'i18next';

export const createLoginSchema = (t: TFunction) => z.object({
  email: z.string().min(1, t('validation.emailRequired')).email(t('validation.emailInvalid')),
  password: z.string().min(6, t('validation.passwordLength')),
});

export const createRegisterSchema = (t: TFunction) => z.object({
  first_name: z.string().min(2, t('validation.firstNameRequired')),
  last_name: z.string().min(2, t('validation.lastNameRequired')),
  email: z.string().min(1, t('validation.emailRequired')).email(t('validation.emailInvalid')),
  password: z.string().min(6, t('validation.passwordLength')),
  confirm_password: z.string().min(6, t('validation.confirmPasswordRequired')),
}).refine((data) => data.password === data.confirm_password, {
  message: t('validation.passwordMismatch'),
  path: ['confirm_password'],
});

export const createForgotPasswordSchema = (t: TFunction) => z.object({
  email: z.string().min(1, t('validation.emailRequired')).email(t('validation.emailInvalid')),
});

export const createMessageSchema = (t: TFunction) => z.object({
  content: z.string().min(1, t('validation.messageRequired')).max(2000, t('validation.messageTooLong')),
});

export const createNewConversationSchema = (t: TFunction) => z.object({
  category: z.enum(['MEDICATION', 'SPORT', 'NUTRITION', 'APPOINTMENT', 'MEDICAL_RECORD', 'OTHER']),
  subject: z.string().optional(),
  initial_message: z.string().min(1, t('validation.messageRequired')),
});
