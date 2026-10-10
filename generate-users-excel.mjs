// Run with: node generate-users-excel.mjs
// Exports all configured local demo credentials from backend/.env.
// Output: users-credentials-updated-with-passwords.xlsx (the existing workbook may be open).

import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const require = createRequire(new URL('./frontend/package.json', import.meta.url));
const XLSX = require('xlsx');

const envText = readFileSync(resolve('backend/.env'), 'utf8');
const bootstrapLine = envText.split(/\r?\n/).find(line => line.startsWith('BOOTSTRAP_USERS_JSON='));
if (!bootstrapLine) throw new Error('BOOTSTRAP_USERS_JSON was not found in backend/.env');
const provisionedUsers = JSON.parse(bootstrapLine.slice('BOOTSTRAP_USERS_JSON='.length));
const roleLabels = {
  PRODUCER: 'Factory Coordinator',
  RECYCLER_EMPLOYEE: 'Recycler',
  GOVERNMENT_OFFICER: 'Government Official',
  ADMINISTRATOR: 'Administrator',
};
const users = provisionedUsers
  .filter(user => roleLabels[user.role])
  .map(user => ({ ...user, role: roleLabels[user.role] }));
if (users.length === 0) throw new Error('No non-administrator demo users were found');

const rows = users.map((user, index) => ({
  'S.No': index + 1,
  'Display Name': user.display_name,
  'Username': user.username,
  'Password': user.password,
  'Role': user.role,
  'Organisation': user.organisation,
  'Department': user.department || '—',
}));

const workbook = XLSX.utils.book_new();
const sheet = XLSX.utils.json_to_sheet(rows);
sheet['!cols'] = [
  { wch: 6 }, { wch: 26 }, { wch: 28 }, { wch: 32 },
  { wch: 24 }, { wch: 42 }, { wch: 34 },
];
XLSX.utils.book_append_sheet(workbook, sheet, 'User Credentials');
XLSX.writeFile(workbook, 'users-credentials-updated-with-passwords.xlsx');
console.log('Local demo credentials workbook generated. Keep this file private.');
