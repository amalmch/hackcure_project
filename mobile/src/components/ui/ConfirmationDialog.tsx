import React from 'react';
import {
  Modal,
  View,
  Text,
  StyleSheet,
  TouchableWithoutFeedback,
} from 'react-native';
import { useTheme } from '../../theme';
import { useRTL } from '../../i18n/RTLContext';
import { PrimaryButton } from './PrimaryButton';
import { SecondaryButton } from './SecondaryButton';
import { useTranslation } from 'react-i18next';

interface ConfirmationDialogProps {
  visible: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
  onCancel: () => void;
  isDestructive?: boolean;
  loading?: boolean;
}

export const ConfirmationDialog: React.FC<ConfirmationDialogProps> = ({
  visible,
  title,
  message,
  confirmText,
  cancelText,
  onConfirm,
  onCancel,
  isDestructive = false,
  loading = false,
}) => {
  const { colors, typography, radii, spacing } = useTheme();
  const { flexDirection, textAlign } = useRTL();
  const { t } = useTranslation();

  return (
    <Modal
      transparent
      visible={visible}
      animationType="fade"
      onRequestClose={onCancel}
    >
      <TouchableWithoutFeedback onPress={onCancel}>
        <View style={styles.backdrop}>
          <TouchableWithoutFeedback>
            <View
              style={[
                styles.dialog,
                {
                  backgroundColor: colors.surface,
                  borderRadius: radii.xl,
                  padding: spacing.xl,
                },
              ]}
            >
              <Text
                style={[
                  typography.h3,
                  styles.title,
                  { color: colors.textPrimary, textAlign },
                ]}
              >
                {title}
              </Text>
              <Text
                style={[
                  typography.body,
                  styles.message,
                  { color: colors.textSecondary, textAlign },
                ]}
              >
                {message}
              </Text>

              <View style={[styles.buttonRow, { flexDirection }]}>
                <SecondaryButton
                  title={cancelText || t('common.cancel')}
                  onPress={onCancel}
                  style={styles.actionBtn}
                />
                <PrimaryButton
                  title={confirmText || t('common.confirm')}
                  onPress={onConfirm}
                  loading={loading}
                  variant={isDestructive ? 'danger' : 'primary'}
                  style={styles.actionBtn}
                />
              </View>
            </View>
          </TouchableWithoutFeedback>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  dialog: {
    width: '100%',
    maxWidth: 400,
  },
  title: {
    marginBottom: 8,
  },
  message: {
    marginBottom: 24,
    lineHeight: 22,
  },
  buttonRow: {
    justifyContent: 'space-between',
    gap: 12,
  },
  actionBtn: {
    flex: 1,
  },
});
