import React, { useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, FlatList, KeyboardAvoidingView, Platform,
  StyleSheet, Text, TouchableOpacity, View,
} from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useOfflineStore } from '../../store/offlineStore';
import { companionApi } from '../../services/api/companion';
import { SakinaEmergencyNumber, SakinaMessage, sakinaApi } from '../../services/api/sakina';
import { Header } from '../../components/layout/Header';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { TextInput } from '../../components/ui/TextInput';
const uuidv4 = () => `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

interface DisplayMessage extends SakinaMessage {
  id: string;
  fallback?: boolean;
  crisis?: boolean;
  emergencyNumbers?: SakinaEmergencyNumber[];
}

const QUICK_REPLIES = ['companion.anxiety', 'companion.listen', 'companion.grounding'] as const;

const containsCrisisKeyword = (value: string) => {
  const text = value.toLocaleLowerCase();
  const terms = [
    'suicide', 'suicidal', 'kill myself', 'end my life', 'want to die', "don't want to live",
    'dont want to live', 'self-harm', 'self harm', 'hurt myself', 'harm myself', 'abuse',
    'being abused', 'someone is hurting me', 'i am in danger', "i'm in danger", 'in danger', 'unsafe right now',
    'me suicider', 'suicidaire', 'me faire du mal', 'me blesser', 'envie de mourir',
    'ne veux plus vivre', 'violence', 'violences', 'abus', 'je suis en danger', 'en danger',
    'quelqu’un me fait du mal', "quelqu'un me fait du mal", 'انتحار', 'انتحاري', 'أقتل نفسي', 'اقتل نفسي',
    'أؤذي نفسي', 'اوذي نفسي', 'أضر نفسي', 'أريد أن أموت', 'نريد أن نموت', 'لا أريد أن أعيش',
    'إيذاء النفس', 'اعتداء', 'عنف', 'أنا في خطر', 'انا في خطر', 'نحب نموت', 'نقتل روحي', 'نأذي روحي',
    'نضر روحي', 'نتعرض للعنف',
  ];
  return terms.some((term) => text.includes(term));
};

const confirmsSafety = (value: string) => {
  const text = value.toLocaleLowerCase();
  return [
    'i am safe now', "i'm safe now", 'im safe now', 'i am safe', "i'm safe",
    'je suis en sécurité', 'je suis en securite', 'je suis en sûreté', 'je suis en surete',
    'أنا بأمان', 'انا بأمان', 'أنا في أمان', 'انا في امان', 'أنا بخير الآن', 'انا بخير توا',
  ].some((phrase) => text.includes(phrase));
};

export const CompanionScreen: React.FC = () => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, isRTL } = useRTL();
  const { t } = useTranslation();
  const isOnline = useOfflineStore((state) => state.isOnline);
  const [text, setText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState(false);
  const [crisisActive, setCrisisActive] = useState(false);
  const [retryHistory, setRetryHistory] = useState<SakinaMessage[] | undefined>(undefined);
  const listRef = useRef<FlatList<DisplayMessage> | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([{
    id: 'sakina-welcome', role: 'assistant', content: t('companion.greeting'),
  }]);

  const contactsQuery = useQuery({ queryKey: ['sakina-emergency'], queryFn: companionApi.emergencyContacts });
  const contacts = contactsQuery.data?.numbers ?? [];

  const showUrgentHelp = () => {
    const details = contacts.map((item) => `${item.label}: ${item.number}`).join('\n');
    Alert.alert(t('companion.urgent'), [t('companion.emergencyDescription'), details || t('companion.localEmergency')].filter(Boolean).join('\n\n'));
  };

  const retry = async (history: SakinaMessage[]) => {
    setMessages((current) => current.filter((message) => !message.fallback));
    setIsSending(true);
    setSendError(false);
    try {
      const result = await sakinaApi.send(history);
      setMessages((current) => [...current, {
        id: uuidv4(), role: 'assistant', content: result.reply,
        fallback: result.fallback,
        crisis: result.crisis,
        emergencyNumbers: result.crisis ? result.emergency_numbers : undefined,
      }]);
      setSendError(result.fallback);
      setRetryHistory(result.fallback ? history : undefined);
    } catch {
      setMessages((current) => [...current, {
        id: uuidv4(), role: 'assistant', content: t('companion.connectionError'), fallback: true,
      }]);
      setRetryHistory(history);
      setSendError(true);
    } finally {
      setIsSending(false);
      requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
    }
  };

  const send = (value = text) => {
    const content = value.trim();
    if (!content || isSending) return;

    const userMessage: DisplayMessage = { id: uuidv4(), role: 'user', content };
    const prior = messages.filter((message) => !message.fallback).map(({ role, content: body }) => ({ role, content: body }));
    const history: SakinaMessage[] = [...prior, { role: 'user', content }];
    setMessages((current) => [...current, userMessage]);
    setText('');
    setSendError(false);

    if (containsCrisisKeyword(content)) {
      setCrisisActive(true);
      setMessages((current) => [...current, {
        id: uuidv4(), role: 'assistant', content: t('companion.crisisReply'),
        emergencyNumbers: contacts, crisis: true, fallback: false,
      }]);
      setRetryHistory(undefined);
      return;
    }

    if (crisisActive && !confirmsSafety(content)) {
      setMessages((current) => [...current, {
        id: uuidv4(), role: 'assistant', content: t('companion.crisisFollowup'),
        emergencyNumbers: contacts, crisis: true,
      }]);
      return;
    }
    if (crisisActive && confirmsSafety(content)) setCrisisActive(false);

    if (!isOnline) {
      setMessages((current) => [...current, {
        id: uuidv4(), role: 'assistant', content: t('companion.offlineReply'), fallback: true,
      }]);
      setRetryHistory(history);
      setSendError(true);
      return;
    }
    setRetryHistory(history);
    void retry(history);
  };

  return (
    <ScreenContainer scrollable={false}>
      <Header title={t('companion.title')} showBack={false} />
      <View style={[styles.disclaimer, { backgroundColor: colors.primaryLight, borderRadius: radii.md, marginBottom: spacing.sm, flexDirection }]}>
        <Ionicons name="information-circle-outline" size={18} color={colors.primary} />
        <Text accessibilityRole="text" style={[typography.caption, { color: colors.primaryDark, marginHorizontal: spacing.xs, flex: 1, textAlign: isRTL ? 'right' : 'left' }]}>{t('companion.disclaimer')}</Text>
      </View>
      <TouchableOpacity accessibilityRole="button" accessibilityLabel={t('companion.urgent')} onPress={showUrgentHelp} style={[styles.urgentButton, { borderColor: colors.error, borderRadius: radii.lg, marginBottom: spacing.sm, flexDirection }]}>
        <Ionicons name="alert-circle-outline" size={20} color={colors.error} />
        <Text style={[typography.captionBold, { color: colors.error, marginHorizontal: spacing.sm }]}>{t('companion.urgent')}</Text>
      </TouchableOpacity>
      {!isOnline && <Text accessibilityRole="alert" style={[typography.caption, { color: colors.warning, textAlign: 'center' }]}>{t('companion.offline')}</Text>}
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => {
          const own = item.role === 'user';
          return (
            <View style={[styles.messageRow, { justifyContent: own ? (isRTL ? 'flex-start' : 'flex-end') : (isRTL ? 'flex-end' : 'flex-start') }]}>
              <View style={[styles.bubble, {
                backgroundColor: own ? colors.primary : colors.card,
                borderColor: item.fallback ? colors.warning : colors.cardBorder,
                borderRadius: radii.lg,
                borderBottomRightRadius: own && !isRTL ? 4 : radii.lg,
                borderBottomLeftRadius: own && isRTL ? 4 : radii.lg,
              }]}>
                <Text accessibilityRole="text" style={[typography.body, { color: own ? '#FFFFFF' : colors.textPrimary, textAlign: isRTL ? 'right' : 'left' }]}>{item.content}</Text>
                {item.crisis && (
                  <View style={[styles.resources, { borderTopColor: colors.cardBorder }]}>
                    <Text style={[typography.captionBold, { color: colors.textPrimary, textAlign: isRTL ? 'right' : 'left' }]}>{t('companion.emergencyResources')}</Text>
                    {!!item.emergencyNumbers?.length
                      ? item.emergencyNumbers.map((number) => <Text key={`${number.label}-${number.number}`} style={[typography.bodyBold, { color: colors.error, textAlign: isRTL ? 'right' : 'left' }]}>{number.label}: {number.number}</Text>)
                      : <Text style={[typography.bodyBold, { color: colors.error, textAlign: isRTL ? 'right' : 'left' }]}>{t('companion.localEmergency')}</Text>}
                    <Text style={[typography.caption, { color: colors.textSecondary, textAlign: isRTL ? 'right' : 'left' }]}>{t('companion.trustedPerson')}</Text>
                  </View>
                )}
              </View>
            </View>
          );
        }}
        contentContainerStyle={{ paddingVertical: spacing.md, flexGrow: 1 }}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
        ListFooterComponent={isSending ? <View accessibilityLiveRegion="polite" style={[styles.typing, { flexDirection }]}><ActivityIndicator size="small" color={colors.primary} /><Text style={[typography.caption, { color: colors.textMuted, marginHorizontal: spacing.sm }]}>{t('companion.loading')}</Text></View> : null}
      />
      <View style={[styles.quickReplies, { flexDirection }]}>
        {QUICK_REPLIES.map((key) => <TouchableOpacity key={key} accessibilityRole="button" disabled={isSending} onPress={() => send(t(key))} style={[styles.quickChip, { backgroundColor: colors.primaryLight, borderRadius: radii.full }]}><Text style={[typography.caption, { color: colors.primaryDark }]}>{t(key)}</Text></TouchableOpacity>)}
      </View>
      {sendError && (
        <View style={[styles.retryNotice, { flexDirection, borderColor: colors.warning, borderRadius: radii.md }]}>
          <Text accessibilityRole="alert" style={[typography.caption, { flex: 1, color: colors.warning, textAlign: isRTL ? 'right' : 'left' }]}>{t('companion.connectionUnstable')}</Text>
          <TouchableOpacity accessibilityRole="button" accessibilityLabel={t('companion.retrySend')} disabled={isSending || !isOnline || !retryHistory} onPress={() => retryHistory && void retry(retryHistory)}>
            <Text style={[typography.captionBold, { color: colors.primary }]}>{t('companion.retrySend')}</Text>
          </TouchableOpacity>
        </View>
      )}
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={[styles.inputBar, { backgroundColor: colors.surface, borderTopColor: colors.cardBorder, flexDirection }]}>
        <View style={{ flex: 1 }}><TextInput accessibilityLabel={t('companion.placeholder')} placeholder={t('companion.placeholder')} value={text} onChangeText={setText} onSubmitEditing={() => send()} returnKeyType="send" containerStyle={{ marginVertical: 0 }} /></View>
        <TouchableOpacity accessibilityRole="button" accessibilityLabel={t('companion.send')} onPress={() => send()} disabled={!text.trim() || isSending} style={[styles.sendButton, { backgroundColor: text.trim() ? colors.primary : colors.cardBorder, borderRadius: radii.full }]}><Ionicons name="send" size={20} color="#fff" /></TouchableOpacity>
      </KeyboardAvoidingView>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  disclaimer: { alignItems: 'center', paddingHorizontal: 10, paddingVertical: 8 },
  urgentButton: { minHeight: 42, borderWidth: 1, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center' },
  messageRow: { flexDirection: 'row', marginVertical: 5 },
  bubble: { borderWidth: 1, maxWidth: '88%', paddingVertical: 10, paddingHorizontal: 14 },
  resources: { borderTopWidth: 1, marginTop: 10, paddingTop: 8, gap: 4 },
  typing: { alignItems: 'center', padding: 8 },
  quickReplies: { gap: 7, paddingVertical: 8, flexWrap: 'wrap' },
  quickChip: { paddingHorizontal: 10, paddingVertical: 7 },
  retryNotice: { alignItems: 'center', justifyContent: 'space-between', gap: 8, borderWidth: 1, padding: 8, marginVertical: 4 },
  inputBar: { borderTopWidth: 1, paddingVertical: 6, paddingHorizontal: 8, alignItems: 'center', gap: 8 },
  sendButton: { width: 46, height: 46, alignItems: 'center', justifyContent: 'center' },
});
