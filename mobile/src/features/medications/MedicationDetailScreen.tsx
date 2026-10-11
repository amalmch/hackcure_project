import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { medicationsApi } from '../../services/api/medications';
import { formatDate } from '../../utils/dateUtils';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { Card } from '../../components/ui/Card';
import { LoadingScreen } from '../../components/ui/LoadingScreen';
import { ErrorState } from '../../components/ui/ErrorState';

export const MedicationDetailScreen: React.FC = () => {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const {
    data: medication,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['medication', id],
    queryFn: () => medicationsApi.getMedicationById(id as string),
    enabled: !!id,
  });

  if (isLoading) return <LoadingScreen />;

  if (isError || !medication) {
    return (
      <ScreenContainer>
        <Header title={t('medications.title')} showBack />
        <ErrorState
          title={i18n.t('copy.static_medication_not_found')}
          message={i18n.t('copy.static_could_not_retrieve_details_for_this_medication')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer>
      <Header title={medication.medication_name} showBack />

      {/* Hero Badge */}
      <Card style={styles.heroCard}>
        <View style={[styles.heroRow, { flexDirection }]}>
          <View
            style={[
              styles.iconWrapper,
              { backgroundColor: colors.primaryLight, borderRadius: radii.xl },
            ]}
          >
            <Ionicons name="medical" size={36} color={colors.primary} />
          </View>
          <View style={styles.heroTextCol}>
            <Text style={[typography.h3, { color: colors.textPrimary, textAlign }]}>
              {medication.medication_name}
            </Text>
            {medication.active_ingredient && (
              <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
                {medication.active_ingredient}
              </Text>
            )}
            <View style={[styles.pillBadge, { backgroundColor: colors.inputBg, borderRadius: radii.full, marginTop: 6 }]}>
              <Text style={[typography.captionBold, { color: colors.primary }]}>
                {medication.dosage} • {medication.form || t('copy.tabletLabel')}
              </Text>
            </View>
          </View>
        </View>
      </Card>

      {/* Safety Notice */}
      <View
        style={[
          styles.safetyBanner,
          {
            backgroundColor: colors.infoLight,
            borderColor: colors.info,
            borderRadius: radii.lg,
            flexDirection,
          },
        ]}
      >
        <Ionicons name="shield-checkmark" size={20} color={colors.info} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.caption, { color: colors.info, flex: 1, textAlign }]}>
          {i18n.t('copy.static_prescribed_exclusively_by_your_attending_physici')}</Text>
      </View>

      {/* Details Sections */}
      <View style={{ marginTop: spacing.md }}>
        <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
          {i18n.t('copy.static_treatment_protocol')}</Text>

        <Card style={styles.detailCard}>
          <View style={styles.detailRow}>
            <Text style={[typography.caption, { color: colors.textMuted }]}>
              {t('medications.frequency')}
            </Text>
            <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '600' }]}>
              {medication.frequency}
            </Text>
          </View>

          <View style={[styles.divider, { backgroundColor: colors.cardBorder }]} />

          <View style={styles.detailRow}>
            <Text style={[typography.caption, { color: colors.textMuted }]}>
              {i18n.t('copy.static_meal_recommendation')}</Text>
            <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '600' }]}>
              {medication.before_food === true
                ? t('medications.beforeFood')
                : medication.before_food === false
                ? t('medications.afterFood')
                : t('copy.waterAnyTime')}
            </Text>
          </View>

          {medication.start_date && (
            <>
              <View style={[styles.divider, { backgroundColor: colors.cardBorder }]} />
              <View style={styles.detailRow}>
                <Text style={[typography.caption, { color: colors.textMuted }]}>
                  {i18n.t('copy.static_course_duration')}</Text>
                <Text style={[typography.subtitle, { color: colors.textPrimary, fontWeight: '600' }]}>
                  {formatDate(medication.start_date)}
                  {medication.end_date ? ` ${t('copy.to')} ${formatDate(medication.end_date)}` : ` (${t('copy.ongoing')})`}
                </Text>
              </View>
            </>
          )}
        </Card>
      </View>

      {/* Instructions */}
      {medication.instructions && (
        <View style={{ marginTop: spacing.base }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
            {t('medications.instructions').toUpperCase()}
          </Text>
          <Card style={styles.detailCard}>
            <Text style={[typography.body, { color: colors.textPrimary, textAlign, lineHeight: 22 }]}>
              {medication.instructions}
            </Text>
          </Card>
        </View>
      )}

      {/* Doctor Notes */}
      {medication.doctor_notes && (
        <View style={{ marginTop: spacing.base }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
            {t('medications.doctorNotes').toUpperCase()}
          </Text>
          <Card style={[styles.detailCard, { backgroundColor: colors.primaryLight }]}>
            <Text style={[typography.body, { color: colors.textPrimary, textAlign, lineHeight: 22 }]}>
              « {medication.doctor_notes} »
            </Text>
          </Card>
        </View>
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  heroCard: {
    marginVertical: 8,
  },
  heroRow: {
    alignItems: 'center',
  },
  iconWrapper: {
    width: 64,
    height: 64,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 12,
  },
  heroTextCol: {
    flex: 1,
    paddingHorizontal: 4,
  },
  pillBadge: {
    alignSelf: 'flex-start',
    paddingVertical: 4,
    paddingHorizontal: 10,
  },
  safetyBanner: {
    borderWidth: 1,
    padding: 12,
    alignItems: 'center',
    marginVertical: 8,
  },
  detailCard: {
    padding: 16,
  },
  detailRow: {
    marginVertical: 6,
  },
  divider: {
    height: 1,
    width: '100%',
    marginVertical: 8,
  },
});
