import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { medicationsApi } from '../../services/api/medications';
import { MedicationDose } from '../../types';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { formatDate, formatTime } from '../../utils/dateUtils';

export const DoseHistoryScreen: React.FC = () => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const [filter, setFilter] = useState<'ALL' | 'TAKEN' | 'MISSED'>('ALL');

  const {
    data: doses,
    isLoading,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['doseHistory'],
    queryFn: () => medicationsApi.getDoseHistory(30),
  });

  const filteredDoses = (doses || []).filter((d) => {
    if (filter === 'TAKEN') return d.status.startsWith('TAKEN');
    if (filter === 'MISSED') return d.status === 'MISSED';
    return true;
  });

  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'TAKEN_ON_TIME':
        return { label: i18n.t('labels.takenOnTime'), color: colors.success, icon: 'checkmark-circle' };
      case 'TAKEN_LATE':
        return { label: i18n.t('labels.takenLate'), color: colors.warning, icon: 'alert-circle' };
      case 'MISSED':
        return { label: i18n.t('labels.missed'), color: colors.error, icon: 'close-circle' };
      case 'DUE':
        return { label: i18n.t('labels.due'), color: colors.warning, icon: 'time' };
      default:
        return { label: i18n.t('labels.scheduled'), color: colors.info, icon: 'calendar' };
    }
  };

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={i18n.t('copy.static_historique_des_prises')} showBack />

      {/* Filter Chips */}
      <View style={[styles.filterRow, { flexDirection }]}>
        {(['ALL', 'TAKEN', 'MISSED'] as const).map((f) => (
          <TouchableOpacity
            key={f}
            onPress={() => setFilter(f)}
            style={[
              styles.filterChip,
              {
                backgroundColor: filter === f ? colors.primary : colors.inputBg,
                borderColor: filter === f ? colors.primary : colors.cardBorder,
                borderRadius: radii.full,
              },
            ]}
          >
            <Text
              style={[
                typography.captionBold,
                { color: filter === f ? colors.textInverse : colors.textSecondary },
              ]}
            >
              {f === 'ALL' ? i18n.t('copy.filterAll') : f === 'TAKEN' ? i18n.t('copy.filterTaken') : i18n.t('copy.filterMissed')}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Disclaimer */}
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
        <Ionicons name="information-circle-outline" size={16} color={colors.textSecondary} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.tiny, { color: colors.textSecondary, flex: 1, textAlign }]}>
          {i18n.t('copy.static_historique_conforme_a_votre_suivi_medical_cette_')}</Text>
      </View>

      {isLoading && !doses ? (
        <View style={{ marginTop: spacing.md }}>
          <CardSkeleton />
          <CardSkeleton />
        </View>
      ) : filteredDoses.length === 0 ? (
        <EmptyState
          icon="time-outline"
          title={i18n.t('copy.static_aucun_historique_pour_cette_periode')}
          description={i18n.t('copy.static_les_prises_confirmees_et_oubliees_s_afficheront_')}
        />
      ) : (
        <FlatList
          data={filteredDoses}
          keyExtractor={(item) => item.id}
          scrollEnabled={false}
          renderItem={({ item }) => {
            const statusConfig = getStatusConfig(item.status);
            const medName = item.prescription_item?.medication_name || i18n.t('labels.medication');
            const dosage = item.prescription_item?.dosage || '';
            const takenTimeStr = item.taken_at
              ? formatTime(item.taken_at)
              : null;

            return (
              <View
                style={[
                  styles.historyCard,
                  {
                    backgroundColor: colors.card,
                    borderColor: colors.cardBorder,
                    borderRadius: radii.md,
                  },
                ]}
              >
                <View style={[styles.cardHeader, { flexDirection }]}>
                  <View style={{ flex: 1 }}>
                    <Text style={[typography.bodyBold, { color: colors.textPrimary, textAlign }]}>
                      • {medName}
                    </Text>
                    <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
                      {dosage} {i18n.t('copy.plannedAt')} {formatTime(item.scheduled_time)} ({formatDate(item.scheduled_date)})
                    </Text>
                  </View>
                  <View style={[styles.badge, { backgroundColor: statusConfig.color + '20' }]}>
                    <Ionicons name={statusConfig.icon as any} size={14} color={statusConfig.color} style={{ marginRight: 4 }} />
                    <Text style={[typography.tiny, { color: statusConfig.color, fontWeight: '700' }]}>
                      {statusConfig.label}
                    </Text>
                  </View>
                </View>

                {takenTimeStr && (
                  <View style={[styles.timestampRow, { flexDirection }]}>
                    <Ionicons name="checkmark-done" size={14} color={colors.success} style={{ marginHorizontal: 4 }} />
                    <Text style={[typography.tiny, { color: colors.success, textAlign }]}>
                      {i18n.t('copy.confirmedOn')}{' '}{formatDate(item.taken_at)}{' '}{i18n.t('copy.at')}{' '}{takenTimeStr}
                    </Text>
                  </View>
                )}
              </View>
            );
          }}
        />
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  filterRow: {
    marginVertical: 10,
    gap: 8,
  },
  filterChip: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderWidth: 1,
  },
  disclaimerBox: {
    padding: 8,
    borderWidth: 1,
    alignItems: 'center',
    marginBottom: 12,
  },
  historyCard: {
    padding: 12,
    borderWidth: 1,
    marginBottom: 10,
  },
  cardHeader: {
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  timestampRow: {
    marginTop: 8,
    alignItems: 'center',
  },
});
