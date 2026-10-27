import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { existsSync } from 'node:fs';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: { esbuildOptions: {
    tsconfig: fileURLToPath(new URL('./tsconfig.json', import.meta.url)),
    // Native esbuild otherwise traverses inaccessible ancestors on restricted Windows hosts.
    plugins: [{ name: 'local-relative-files', setup(build) {
      build.onResolve({ filter: /^\.\.?\// }, args => {
        const path = resolve(args.resolveDir, args.path);
        if (existsSync(path) && /\.[cm]?[jt]sx?$/.test(path)) return { path };
      });
    } }],
  } },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'] },
});
