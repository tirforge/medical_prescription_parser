import { defineConfig } from '@playwright/test';
import fs from 'fs';

let apiKey = '';
try {
  const m = fs.readFileSync('keys.py', 'utf8').match(/GOOGLE_API_KEY\s*=\s*["']([^"']+)["']/);
  if (m) apiKey = m[1];
} catch {}

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.js',
  webServer: {
    command: 'python -m uvicorn api:app --host 127.0.0.1 --port 8000',
    url: 'http://127.0.0.1:8000/health',
    env: { GOOGLE_API_KEY: apiKey, GEMINI_MODEL: 'gemini-3.5-flash-lite' },
    timeout: 30 * 1000,
    reuseExistingServer: !process.env.CI,
  },
  use: { baseURL: 'http://127.0.0.1:8000' },
});
