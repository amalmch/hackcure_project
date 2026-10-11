import { useWindowDimensions } from 'react-native';

export type ScreenSize = 'small' | 'standard' | 'large' | 'tablet';

export function useResponsiveLayout() {
  const { width, height, fontScale } = useWindowDimensions();
  const screenSize: ScreenSize = width <= 360
    ? 'small'
    : width >= 768
      ? 'tablet'
      : width >= 412
        ? 'large'
        : 'standard';

  return {
    width,
    height,
    fontScale,
    screenSize,
    contentMaxWidth: screenSize === 'tablet' ? 760 : undefined,
    horizontalPadding: screenSize === 'small' ? 12 : screenSize === 'tablet' ? 24 : 16,
    isTablet: screenSize === 'tablet',
  } as const;
}
