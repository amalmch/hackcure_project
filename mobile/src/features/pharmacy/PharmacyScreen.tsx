import i18n from '../../i18n';
import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { pharmaciesApi } from '../../services/api/pharmacies';
import { prescriptionsApi } from '../../services/api/prescriptions';
import { PrescriptionItem } from '../../types';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { SearchBar } from '../../components/ui/SearchBar';
import { TabBar } from '../../components/ui/TabBar';
import { PharmacyCard } from '../../components/cards/PharmacyCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

interface MedicineStockItemProps {
  med: PrescriptionItem;
  lat?: number;
  lng?: number;
}

const MedicineStockItem: React.FC<MedicineStockItemProps> = ({ med, lat, lng }) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();

  const { data: availabilities, isLoading } = useQuery({
    queryKey: ['medicineAvailability', med.medication_name, lat, lng],
    queryFn: () => pharmaciesApi.getMedicineAvailability(med.medication_name, lat, lng),
  });

  return (
    <View style={[styles.medStockContainer, { backgroundColor: colors.card, borderColor: colors.cardBorder, borderRadius: radii.md }]}>
      <View style={[styles.medHeaderRow, { flexDirection }]}>
        <View style={{ flex: 1 }}>
          <Text style={[typography.h4, { color: colors.primary, textAlign }]}>
            💊 {med.medication_name} ({med.dosage})
          </Text>
          <Text style={[typography.caption, { color: colors.textSecondary, textAlign }]}>
            {i18n.t('copy.static_posologie')}{' '}{med.frequency} {med.duration_days ? `• ${i18n.t('copy.durationDays', { count: med.duration_days })}` : ''}
          </Text>
        </View>
        {med.quantity_prescribed && (
          <View style={[styles.qtyBadge, { backgroundColor: colors.primaryLight }]}>
            <Text style={[typography.tiny, { color: colors.primary, fontWeight: '700' }]}>
              {i18n.t('copy.static_qte')}{' '}{med.quantity_prescribed}
            </Text>
          </View>
        )}
      </View>

      {isLoading ? (
        <View style={{ marginVertical: 8 }}>
          <CardSkeleton />
        </View>
      ) : !availabilities || availabilities.length === 0 ? (
        <View style={[styles.outOfStockBox, { backgroundColor: colors.warningLight, borderRadius: radii.sm }]}>
          <Ionicons name="alert-circle-outline" size={16} color={colors.warning} style={{ marginRight: 6 }} />
          <Text style={[typography.tiny, { color: colors.warning, flex: 1, textAlign }]}>
            {i18n.t('copy.static_non_repertorie_en_stock_immediat_contactez_votre')}</Text>
        </View>
      ) : (
        <View style={{ marginTop: 8 }}>
          <Text style={[typography.tiny, { color: colors.textSecondary, textAlign, marginBottom: 6 }]}>
            {i18n.t('copy.static_pharmacies_partenaires_avec_stock_verifie')}{availabilities.length})
          </Text>
          {availabilities.map((avail, index) => (
            <View key={index} style={{ marginBottom: spacing.xs }}>
              <PharmacyCard
                pharmacy={avail.pharmacy}
                inventory={avail.inventory}
              />
            </View>
          ))}
        </View>
      )}
    </View>
  );
};

export const PharmacyScreen: React.FC = () => {
  const { colors, typography, spacing, radii } = useTheme();
  const { textAlign, flexDirection } = useRTL();
  const { t } = useTranslation();

  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'prescriptions' | 'nearby'>('prescriptions');
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { status } = await Location.getForegroundPermissionsAsync();
        if (status === 'granted') {
          const loc = await Location.getCurrentPositionAsync({});
          setUserLocation({ lat: loc.coords.latitude, lng: loc.coords.longitude });
        }
      } catch {
        // Default to city center
      }
    })();
  }, []);

  // Fetch active prescriptions
  const { data: prescriptions } = useQuery({
    queryKey: ['activePrescriptions'],
    queryFn: prescriptionsApi.getActivePrescriptions,
  });

  // Fetch nearby pharmacies
  const {
    data: pharmacies,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['nearbyPharmacies', userLocation?.lat, userLocation?.lng],
    queryFn: () =>
      pharmaciesApi.getNearby(userLocation?.lat || 36.8065, userLocation?.lng || 10.1815, 15),
  });

  const activePrescription = prescriptions?.[0];
  const prescribedMedicines = activePrescription?.items || [];

  const tabs = [
    { key: 'prescriptions' as const, label: t('pharmacy.prescribedMedicinesStock') },
    { key: 'nearby' as const, label: t('pharmacy.nearbyPharmacies') },
  ];

  const filteredPharmacies = (pharmacies || []).filter((p) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return p.name.toLowerCase().includes(q) || p.address.toLowerCase().includes(q);
  });

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={t('pharmacy.title')} />

      <SearchBar
        value={searchQuery}
        onChangeText={setSearchQuery}
        placeholder={t('pharmacy.searchPlaceholder')}
      />

      <TabBar
        tabs={tabs}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      {/* Safety Notice & Disclaimer */}
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
        <Ionicons name="information-circle-outline" size={18} color={colors.textSecondary} style={{ marginHorizontal: 6 }} />
        <Text style={[typography.tiny, { color: colors.textSecondary, flex: 1, textAlign }]}>
          {i18n.t('copy.static_les_disponibilites_en_pharmacie_sont_indicatives')}</Text>
      </View>

      {isLoading && !pharmacies ? (
        <View style={{ marginTop: spacing.md }}>
          <CardSkeleton />
          <CardSkeleton />
        </View>
      ) : isError && !pharmacies ? (
        <ErrorState
          title={i18n.t('copy.static_could_not_connect_to_pharmacy_network')}
          onRetry={refetch}
        />
      ) : activeTab === 'prescriptions' ? (
        <View style={{ marginTop: spacing.sm }}>
          <Text style={[typography.captionBold, { color: colors.textSecondary, textAlign, marginBottom: 8 }]}>
            {i18n.t('copy.static_disponibilites_reelles_par_medicament_prescrit')}</Text>

          {prescribedMedicines.length === 0 ? (
            <EmptyState
              icon="medical-outline"
              title={i18n.t('copy.static_aucun_medicament_actif_prescrit')}
              description={i18n.t('copy.static_les_recherches_de_stock_en_pharmacie_s_appliquen')}
            />
          ) : (
            prescribedMedicines.map((med) => (
              <MedicineStockItem
                key={med.id}
                med={med}
                lat={userLocation?.lat}
                lng={userLocation?.lng}
              />
            ))
          )}
        </View>
      ) : (
        <View style={{ marginTop: spacing.md }}>
          {filteredPharmacies.length === 0 ? (
            <EmptyState
              icon="business-outline"
              title={i18n.t('copy.static_aucune_pharmacie_trouvee')}
              description={i18n.t('copy.static_aucune_pharmacie_ne_correspond_a_votre_recherche')}
            />
          ) : (
            filteredPharmacies.map((pharmacy) => (
              <PharmacyCard key={pharmacy.id} pharmacy={pharmacy} />
            ))
          )}
        </View>
      )}
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  noticeBox: {
    borderWidth: 1,
    padding: 10,
    alignItems: 'center',
    marginBottom: 8,
  },
  medStockContainer: {
    padding: 12,
    borderWidth: 1,
    marginBottom: 12,
  },
  medHeaderRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  qtyBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  outOfStockBox: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 8,
    marginTop: 6,
  },
});
