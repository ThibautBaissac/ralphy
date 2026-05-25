// Global application settings (single-instance key/value).
//
// GET is public so the dashboard can render the configured tool name on the
// login screen, before the user is authenticated. PUT is admin-only.

import express, { type Request, type Response } from 'express';
import { appSettingsDb } from '../database/db.js';
import { authenticateToken, requireAdmin } from '../middleware/auth.js';
import { validateBody } from '../middleware/validate.js';
import {
  UpdateAppSettingsBodySchema,
  type UpdateAppSettingsBody,
} from '../../shared/schemas/appSettings.js';
import type { ApiError } from '../../shared/api/_common.js';
import type {
  GetAppSettingsResponse,
  UpdateAppSettingsResponse,
} from '../../shared/api/settings.js';

const router = express.Router();

router.get('/', (_req: Request, res: Response<GetAppSettingsResponse | ApiError>) => {
  try {
    const settings = appSettingsDb.getAll() as unknown as GetAppSettingsResponse;
    res.json(settings);
  } catch (error) {
    console.error('Error reading app_settings:', error);
    res.status(500).json({ error: 'Failed to read app settings' });
  }
});

router.put(
  '/',
  authenticateToken,
  requireAdmin,
  validateBody(UpdateAppSettingsBodySchema),
  (
    req: Request<unknown, UpdateAppSettingsResponse | ApiError>,
    res: Response<UpdateAppSettingsResponse | ApiError>,
  ) => {
    const updates = req.validated!.body as UpdateAppSettingsBody;

    try {
      for (const [key, value] of Object.entries(updates)) {
        if (value === undefined) continue;
        appSettingsDb.setValue(key, value);
      }
      res.json(appSettingsDb.getAll() as unknown as UpdateAppSettingsResponse);
    } catch (error) {
      console.error('Error writing app_settings:', error);
      res.status(500).json({ error: 'Failed to save app settings' });
    }
  },
);

export default router;
