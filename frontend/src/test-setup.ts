import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
