import path from 'path';
import { z } from 'zod';

const trimmedString = (max: number) => z.string().trim().min(1).max(max);

export const UpdateAppSettingsBodySchema = z
  .object({
    internal_tool_name: trimmedString(100).optional(),
    github_pr_trigger: z
      .string()
      .trim()
      .transform((value) => value.replace(/^@+/, '').toLowerCase())
      .pipe(z.string().min(1).max(100).regex(/^[a-z0-9][a-z0-9_-]*$/, {
        message: 'must contain only letters, digits, hyphens, or underscores',
      }))
      .optional(),
    scripts_dir: trimmedString(1024)
      .refine((value) => path.isAbsolute(value), {
        message: 'must be an absolute filesystem path',
      })
      .optional(),
  })
  .strict();

export type UpdateAppSettingsBody = z.infer<typeof UpdateAppSettingsBodySchema>;
