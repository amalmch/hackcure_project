import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { useAuthStore } from '../../store/authStore';
import { useOfflineStore } from '../../store/offlineStore';
import { conversationsApi } from '../../services/api/conversations';
import { Message, MessageType } from '../../types';
import { WS_BASE_URL } from '../../constants';
import { formatTime } from '../../utils/dateUtils';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { TextInput } from '../../components/ui/TextInput';
import { LoadingScreen } from '../../components/ui/LoadingScreen';

export const ChatScreen: React.FC = () => {
  const { id } = useLocalSearchParams<{ id: string }>();
  const conversationId = id as string;

  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection, isRTL } = useRTL();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const user = useAuthStore((state) => state.user);
  const isOnline = useOfflineStore((state) => state.isOnline);
  const queueMessage = useOfflineStore((state) => state.queueMessage);

  const [inputText, setInputText] = useState('');
  const flatListRef = useRef<FlatList>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Messages Query
  const {
    data: messages,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => conversationsApi.getMessages(conversationId),
    enabled: !!conversationId,
    refetchInterval: 5000, // Polling fallback
  });

  // WebSocket Connection
  useEffect(() => {
    if (!user?.id || !conversationId) return;

    try {
      const ws = new WebSocket(`${WS_BASE_URL}/ws/${user.id}`);
      wsRef.current = ws;

      ws.onmessage = () => {
        // Invalidate on real-time message received
        queryClient.invalidateQueries({ queryKey: ['messages', conversationId] });
      };

      ws.onerror = () => {
        // WebSocket error, fallback to polling
      };
    } catch {
      // Fallback
    }

    return () => {
      wsRef.current?.close();
    };
  }, [user?.id, conversationId, queryClient]);

  // Send Message Mutation
  const sendMutation = useMutation({
    mutationFn: async (text: string) => {
      if (!isOnline) {
        const localId = `local_${Date.now()}`;
        await queueMessage(conversationId, text, localId);
        return {
          id: localId,
          conversation_id: conversationId,
          sender_id: user?.id || '',
          sender_role: 'PATIENT' as const,
          content: text,
          message_type: MessageType.TEXT,
          is_read: false,
          created_at: new Date().toISOString(),
          pending: true,
        };
      }
      return await conversationsApi.sendMessage(conversationId, text);
    },
    onSuccess: () => {
      setInputText('');
      queryClient.invalidateQueries({ queryKey: ['messages', conversationId] });
    },
  });

  const handleSend = () => {
    if (!inputText.trim()) return;
    sendMutation.mutate(inputText.trim());
  };

  const renderMessageItem = ({ item }: { item: Message }) => {
    const isPatient = item.sender_role === 'PATIENT';

    return (
      <View
        style={[
          styles.messageRow,
          {
            justifyContent: isPatient ? (isRTL ? 'flex-start' : 'flex-end') : (isRTL ? 'flex-end' : 'flex-start'),
          },
        ]}
      >
        <View
          style={[
            styles.bubble,
            {
              backgroundColor: isPatient ? colors.primary : colors.card,
              borderColor: isPatient ? colors.primary : colors.cardBorder,
              borderWidth: isPatient ? 0 : 1,
              borderBottomRightRadius: isPatient ? 4 : radii.lg,
              borderBottomLeftRadius: isPatient ? radii.lg : 4,
              borderRadius: radii.lg,
            },
          ]}
        >
          <Text
            style={[
              typography.body,
              {
                color: isPatient ? '#FFFFFF' : colors.textPrimary,
                textAlign: isRTL ? 'right' : 'left',
              },
            ]}
          >
            {item.content}
          </Text>

          <View style={[styles.metaRow, { flexDirection: isRTL ? 'row-reverse' : 'row' }]}>
            <Text
              style={[
                typography.tiny,
                { color: isPatient ? 'rgba(255,255,255,0.7)' : colors.textMuted },
              ]}
            >
              {formatTime(item.created_at)}
            </Text>

            {isPatient && (
              <Ionicons
                name={item.pending ? 'time-outline' : item.is_read ? 'checkmark-done' : 'checkmark'}
                size={14}
                color={isPatient ? 'rgba(255,255,255,0.8)' : colors.textMuted}
                style={{ marginHorizontal: 4 }}
              />
            )}
          </View>
        </View>
      </View>
    );
  };

  if (isLoading && !messages) {
    return <LoadingScreen message={t('copy.connectDoctor')} />;
  }

  return (
    <ScreenContainer scrollable={false}>
      <Header title={t('messages.title')} showBack />

      {/* Emergency reminder banner */}
      <View style={[styles.emergencyBanner, { backgroundColor: colors.warningLight }]}>
        <Ionicons name="alert-circle-outline" size={16} color={colors.warning} />
        <Text style={[typography.tiny, { color: colors.warning, marginLeft: 6 }]}>
        {t('copy.emergencyDisclaimer')}
        </Text>
      </View>

      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1 }}
      >
        <FlatList
          ref={flatListRef}
          data={messages || []}
          keyExtractor={(item) => item.id}
          renderItem={renderMessageItem}
          contentContainerStyle={{ paddingVertical: 12 }}
          showsVerticalScrollIndicator={false}
          onContentSizeChange={() => flatListRef.current?.scrollToEnd({ animated: true })}
        />

        {/* Input Bar */}
        <View style={[styles.inputBar, { backgroundColor: colors.surface, borderTopColor: colors.cardBorder, flexDirection }]}>
          <View style={{ flex: 1 }}>
            <TextInput
              placeholder={t('messages.typeMessage')}
              value={inputText}
              onChangeText={setInputText}
              containerStyle={{ marginVertical: 0 }}
            />
          </View>

          <TouchableOpacity
            onPress={handleSend}
            disabled={!inputText.trim() || sendMutation.isPending}
            activeOpacity={0.7}
            style={[
              styles.sendBtn,
              {
                backgroundColor: inputText.trim() ? colors.primary : colors.cardBorder,
                borderRadius: radii.full,
              },
            ]}
          >
            <Ionicons name="send" size={18} color="#FFFFFF" />
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  emergencyBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 8,
    borderRadius: 8,
    marginVertical: 4,
  },
  messageRow: {
    marginVertical: 4,
    flexDirection: 'row',
  },
  bubble: {
    maxWidth: '80%',
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  metaRow: {
    alignItems: 'center',
    marginTop: 4,
    justifyContent: 'flex-end',
  },
  inputBar: {
    borderTopWidth: 1,
    paddingVertical: 8,
    paddingHorizontal: 8,
    alignItems: 'center',
    gap: 8,
  },
  sendBtn: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
