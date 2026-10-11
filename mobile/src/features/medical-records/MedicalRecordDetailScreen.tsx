import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { medicalRecordsApi } from '../../services/api/medicalRecords';
import { useAuthStore } from '../../store/authStore';
import { formatDate } from '../../utils/dateUtils';
import { medicalLabel } from '../../utils/medicalLabels';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { Card } from '../../components/ui/Card';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { LoadingScreen } from '../../components/ui/LoadingScreen';
import { ErrorState } from '../../components/ui/ErrorState';

export const MedicalRecordDetailScreen: React.FC = () => {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();
  const currentUserId = useAuthStore((state) => state.user?.id);

  const {
    data: record,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['medicalRecord', currentUserId, id],
    queryFn: () => medicalRecordsApi.getById(id as string),
    enabled: !!currentUserId && !!id,
    staleTime: 0,
  });

  if (isLoading) return <LoadingScreen />;

  if (isError || !record) {
    return (
      <ScreenContainer>
        <Header title={t('medicalRecords.title')} showBack />
        <ErrorState
          title={t('copy.clinicalDocumentNotFound')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer>
      <Header title={t('copy.clinicalDocument')} showBack />

      <Card style={styles.card}>
        <View style={[styles.headerRow, { flexDirection }]}>
          <Text style={[typography.h3, { color: colors.textPrimary, textAlign, flex: 1 }]}>
            {record.title}
          </Text>
          <StatusBadge
            label={medicalLabel(record.record_type)}
            color={colors.primary}
          />
        </View>

        <View style={[styles.metaRow, { flexDirection, marginTop: spacing.sm }]}>
          <Ionicons name="calendar-outline" size={16} color={colors.textMuted} style={{ marginHorizontal: 4 }} />
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {t('copy.date')} {formatDate(record.record_date)}
          </Text>
          {record.doctor && (
            <Text style={[typography.caption, { color: colors.textSecondary, marginHorizontal: 6 }]}>
              • {t('copy.signedBy')} {record.doctor.last_name}
            </Text>
          )}
        </View>

        <View style={[styles.divider, { backgroundColor: colors.cardBorder }]} />

        {record.description && (
          <View style={{ marginVertical: 8 }}>
            <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 4 }]}>
              {t('copy.clinicalSummary')}
            </Text>
            <Text style={[typography.body, { color: colors.textPrimary, textAlign, lineHeight: 22 }]}>
              {record.description}
            </Text>
          </View>
        )}

        {record.data && (
          <View style={[styles.dataBox, { backgroundColor: colors.inputBg, borderRadius: radii.md, marginTop: spacing.md }]}>
            <Text style={[typography.captionBold, { color: colors.textPrimary, marginBottom: 6 }]}>
              {t('copy.structuredFindings')}
            </Text>
            {Object.entries(record.data).map(([key, val]) => (
              <View key={key} style={[styles.findingRow, { flexDirection }]}>
                <Text style={[typography.caption, { color: colors.textSecondary, textTransform: 'capitalize' }]}>
                  {key.replace(/_/g, ' ')} :
                </Text>
                <Text style={[typography.captionBold, { color: colors.textPrimary, marginHorizontal: 8 }]}>
                  {String(val)}
                </Text>
              </View>
            ))}
          </View>
        )}
      </Card>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 8,
    padding: 16,
  },
  headerRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  metaRow: {
    alignItems: 'center',
  },
  divider: {
    height: 1,
    marginVertical: 14,
  },
  dataBox: {
    padding: 12,
  },
  findingRow: {
    alignItems: 'center',
    marginVertical: 3,
  },
});
