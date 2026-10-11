import i18n from '../../i18n';
import React, { useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useTheme } from '../../theme';
import { appointmentsApi } from '../../services/api/appointments';
import { AppointmentStatus } from '../../types';
import { isPast } from '../../utils/dateUtils';
import { ScreenContainer } from '../../components/layout/ScreenContainer';
import { Header } from '../../components/layout/Header';
import { TabBar } from '../../components/ui/TabBar';
import { AppointmentCard } from '../../components/cards/AppointmentCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { CardSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';

export const AppointmentListScreen: React.FC = () => {
  const router = useRouter();
  const { spacing } = useTheme();
  const { t } = useTranslation();

  const [activeTab, setActiveTab] = useState<'upcoming' | 'past'>('upcoming');

  const {
    data: appointments,
    isLoading,
    isError,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['appointments'],
    queryFn: appointmentsApi.getAppointments,
  });

  const tabs = [
    { key: 'upcoming' as const, label: t('appointments.upcomingTab') },
    { key: 'past' as const, label: t('appointments.pastTab') },
  ];

  if (isLoading && !appointments) {
    return (
      <ScreenContainer>
        <Header title={t('appointments.title')} showBack />
        <CardSkeleton />
        <CardSkeleton />
      </ScreenContainer>
    );
  }

  if (isError && !appointments) {
    return (
      <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
        <Header title={t('appointments.title')} showBack />
        <ErrorState
          title={i18n.t('copy.static_could_not_load_appointments')}
          onRetry={refetch}
        />
      </ScreenContainer>
    );
  }

  const upcomingList = (appointments || []).filter((a) => {
    return a.status !== AppointmentStatus.CANCELLED && a.status !== AppointmentStatus.COMPLETED && !isPast(a.appointment_date);
  });

  const pastList = (appointments || []).filter((a) => {
    return a.status === AppointmentStatus.COMPLETED || a.status === AppointmentStatus.CANCELLED || isPast(a.appointment_date);
  });

  const displayedList = activeTab === 'upcoming' ? upcomingList : pastList;

  return (
    <ScreenContainer onRefresh={refetch} refreshing={isRefetching}>
      <Header title={t('appointments.title')} showBack />

      <TabBar
        tabs={tabs}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      <View style={{ marginTop: spacing.sm }}>
        {displayedList.length === 0 ? (
          <EmptyState
            icon="calendar-outline"
            title={activeTab === 'upcoming' ? t('home.noAppointments') : t('copy.noPastVisits')}
          />
        ) : (
          displayedList.map((appointment) => (
            <AppointmentCard
              key={appointment.id}
              appointment={appointment}
              onPress={() => router.push(`/appointment/${appointment.id}` as any)}
            />
          ))
        )}
      </View>
    </ScreenContainer>
  );
};
