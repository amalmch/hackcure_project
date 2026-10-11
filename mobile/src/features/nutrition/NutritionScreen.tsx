import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { nutritionApi } from '../../services/api/nutrition';
import { patientApi } from '../../services/api/patient';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { NutritionCard } from '../../components/cards/NutritionCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

export const NutritionScreen: React.FC = () => {
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();

  const {
    data: plans,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['nutritionPlans'],
    queryFn: nutritionApi.getPlans,
  });

  const { data: summary } = useQuery({
    queryKey: ['treatmentSummary'],
    queryFn: patientApi.getTreatmentSummary,
  });

  const nutReco = summary?.nutrition_recommendations;

  if (isLoading && !plans) {
    return (
      <ScreenContainer>
        <Header title={t('nutrition.title')} showBack />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isError && !plans) {
    return (
      <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
        <Header title={t('nutrition.title')} showBack />
        <ErrorState
          title={t('copy.loadNutrition')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={t('nutrition.title')} showBack />

      {/* Medical Disclaimer */}
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
          {i18n.t('copy.static_conseils_nutritionnels_valides_selon_votre_bilan')}</Text>
      </View>

      {/* Recommendations extracted from Doctor's report */}
      {nutReco && (
        <View
          style={[
            styles.recoCard,
            {
              backgroundColor: colors.card,
              borderColor: colors.cardBorder,
              borderRadius: radii.md,
            },
          ]}
        >
          <Text style={[typography.bodyBold, { color: colors.textPrimary, textAlign, marginBottom: 4 }]}>
            {i18n.t('copy.static_regime_recommande')}{' '}{nutReco.regime_type || t('copy.balancedDiet')}
          </Text>

          {nutReco.conseils && (
            <Text style={[typography.caption, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
              {nutReco.conseils}
            </Text>
          )}

          {/* Vitals targets */}
          <View style={[styles.targetRow, { flexDirection }]}>
            {nutReco.hydratation_ml && (
              <View style={[styles.targetPill, { backgroundColor: colors.infoLight }]}>
                <Ionicons name="water-outline" size={14} color={colors.info} style={{ marginRight: 4 }} />
                <Text style={[typography.tiny, { color: colors.info, fontWeight: '700' }]}>
                  {nutReco.hydratation_ml} {' '}{i18n.t('copy.static_ml_jour')}</Text>
              </View>
            )}
            {nutReco.calories_cible && (
              <View style={[styles.targetPill, { backgroundColor: colors.warningLight }]}>
                <Ionicons name="flame-outline" size={14} color={colors.warning} style={{ marginRight: 4 }} />
                <Text style={[typography.tiny, { color: colors.warning, fontWeight: '700' }]}>
                  {nutReco.calories_cible} {' '}{i18n.t('copy.static_kcal_jour')}</Text>
              </View>
            )}
          </View>

          {/* Foods to prioritize */}
          {nutReco.a_privilegier && nutReco.a_privilegier.length > 0 && (
            <View style={{ marginTop: 8 }}>
              <Text style={[typography.captionBold, { color: colors.success, textAlign, marginBottom: 4 }]}>
                {i18n.t('copy.static_a_privilegier')}</Text>
              <View style={[styles.badgeWrap, { flexDirection }]}>
                {nutReco.a_privilegier.map((food, i) => (
                  <View key={i} style={[styles.tag, { backgroundColor: colors.successLight }]}>
                    <Text style={[typography.tiny, { color: colors.success, fontWeight: '600' }]}>
                      ✓ {food}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}

          {/* Foods to limit */}
          {nutReco.a_limiter && nutReco.a_limiter.length > 0 && (
            <View style={{ marginTop: 8 }}>
              <Text style={[typography.captionBold, { color: colors.error, textAlign, marginBottom: 4 }]}>
                {i18n.t('copy.static_a_limiter_eviter')}</Text>
              <View style={[styles.badgeWrap, { flexDirection }]}>
                {nutReco.a_limiter.map((food, i) => (
                  <View key={i} style={[styles.tag, { backgroundColor: colors.errorLight }]}>
                    <Text style={[typography.tiny, { color: colors.error, fontWeight: '600' }]}>
                      ✕ {food}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}
        </View>
      )}

      {(!plans || plans.length === 0) && !nutReco ? (
        <EmptyState
          icon="nutrition-outline"
          title={t('copy.noNutritionPlan')}
          description={t('copy.noNutritionPlanDescription')}
        />
      ) : (
        (plans || []).map((plan) => (
          <View key={plan.id} style={{ marginBottom: spacing.md }}>
            <NutritionCard plan={plan} />
          </View>
        ))
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  disclaimerBox: {
    padding: 8,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 10,
  },
  recoCard: {
    padding: 12,
    borderWidth: 1,
    marginBottom: 12,
  },
  targetRow: {
    gap: 8,
    marginBottom: 6,
  },
  targetPill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  badgeWrap: {
    flexWrap: 'wrap',
    gap: 6,
  },
  tag: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
});
