import React from 'react';
import { View, Text, Image, StyleSheet, ViewStyle } from 'react-native';
import { useTheme } from '../../theme';

interface AvatarProps {
  url?: string;
  name?: string;
  size?: number;
  style?: ViewStyle;
}

export const Avatar: React.FC<AvatarProps> = ({
  url,
  name,
  size = 48,
  style,
}) => {
  const { colors, typography, radii } = useTheme();

  const getInitials = (n?: string): string => {
    if (!n) return 'P';
    const parts = n.trim().split(' ');
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    }
    return n.slice(0, 2).toUpperCase();
  };

  if (url) {
    return (
      <Image
        source={{ uri: url }}
        style={[
          styles.avatar,
          {
            width: size,
            height: size,
            borderRadius: radii.full,
          },
          style as any,
        ]}
      />
    );
  }

  return (
    <View
      style={[
        styles.fallback,
        {
          width: size,
          height: size,
          borderRadius: radii.full,
          backgroundColor: colors.primaryLight,
          borderColor: colors.primary,
          borderWidth: 1,
        },
        style,
      ]}
    >
      <Text
        style={[
          typography.subtitle,
          { color: colors.primary, fontWeight: '700' },
        ]}
      >
        {getInitials(name)}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  avatar: {
    resizeMode: 'cover',
  },
  fallback: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
