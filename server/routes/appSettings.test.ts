import { describe, it, expect, beforeEach, vi } from 'vitest';
import express from 'express';
import request from 'supertest';
import appSettingsRoutes from './appSettings.js';

vi.mock('../database/db.js', () => ({
  appSettingsDb: {
    getAll: vi.fn(),
    setValue: vi.fn(),
  },
}));

vi.mock('../middleware/auth.js', () => ({
  authenticateToken: (
    _req: express.Request,
    _res: express.Response,
    next: express.NextFunction,
  ) => next(),
  requireAdmin: (
    _req: express.Request,
    _res: express.Response,
    next: express.NextFunction,
  ) => next(),
}));

import { appSettingsDb } from '../database/db.js';

interface ValidationErrorBody {
  error: 'Validation failed';
  issues: unknown;
}

describe('PUT /api/app-settings', () => {
  let app: express.Application;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(appSettingsDb.getAll).mockReturnValue({
      internal_tool_name: 'Ralphy',
      github_pr_trigger: 'ralphy',
      scripts_dir: '/srv/ralphy/scripts',
    });
    vi.mocked(appSettingsDb.setValue).mockImplementation((_k, v) => v);

    app = express();
    app.use(express.json());
    app.use('/api/app-settings', appSettingsRoutes);
  });

  it('accepts a free-text key update', async () => {
    const res = await request(app)
      .put('/api/app-settings')
      .send({ internal_tool_name: 'Atelier' });

    expect(res.status).toBe(200);
    expect(appSettingsDb.setValue).toHaveBeenCalledWith('internal_tool_name', 'Atelier');
  });

  it('normalizes the github_pr_trigger', async () => {
    const res = await request(app)
      .put('/api/app-settings')
      .send({ github_pr_trigger: '@MyBot' });

    expect(res.status).toBe(200);
    expect(appSettingsDb.setValue).toHaveBeenCalledWith('github_pr_trigger', 'mybot');
  });

  it('rejects agent_model_settings — it is now a per-user setting, not a global key', async () => {
    const res = await request(app)
      .put('/api/app-settings')
      .send({ agent_model_settings: JSON.stringify({ planification: {} }) });

    expect(res.status).toBe(400);
    const body = res.body as ValidationErrorBody;
    expect(body.error).toBe('Validation failed');
    expect(JSON.stringify(body.issues)).toContain('agent_model_settings');
    expect(appSettingsDb.setValue).not.toHaveBeenCalled();
  });

  it('accepts an absolute scripts_dir path', async () => {
    const res = await request(app)
      .put('/api/app-settings')
      .send({ scripts_dir: '/opt/ralphy/scripts' });

    expect(res.status).toBe(200);
    expect(appSettingsDb.setValue).toHaveBeenCalledWith('scripts_dir', '/opt/ralphy/scripts');
  });

  it('rejects a relative scripts_dir path', async () => {
    const res = await request(app)
      .put('/api/app-settings')
      .send({ scripts_dir: 'scripts' });

    expect(res.status).toBe(400);
    const body = res.body as ValidationErrorBody;
    expect(body.error).toBe('Validation failed');
    expect(JSON.stringify(body.issues)).toContain('absolute');
    expect(appSettingsDb.setValue).not.toHaveBeenCalled();
  });

  it('rejects an empty scripts_dir', async () => {
    const res = await request(app)
      .put('/api/app-settings')
      .send({ scripts_dir: '   ' });

    expect(res.status).toBe(400);
    expect(appSettingsDb.setValue).not.toHaveBeenCalled();
  });

  it('allows long scripts_dir paths (beyond the 100-char limit used for the other keys)', async () => {
    const longPath = '/' + 'a'.repeat(300) + '/scripts';
    const res = await request(app)
      .put('/api/app-settings')
      .send({ scripts_dir: longPath });

    expect(res.status).toBe(200);
    expect(appSettingsDb.setValue).toHaveBeenCalledWith('scripts_dir', longPath);
  });
});
