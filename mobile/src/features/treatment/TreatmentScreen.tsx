import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { prescriptionsApi } from '../../services/api/prescriptions';
import { patientApi } from '../../services/api/patient';
import { medicationsApi } from '../../services/api/medications';
import { useNotifications } from '../../hooks/useNotifications';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { TabBar } from '../../components/ui/TabBar';
import { PrescriptionCard } from '../../components/cards/PrescriptionCard';
import { MedicationCard } from '../../components/cards/MedicationCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

type TreatmentSubTab = 'medications' | 'adherence' | 'sport' | 'nutrition';

export const TreatmentScreen: React.FC = () => {
  const router = useRouter();
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { rebuildAllDoseReminders } = useNotifications();

  const [activeTab, setActiveTab] = useState<TreatmentSubTab>('medications');
  const [showDraftModal, setShowDraftModal] = useState(false);

  // Active prescription
  const {
    data: prescriptions,
    isLoading: isLoadingPrescription,
    isError,
    refetch: refetchPrescription,
    isRefetching,
  } = useQuery({
    queryKey: ['activePrescriptions'],
    queryFn: prescriptionsApi.getActivePrescriptions,
  });

  // Doctor's report treatment summary
  const {
    data: summary,
    refetch: refetchSummary,
  } = useQuery({
    queryKey: ['treatmentSummary'],
    queryFn: patientApi.getTreatmentSummary,
  });

  // Pending automation drafts (from n8n extraction)
  const {
    data: drafts,
    refetch: refetchDrafts,
  } = useQuery({
    queryKey: ['automationDrafts'],
    queryFn: patientApi.getAutomationDrafts,
  });

  const applyDraftMutation = useMutation({
    mutationFn: async (docIds: string[]) => {
      return await patientApi.applyAutomationDrafts(docIds);
    },
    onSuccess: async () => {
      Alert.alert(
        t('copy.treatmentUpdated'),
        t('copy.treatmentUpdatedBody')
      );
      queryClient.invalidateQueries({ queryKey: ['activePrescriptions'] });
      queryClient.invalidateQueries({ queryKey: ['treatmentSummary'] });
      queryClient.invalidateQueries({ queryKey: ['automationDrafts'] });
      queryClient.invalidateQueries({ queryKey: ['todayDoses'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });

      // Fetch today's doses to rebuild reminder schedule
      try {
        const todayDoses = await medicationsApi.getTodayDoses();
        await rebuildAllDoseReminders(todayDoses);
      } catch {
        // Ignore
      }
      setShowDraftModal(false);
    },
    onError: (err: any) => {
      Alert.alert(t('copy.error'), t('copy.applyDraftError'));
    },
  });

  const activePrescription = prescriptions?.[0];
  const pendingDrafts = drafts || [];

  const handleTabChange = (key: TreatmentSubTab) => {
    setActiveTab(key);
    if (key === 'adherence') router.push('/treatment/adherence');
    if (key === 'sport') router.push('/treatment/sport');
    if (key === 'nutrition') router.push('/treatment/nutrition');
  };

  const tabs = [
    { key: 'medications' as const, label: t('treatment.medicationsTab') },
    { key: 'adherence' as const, label: t('treatment.adherenceTab') },
    { key: 'sport' as const, label: t('treatment.sportTab') },
    { key: 'nutrition' as const, label: t('treatment.nutritionTab') },
  ];

  const onFullRefresh = () => {
    refetchPrescription();
    refetchSummary();
    refetchDrafts();
  };

  if (isLoadingPrescription && !prescriptions) {
    return (
      <ScreenContainer>
        <Header title={t('treatment.title')} />
        <CardSkeleton />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isError && !prescriptions) {
    return (
      <ScreenContainer onRefresh={onFullRefresh} refreshing={isRefetching}>
        <Header title={t('treatment.title')} />
        <ErrorState
          title={t('copy.loadTreatment')}
          message={t('copy.backendTreatment')}
          onRetry={onFullRefresh}
        />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer onRefresh={onFullRefresh} refreshing={isRefetching}>
      <Header title={t('treatment.title')} />

      {/* Segment tabs */}
      <TabBar
        tabs={tabs}
        activeTab={activeTab}
        onTabChange={handleTabChange}
      />

      {/* Pending Draft Alert Card (from n8n automation) */}
      {pendingDrafts.length > 0 && (
        <View
          style={[
            styles.draftAlertCard,
            {
              backgroundColor: colors.primaryLight,
              borderColor: colors.primary,
              borderRadius: radii.md,
            },
          ]}
        >
          <View style={[styles.draftHeaderRow, { flexDirection }]}>
            <Ionicons name="document-attach" size={24} color={colors.primary} style={{ marginRight: 8 }} />
            <View style={{ flex: 1 }}>
              <Text style={[typography.bodyBold, { color: colors.primary, textAlign }]}>
                {t('copy.newTreatment')} {pendingDrafts.length} {t('copy.document')}{pendingDrafts.length > 1 ? 's' : ''})
              </Text>
              <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
                {t('copy.extractionSource')}
              </Text>
            </View>
          </View>

          {/* Low confidence warnings if any */}
          {pendingDrafts.some((d: any) => d.low_confidence_fields?.length > 0) && (
            <View style={[styles.lowConfBadge, { backgroundColor: colors.warningLight, flexDirection }]}>
              <Ionicons name="alert-circle" size={16} color={colors.warning} style={{ marginRight: 6 }} />
              <Text style={[typography.tiny, { color: colors.warning, flex: 1, textAlign }]}>
                {t('copy.verifyFields')}
              </Text>
            </View>
          )}

          <TouchableOpacity
            style={[styles.applyButton, { backgroundColor: colors.primary, borderRadius: radii.md }]}
            onPress={() => {
              const ids = pendingDrafts.map((d: any) => d.document_source_id);
              applyDraftMutation.mutate(ids);
            }}
            disabled={applyDraftMutation.isPending}
          >
            <Ionicons name="checkmark-circle" size={18} color={colors.textInverse} style={{ marginRight: 6 }} />
            <Text style={[typography.bodyBold, { color: colors.textInverse }]}>
              {applyDraftMutation.isPending ? t('copy.applyInProgress') : t('copy.confirmApplyTreatment')}
            </Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Medical Disclaimer Banner */}
      <View
        style={[
          styles.disclaimerBox,
          {
            backgroundColor: colors.inputBg,
            borderColor: colors.cardBorder,
            borderRadius: radii.md,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="shield-checkmark" size={16} color={colors.textSecondary} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.tiny, { color: colors.textSecondary, flex: 1, textAlign }]}>
          {i18n.t('copy.static_cette_application_ne_remplace_pas_l_avis_de_votr')}</Text>
      </View>

      {/* Doctor Report Clinical Summary (if available) */}
      {summary && (
        <View
          style={[
            styles.summaryCard,
            {
              backgroundColor: colors.card,
              borderColor: colors.cardBorder,
              borderRadius: radii.lg,
            },
          ]}
        >
          <View style={[styles.summaryHeader, { flexDirection }]}>
            <Ionicons name="clipboard-outline" size={20} color={colors.primary} style={{ marginRight: 8 }} />
            <Text style={[typography.h4, { color: colors.textPrimary, flex: 1, textAlign }]}>
              {i18n.t('copy.static_synthese_du_rapport_medical')}</Text>
          </View>

          {summary.diagnosis && (
            <View style={styles.summarySection}>
              <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign }]}>
                {i18n.t('copy.static_diagnostic_du_medecin')}</Text>
              <Text style={[typography.bodyBold, { color: colors.textPrimary, textAlign, marginTop: 2 }]}>
                {summary.diagnosis}
              </Text>
            </View>
          )}

          {summary.patient_summary && (
            <View style={[styles.patientSummaryBox, { backgroundColor: colors.primaryLight, borderRadius: radii.sm }]}>
              <Text style={[typography.captionBold, { color: colors.primary, textAlign, marginBottom: 2 }]}>
                {i18n.t('copy.static_en_resume_pour_vous')}</Text>
              <Text style={[typography.caption, { color: colors.textPrimary, textAlign, lineHeight: 18 }]}>
                {summary.patient_summary}
              </Text>
            </View>
          )}

          {summary.treatment_goals && summary.treatment_goals.length > 0 && (
            <View style={styles.summarySection}>
              <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 4 }]}>
                {i18n.t('copy.static_objectifs_therapeutiques')}</Text>
              {summary.treatment_goals.map((goal, idx) => (
                <View key={idx} style={[styles.bulletRow, { flexDirection }]}>
                  <Text style={{ color: colors.primary, marginRight: 6 }}>•</Text>
                  <Text style={[typography.caption, { color: colors.textPrimary, flex: 1, textAlign }]}>
                    {goal}
                  </Text>
                </View>
              ))}
            </View>
          )}

          {summary.warnings && summary.warnings.length > 0 && (
            <View style={[styles.alertBox, { backgroundColor: colors.errorLight, borderRadius: radii.sm }]}>
              <View style={[styles.alertHeader, { flexDirection }]}>
                <Ionicons name="warning" size={16} color={colors.error} style={{ marginRight: 6 }} />
                <Text style={[typography.captionBold, { color: colors.error }]}>
                  {i18n.t('copy.static_signes_d_alerte_et_precautions')}</Text>
              </View>
              {summary.warnings.map((warn, idx) => (
                <Text key={idx} style={[typography.tiny, { color: colors.error, marginTop: 2 }]}>
                  ⚠️ {warn}
                </Text>
              ))}
            </View>
          )}

          {summary.follow_up_dates && summary.follow_up_dates.length > 0 && (
            <View style={[styles.followUpRow, { flexDirection }]}>
              <Ionicons name="calendar-outline" size={16} color={colors.primary} style={{ marginRight: 6 }} />
              <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
                {i18n.t('copy.static_prochain_suivi_prevu_le')}{' '}<Text style={{ fontWeight: '700', color: colors.primary }}>{summary.follow_up_dates.join(', ')}</Text>
              </Text>
            </View>
          )}
        </View>
      )}

      {/* Source of Truth Notice */}
      <View
        style={[
          styles.noticeBox,
          {
            backgroundColor: colors.inputBg,
            borderColor: colors.cardBorder,
            borderRadius: radii.md,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="lock-closed" size={16} color={colors.primary} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.caption, { color: colors.textPrimary, flex: 1, textAlign, lineHeight: 18 }]}>
          {t('treatment.cannotModifyNotice')}
        </Text>
      </View>

      {!activePrescription ? (
        <EmptyState
          icon="document-text-outline"
          title={t('treatment.noActivePrescription')}
          description={t('copy.noPrescriptionDescription')}
        />
      ) : (
        <View style={{ marginTop: spacing.sm }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
            {t('treatment.activePrescriptions')}
          </Text>

          <PrescriptionCard
            prescription={activePrescription}
            onPress={() => router.push(`/prescription/${activePrescription.id}` as any)}
          />

          <View style={{ marginTop: spacing.md }}>
            <View style={[styles.sectionRow, { flexDirection }]}>
              <Text style={[typography.h3, { color: colors.textPrimary, textAlign }]}>
                {t('medications.allMedications')}
              </Text>
              <TouchableOpacity onPress={() => router.push('/treatment/medications')}>
                <Text style={[typography.captionBold, { color: colors.primary }]}>
                  {t('common.viewAll')}
                </Text>
              </TouchableOpacity>
            </View>

            {activePrescription.items?.map((item) => (
              <MedicationCard
                key={item.id}
                medication={item}
                onPress={() => router.push(`/treatment/medication/${item.id}` as any)}
              />
            ))}
          </View>
        </View>
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  noticeBox: {
    padding: 10,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 10,
  },
  disclaimerBox: {
    padding: 8,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 10,
  },
  draftAlertCard: {
    padding: 12,
    borderWidth: 1.5,
    marginBottom: 12,
  },
  draftHeaderRow: {
    alignItems: 'center',
  },
  lowConfBadge: {
    padding: 8,
    borderRadius: 8,
    marginTop: 8,
    alignItems: 'center',
  },
  applyButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    marginTop: 10,
  },
  summaryCard: {
    padding: 14,
    borderWidth: 1,
    marginBottom: 12,
  },
  summaryHeader: {
    alignItems: 'center',
    marginBottom: 10,
  },
  summarySection: {
    marginBottom: 10,
  },
  patientSummaryBox: {
    padding: 10,
    marginBottom: 10,
  },
  bulletRow: {
    alignItems: 'flex-start',
    marginTop: 2,
  },
  alertBox: {
    padding: 10,
    marginBottom: 10,
  },
  alertHeader: {
    alignItems: 'center',
    marginBottom: 4,
  },
  followUpRow: {
    alignItems: 'center',
    marginTop: 4,
  },
  sectionRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
});
