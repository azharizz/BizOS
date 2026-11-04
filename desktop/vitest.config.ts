import { defineConfig } from 'vitest/config'

// The Chrome extension's DOM reader is tested here too (jsdom), so it has no toolchain of its own.
export default defineConfig({
  server: { fs: { allow: ['..'] } },
  test: { dir: '..', include: ['desktop/src/**/*.test.ts', 'chrome_extension/**/*.test.js'] },
})
