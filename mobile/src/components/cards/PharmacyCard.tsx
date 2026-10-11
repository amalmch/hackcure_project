import i18n from '../../i18n';
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTranslation } from 'react-i18next';
import { Pharmacy, PharmacyInventory } from '../../types';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { Card } from '../ui/Card';
import { StatusBadge } from '../ui/StatusBadge';

interface PharmacyCardProps {
  pharmacy: Pharmacy;
  inventory?: PharmacyInventory;
  onPress?: () => void;
}

export const PharmacyCard: React.FC<PharmacyCardProps> = ({
  pharmacy,
  inventory,
  onPress,
}) => {
  const { colors, typography, spacing, radii } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  const handleCall = () => {
    if (pharmacy.phone) {
      Linking.openURL(`tel:${pharmacy.phone}`);
    }
  };

  const getStockStatus = () => {
    if (!inventory) return null;
    if (inventory.is_available === true) {
      return {
        label: t('pharmacy.available'),
        color: colors.success,
        bgColor: colors.successLight,
        icon: 'checkmark-circle-outline' as const,
      };
    }
    if (inventory.is_available === false) {
      return {
        label: t('pharmacy.unavailable'),
        color: colors.error,
        bgColor: colors.errorLight,
        icon: 'close-circle-outline' as const,
      };
    }
    return {
      label: t('pharmacy.unknown'),
      color: colors.textMuted,
      bgColor: colors.inputBg,
      icon: 'help-circle-outline' as const,
    };
  };

  const stockInfo = getStockStatus();

  return (
    <Card onPress={onPress} style={styles.card}>
      <View style={[styles.headerRow, { flexDirection }]}>
        <View style={styles.titleColumn}>
          <Text style={[typography.h4, { color: colors.textPrimary, textAlign }]}>
            {pharmacy.name}
          </Text>
          <View style={[styles.metaRow, { flexDirection, marginTop: 4 }]}>
            <Ionicons name="location-outline" size={14} color={colors.textMuted} style={{ marginHorizontal: 2 }} />
            <Text style={[typography.caption, { color: colors.textSecondary }]}>
              {pharmacy.address}{pharmacy.city ? `, ${pharmacy.city}` : ''}
            </Text>
          </View>
        </View>

        {typeof pharmacy.distance_km === 'number' && Number.isFinite(pharmacy.distance_km) && (
          <View
            style={[
              styles.distanceBadge,
              { backgroundColor: colors.primaryLight, borderRadius: radii.full },
            ]}
          >
            <Text style={[typography.tiny, { color: colors.primary, fontWeight: '700' }]}>
              {pharmacy.distance_km.toFixed(1)} km
            </Text>
          </View>
        )}
      </View>

      {stockInfo && (
        <View style={[styles.stockRow, { flexDirection, marginTop: spacing.md }]}>
          <StatusBadge
            label={stockInfo.label}
            color={stockInfo.color}
            bgColor={stockInfo.bgColor}
            icon={<Ionicons name={stockInfo.icon} size={14} color={stockInfo.color} />}
          />
          {inventory?.medication_name && (
            <Text style={[typography.captionBold, { color: colors.textPrimary, marginHorizontal: 8 }]}>
              {inventory.medication_name} • {inventory.dosage}
            </Text>
          )}
        </View>
      )}

      <View style={[styles.footerRow, { flexDirection, marginTop: spacing.md }]}>
        {pharmacy.is_24h ? (
          <View style={[styles.tag, { backgroundColor: colors.successLight, borderRadius: radii.md }]}>
            <Text style={[typography.tiny, { color: colors.success, fontWeight: '700' }]}>
              {t('pharmacy.open24h')}
            </Text>
          </View>
        ) : (
          <Text style={[typography.tiny, { color: colors.textMuted }]}>
            {i18n.t('copy.static_hours_08_30_20_00')}</Text>
        )}

        {pharmacy.phone && (
          <TouchableOpacity
            onPress={handleCall}
            activeOpacity={0.7}
            style={[
              styles.callBtn,
              { backgroundColor: colors.inputBg, borderRadius: radii.full },
            ]}
          >
            <Ionicons name="call-outline" size={16} color={colors.primary} />
            <Text style={[typography.captionBold, { color: colors.primary, marginHorizontal: 4 }]}>
              {t('pharmacy.callPharmacy')}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    </Card>
  );
};

const styles = StyleSheet.create({
  card: {
    marginVertical: 6,
  },
  headerRow: {
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  titleColumn: {
    flex: 1,
    paddingHorizontal: 2,
  },
  metaRow: {
    alignItems: 'center',
  },
  distanceBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    marginLeft: 8,
  },
  stockRow: {
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  footerRow: {
    alignItems: 'center',
    justifyContent: 'space-between',
    borderTopWidth: 1,
    borderTopColor: '#F1F5F9',
    paddingTop: 10,
  },
  tag: {
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  callBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
});
