import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { medicalLabel } from '../../utils/medicalLabels';
import { doctorsApi } from '../../services/api/doctors';
import { conversationsApi } from '../../services/api/conversations';
import { ConversationCategory } from '../../types';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { DoctorCard } from '../../components/cards/DoctorCard';
import { Card } from '../../components/ui/Card';
import { BottomSheet } from '../../components/ui/BottomSheet';
import { TextInput } from '../../components/ui/TextInput';
import { PrimaryButton } from '../../components/ui/PrimaryButton';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

export const DoctorScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [askModalVisible, setAskModalVisible] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<ConversationCategory>(ConversationCategory.MEDICATION);
  const [initialMessage, setInitialMessage] = useState('');

  const {
    data: doctors,
    isLoading: isLoadingDoctors,
    isError: isErrorDoctors,
    refetch: refetchDoctors,
  } = useQuery({
    queryKey: ['myDoctors'],
    queryFn: doctorsApi.getMyDoctors,
  });

  const {
    data: conversations,
    isLoading: isLoadingConvs,
    refetch: refetchConvs,
  } = useQuery({
    queryKey: ['conversations'],
    queryFn: conversationsApi.getConversations,
  });

  const doctor = doctors?.[0];

  const createConvMutation = useMutation({
    mutationFn: async () => {
      if (!doctor) throw new Error('No doctor assigned');
      return await conversationsApi.createConversation({
        doctor_id: doctor.id,
        category: selectedCategory,
        initial_message: initialMessage,
      });
    },
    onSuccess: (newConv) => {
      setAskModalVisible(false);
      setInitialMessage('');
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
      router.push(`/conversation/${newConv.id}` as any);
    },
  });

  const categories = [
    { key: ConversationCategory.MEDICATION, label: t('doctor.categoryMedication'), icon: 'medkit-outline' as const },
    { key: ConversationCategory.SPORT, label: t('doctor.categorySport'), icon: 'walk-outline' as const },
    { key: ConversationCategory.NUTRITION, label: t('doctor.categoryNutrition'), icon: 'nutrition-outline' as const },
    { key: ConversationCategory.APPOINTMENT, label: t('doctor.categoryAppointment'), icon: 'calendar-outline' as const },
    { key: ConversationCategory.MEDICAL_RECORD, label: t('doctor.categoryRecord'), icon: 'document-text-outline' as const },
    { key: ConversationCategory.OTHER, label: t('doctor.categoryOther'), icon: 'help-circle-outline' as const },
  ];

  if (isLoadingDoctors && !doctors) {
    return (
      <ScreenContainer>
        <Header title={t('doctor.title')} />
        <CardSkeleton />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isErrorDoctors && !doctors) {
    return (
      <ScreenContainer onRefresh={refetchDoctors}>
        <Header title={t('doctor.title')} />
        <ErrorState
          title={t('copy.loadDoctors')}
          onRetry={refetchDoctors}
        />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer onRefresh={() => { refetchDoctors(); refetchConvs(); }}>
      <Header title={t('doctor.title')} />

      {/* Emergency Notice */}
      <View
        style={[
          styles.emergencyBox,
          {
            backgroundColor: colors.errorLight,
            borderColor: colors.error,
            borderRadius: radii.lg,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="warning" size={20} color={colors.error} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.captionBold, { color: colors.error, flex: 1, textAlign, lineHeight: 18 }]}>
          {t('doctor.emergencyNotice')}
        </Text>
      </View>

      {/* Attending Physician Card */}
      {doctor ? (
        <View style={{ marginTop: spacing.md }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
            {t('copy.primaryDoctor')}
          </Text>
          <DoctorCard
            doctor={doctor}
            onMessage={() => setAskModalVisible(true)}
          />
        </View>
      ) : (
        <EmptyState
          icon="person-outline"
          title={t('copy.noDoctor')}
          description={t('copy.institutionWillAssign')}
        />
      )}

      {/* Conversations History */}
      <View style={{ marginTop: spacing.xl }}>
        <View style={[styles.sectionHeaderRow, { flexDirection }]}>
          <Text style={[typography.h3, { color: colors.textPrimary, textAlign }]}>
            {t('copy.consultationThreads')}
          </Text>
          {doctor && (
            <TouchableOpacity
              onPress={() => setAskModalVisible(true)}
              style={[styles.askPill, { backgroundColor: colors.primaryLight, borderRadius: radii.full }]}
            >
              <Ionicons name="add" size={16} color={colors.primary} />
              <Text style={[typography.captionBold, { color: colors.primary, marginHorizontal: 4 }]}>
                {t('doctor.askMyDoctor')}
              </Text>
            </TouchableOpacity>
          )}
        </View>

        {(!conversations || conversations.length === 0) ? (
          <EmptyState
            icon="chatbubbles-outline"
            title={t('copy.noConsultationHistory')}
            description={t('copy.askDoctorForNonUrgent')}
          />
        ) : (
          conversations.map((conv) => (
            <Card
              key={conv.id}
              onPress={() => router.push(`/conversation/${conv.id}` as any)}
              style={styles.convCard}
            >
              <View style={[styles.convRow, { flexDirection }]}>
                <View style={[styles.convIcon, { backgroundColor: colors.primaryLight, borderRadius: radii.md }]}>
                  <Ionicons name="chatbubble-outline" size={20} color={colors.primary} />
                </View>
                <View style={styles.convContent}>
                  <Text style={[typography.subtitle, { color: colors.textPrimary, textAlign, fontWeight: '700' }]}>
                    {conv.subject || medicalLabel(conv.category)}
                  </Text>
                  <Text style={[typography.caption, { color: colors.textSecondary, textAlign, marginTop: 2 }]}>
                    {t('copy.category')} {medicalLabel(conv.category)}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
              </View>
            </Card>
          ))
        )}
      </View>

      {/* "Ask My Doctor" BottomSheet Modal */}
      <BottomSheet
        visible={askModalVisible}
        onClose={() => setAskModalVisible(false)}
        title={t('doctor.askMyDoctor')}
      >
        <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
          {t('copy.selectTopic')}
        </Text>

        <View style={[styles.categoryGrid, { flexDirection, flexWrap: 'wrap' }]}>
          {categories.map((cat) => {
            const isSelected = selectedCategory === cat.key;
            return (
              <TouchableOpacity
                key={cat.key}
                onPress={() => setSelectedCategory(cat.key)}
                style={[
                  styles.catItem,
                  {
                    backgroundColor: isSelected ? colors.primaryLight : colors.inputBg,
                    borderColor: isSelected ? colors.primary : colors.cardBorder,
                    borderRadius: radii.lg,
                  },
                ]}
              >
                <Ionicons
                  name={cat.icon}
                  size={18}
                  color={isSelected ? colors.primary : colors.textSecondary}
                />
                <Text
                  style={[
                    typography.tiny,
                    {
                      color: isSelected ? colors.primary : colors.textPrimary,
                      fontWeight: isSelected ? '700' : '500',
                      marginTop: 4,
                      textAlign: 'center',
                    },
                  ]}
                >
                  {cat.label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <TextInput
          label={t('copy.inquiry')}
          placeholder={t('copy.inquiryPlaceholder')}
          multiline
          numberOfLines={4}
          value={initialMessage}
          onChangeText={setInitialMessage}
          containerStyle={{ marginTop: spacing.md }}
        />

        <PrimaryButton
          title={t('copy.sendToDoctor')}
          onPress={() => createConvMutation.mutate()}
          loading={createConvMutation.isPending}
          disabled={!initialMessage.trim()}
          style={{ marginTop: spacing.lg }}
        />
      </BottomSheet>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  emergencyBox: {
    borderWidth: 1,
    padding: 12,
    alignItems: 'center',
    marginBottom: 8,
  },
  sectionHeaderRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  askPill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  convCard: {
    marginVertical: 4,
  },
  convRow: {
    alignItems: 'center',
  },
  convIcon: {
    width: 36,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 8,
  },
  convContent: {
    flex: 1,
    paddingHorizontal: 4,
  },
  categoryGrid: {
    gap: 8,
    marginBottom: 8,
  },
  catItem: {
    width: '48%',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderWidth: 1,
  },
});
