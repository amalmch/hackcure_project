import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { NutritionPlan, MealRecommendation } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';

interface NutritionCardProps {
  plan: NutritionPlan;
}

export const NutritionCard: React.FC<NutritionCardProps> = ({ plan }) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  return (
    <Card style={styles.card}>
      <View style={[styles.headerRow, { flexDirection }]}>
        <View
          style={[
            styles.iconWrapper,
            { backgroundColor: colors.secondaryLight, borderRadius: radii.lg },
          ]}
        >
          <Ionicons name="nutrition-outline" size={24} color={colors.secondary} />
        </View>

        <View style={styles.titleColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {plan.plan_type || t('nutrition.title')}
          </Text>
          <Text style={[typography.caption, { color: colors.secondary, textAlign, fontWeight: '600' }]}>
            {i18n.t('copy.static_prescribed_by_medical_care_team')}</Text>
        </View>
      </View>

      {/* Hydration and Calorie Targets */}
      {(plan.hydration_ml_daily || plan.calories_target) && (
        <View style={[styles.targetsRow, { flexDirection, marginTop: spacing.md }]}>
          {plan.hydration_ml_daily && (
            <View
              style={[
                styles.targetBadge,
                { backgroundColor: colors.infoLight, borderRadius: radii.md },
              ]}
            >
              <Ionicons name="water-outline" size={16} color={colors.info} />
              <Text style={[typography.captionBold, { color: colors.info, marginHorizontal: 4 }]}>
                {plan.hydration_ml_daily} mL / jour
              </Text>
            </View>
          )}

          {plan.calories_target && (
            <View
              style={[
                styles.targetBadge,
                { backgroundColor: colors.warningLight, borderRadius: radii.md },
              ]}
            >
              <Ionicons name="flame-outline" size={16} color={colors.warning} />
              <Text style={[typography.captionBold, { color: colors.warning, marginHorizontal: 4 }]}>
                {plan.calories_target} kcal / jour
              </Text>
            </View>
          )}
        </View>
      )}

      {/* Recommended Foods */}
      {plan.recommended_foods && plan.recommended_foods.length > 0 && (
        <View style={{ marginTop: spacing.md }}>
          <Text style={[typography.captionBold, { color: colors.success, textAlign, marginBottom: 4 }]}>
            ✓ {t('nutrition.recommendedFoods')}
          </Text>
          <View style={[styles.tagsContainer, { flexDirection }]}>
            {plan.recommended_foods.map((food, idx) => (
              <View
                key={idx}
                style={[
                  styles.tag,
                  { backgroundColor: colors.successLight, borderRadius: radii.md },
                ]}
              >
                <Text style={[typography.tiny, { color: colors.success, fontWeight: '600' }]}>
                  {food}
                </Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {/* Foods to Avoid */}
      {plan.foods_to_avoid && plan.foods_to_avoid.length > 0 && (
        <View style={{ marginTop: spacing.sm }}>
          <Text style={[typography.captionBold, { color: colors.error, textAlign, marginBottom: 4 }]}>
            ⚠ {t('nutrition.foodsToAvoid')}
          </Text>
          <View style={[styles.tagsContainer, { flexDirection }]}>
            {plan.foods_to_avoid.map((food, idx) => (
              <View
                key={idx}
                style={[
                  styles.tag,
                  { backgroundColor: colors.errorLight, borderRadius: radii.md },
                ]}
              >
                <Text style={[typography.tiny, { color: colors.error, fontWeight: '600' }]}>
                  {food}
                </Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {/* Meals Guidance */}
      {plan.meal_recommendations && plan.meal_recommendations.length > 0 && (
        <View style={{ marginTop: spacing.md }}>
          <Text style={[typography.captionBold, { color: colors.textPrimary, textAlign, marginBottom: 6 }]}>
            {t('nutrition.mealSuggestions')}
          </Text>
          {plan.meal_recommendations.map((meal: MealRecommendation, idx) => (
            <View
              key={idx}
              style={[
                styles.mealItem,
                { backgroundColor: colors.inputBg, borderRadius: radii.md, marginBottom: 6 },
              ]}
            >
              <Text style={[typography.captionBold, { color: colors.textPrimary, textAlign }]}>
                {meal.meal}
              </Text>
              <Text style={[typography.tiny, { color: colors.textSecondary, textAlign, marginTop: 2 }]}>
                {meal.description}
              </Text>
            </View>
          ))}
        </View>
      )}

      {/* Doctor / Dietitian Notes */}
      {(plan.doctor_notes || plan.dietitian_notes) && (
        <View
          style={[
            styles.notesBox,
            {
              backgroundColor: colors.inputBg,
              borderRadius: radii.md,
              marginTop: spacing.md,
            },
          ]}
        >
          <Text style={[typography.captionBold, { color: colors.textPrimary, textAlign, marginBottom: 2 }]}>
            {t('medications.doctorNotes')}
          </Text>
          <Text style={[typography.tiny, { color: colors.textSecondary, textAlign }]}>
            {plan.doctor_notes || plan.dietitian_notes}
          </Text>
        </View>
      )}
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 6,
  },
  headerRow: {
    alignItems: 'center',
  },
  iconWrapper: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginHorizontal: 8,
  },
  titleColumn: {
    flex: 1,
    paddingHorizontal: 4,
  },
  targetsRow: {
    gap: 8,
    flexWrap: 'wrap',
  },
  targetBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  tagsContainer: {
    flexWrap: 'wrap',
    gap: 6,
  },
  tag: {
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  mealItem: {
    padding: 8,
  },
  notesBox: {
    padding: 10,
  },
});
