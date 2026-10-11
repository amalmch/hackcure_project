const fs = require('fs');
const path = require('path');

const rootDir = 'c:\\Users\\moham\\Desktop\\hackcure\\mobile';
const dirs = [
  'src/types',
  'src/constants',
  'src/theme',
  'src/i18n/locales',
  'src/services/api',
  'src/store',
  'src/hooks',
  'src/utils',
  'src/components/ui',
  'src/components/cards',
  'src/components/layout',
  'src/features/home',
  'src/features/auth',
  'src/features/onboarding',
  'src/features/treatment',
  'src/features/medications',
  'src/features/adherence',
  'src/features/sport',
  'src/features/nutrition',
  'src/features/pharmacy',
  'src/features/doctor',
  'src/features/appointments',
  'src/features/medical-records',
  'src/features/notifications',
  'src/features/profile',
  'src/features/prescription',
  'app/(auth)',
  'app/(tabs)',
  'app/treatment',
  'app/prescription',
  'app/conversation',
  'app/appointment',
  'app/medical-records',
  'app/settings',
];

dirs.forEach(dir => {
  fs.mkdirSync(path.join(rootDir, dir), { recursive: true });
});

console.log("Directories created successfully!");
