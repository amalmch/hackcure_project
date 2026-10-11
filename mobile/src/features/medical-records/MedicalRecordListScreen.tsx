import React, { useState } from 'react';
import { View, Text, StyleSheet, Linking, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { medicalRecordsApi } from '../../services/api/medicalRecords';
import { useAuthStore } from '../../store/authStore';
import { MedicalRecordType } from '../../types';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { TabBar } from '../../components/ui/TabBar';
import { MedicalRecordCard } from '../../components/cards/MedicalRecordCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

export const MedicalRecordListScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();
  const currentUserId = useAuthStore((state) => state.user?.id);

  const [activeTab, setActiveTab] = useState<'all' | 'diagnoses' | 'labs' | 'documents'>('all');

  const {
    data: records,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['medicalRecords', currentUserId],
    queryFn: medicalRecordsApi.getRecords,
    enabled: !!currentUserId,
    staleTime: 0,
  });

  const tabs = [
    { key: 'all' as const, label: t('medicalRecords.all') },
    { key: 'diagnoses' as const, label: t('medicalRecords.diagnoses') },
    { key: 'labs' as const, label: t('medicalRecords.labResults') },
    { key: 'documents' as const, label: t('medicalRecords.documents') },
  ];

  if (isLoading && !records) {
    return (
      <ScreenContainer>
        <Header title={t('medicalRecords.title')} showBack />
        <CardSkeleton />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isError && !records) {
    return (
      <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
        <Header title={t('medicalRecords.title')} showBack />
        <ErrorState
          title={t('copy.loadMedicalRecords')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  const filteredRecords = (records || []).filter((r) => {
    if (activeTab === 'diagnoses') return r.record_type === MedicalRecordType.DIAGNOSIS;
    if (activeTab === 'labs') return r.record_type === MedicalRecordType.LAB_RESULT;
    if (activeTab === 'documents') return r.record_type === MedicalRecordType.DOCUMENT;
    return true;
  });

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={t('medicalRecords.title')} showBack />

      {/* Confidentiality Notice */}
      <View
        style={[
          styles.noticeBox,
          {
            backgroundColor: colors.primaryLight,
            borderColor: colors.primary,
            borderRadius: radii.md,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="lock-closed" size={16} color={colors.primary} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.tiny, { color: colors.primary, flex: 1, textAlign }]}>
          {t('medicalRecords.confidentialNotice')}
        </Text>
      </View>

      <View style={[styles.guideCard, { backgroundColor: colors.card, borderColor: colors.cardBorder, borderRadius: radii.lg }]}>
        <Text style={[typography.h4, { color: colors.textPrimary, textAlign, marginBottom: spacing.xs }]}>
          {t('medicalRecords.tunisianGuideTitle')}
        </Text>
        <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
          {t('medicalRecords.tunisianGuideBody')}
        </Text>
        <Text style={[typography.captionBold, { color: colors.textPrimary, textAlign, marginTop: spacing.md, marginBottom: spacing.xs }]}>
          {t('medicalRecords.tunisianPortalTitle')}
        </Text>
        <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
          {t('medicalRecords.tunisianPortalBody')}
        </Text>
        <TouchableOpacity accessibilityRole="link" onPress={() => void Linking.openURL('https://www.sehha.tn/Default.aspx')}>
          <Text style={[typography.captionBold, styles.sourceLink, { color: colors.primary, textAlign }]}>{t('medicalRecords.sehhaLink')}</Text>
        </TouchableOpacity>
        <TouchableOpacity accessibilityRole="link" onPress={() => void Linking.openURL('https://santetunisie.rns.tn/fr/prestations/programme-de-d%C3%A9veloppement-de-la-%C2%ABsant%C3%A9-num%C3%A9rique%C2%BB-en-tunisie?start=3')}>
          <Text style={[typography.captionBold, styles.sourceLink, { color: colors.primary, textAlign }]}>{t('medicalRecords.healthMinistryLink')}</Text>
        </TouchableOpacity>
        <Text style={[typography.tiny, { color: colors.textMuted, textAlign, marginTop: spacing.xs }]}>
          {t('medicalRecords.recordsDisclaimer')}
        </Text>
      </View>

      <TabBar
        tabs={tabs}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      <View style={{ marginTop: spacing.sm }}>
        {filteredRecords.length === 0 ? (
          <EmptyState
            icon="folder-open-outline"
            title={t('copy.noRecords')}
            description={t('copy.noRecordsDescription')}
          />
        ) : (
          filteredRecords.map((record) => (
            <MedicalRecordCard
              key={record.id}
              record={record}
              onPress={() => router.push(`/medical-records/${record.id}` as any)}
            />
          ))
        )}
      </View>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  guideCard: {
    borderWidth: 1,
    padding: 14,
    marginVertical: 10,
  },
  sourceLink: {
    textDecorationLine: 'underline',
    paddingVertical: 8,
  },
  noticeBox: {
    borderWidth: 1,
    padding: 10,
    alignItems: 'center',
    marginVertical: 4,
  },
});
