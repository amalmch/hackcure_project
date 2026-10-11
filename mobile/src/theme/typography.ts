import { TextStyle } from 'react-native';

export const typography = {
  fontSizes: {
    xs: 11,
    sm: 13,
    base: 15,
    md: 17,
    lg: 20,
    xl: 24,
    '2xl': 28,
    '3xl': 34,
  },
  fontWeights: {
    regular: '400' as const,
    medium: '500' as const,
    semibold: '600' as const,
    bold: '700' as const,
    heavy: '800' as const,
  },
  lineHeights: {
    tight: 1.15,
    normal: 1.35,
    relaxed: 1.5,
  },
};

export const createTextStyles = (fontScale: number = 1.0) => {
  const scale = (size: number) => Math.round(size * fontScale);

  return {
    h1: {
      fontSize: scale(typography.fontSizes['3xl']),
      fontWeight: typography.fontWeights.bold,
      lineHeight: scale(typography.fontSizes['3xl'] * 1.2),
      letterSpacing: -0.5,
    } as TextStyle,
    h2: {
      fontSize: scale(typography.fontSizes['2xl']),
      fontWeight: typography.fontWeights.bold,
      lineHeight: scale(typography.fontSizes['2xl'] * 1.25),
      letterSpacing: -0.3,
    } as TextStyle,
    h3: {
      fontSize: scale(typography.fontSizes.xl),
      fontWeight: typography.fontWeights.semibold,
      lineHeight: scale(typography.fontSizes.xl * 1.3),
    } as TextStyle,
    h4: {
      fontSize: scale(typography.fontSizes.lg),
      fontWeight: typography.fontWeights.semibold,
      lineHeight: scale(typography.fontSizes.lg * 1.3),
    } as TextStyle,
    subtitle: {
      fontSize: scale(typography.fontSizes.md),
      fontWeight: typography.fontWeights.medium,
      lineHeight: scale(typography.fontSizes.md * 1.35),
    } as TextStyle,
    body: {
      fontSize: scale(typography.fontSizes.base),
      fontWeight: typography.fontWeights.regular,
      lineHeight: scale(typography.fontSizes.base * 1.45),
    } as TextStyle,
    bodyBold: {
      fontSize: scale(typography.fontSizes.base),
      fontWeight: typography.fontWeights.semibold,
      lineHeight: scale(typography.fontSizes.base * 1.45),
    } as TextStyle,
    caption: {
      fontSize: scale(typography.fontSizes.sm),
      fontWeight: typography.fontWeights.regular,
      lineHeight: scale(typography.fontSizes.sm * 1.35),
    } as TextStyle,
    captionBold: {
      fontSize: scale(typography.fontSizes.sm),
      fontWeight: typography.fontWeights.semibold,
      lineHeight: scale(typography.fontSizes.sm * 1.35),
    } as TextStyle,
    tiny: {
      fontSize: scale(typography.fontSizes.xs),
      fontWeight: typography.fontWeights.regular,
      lineHeight: scale(typography.fontSizes.xs * 1.3),
    } as TextStyle,
  };
};
