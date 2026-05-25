import { useEffect, useState, useCallback } from 'react';
import { api } from '../utils/api';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { useAppSettings } from '../contexts/AppSettingsContext';
import { RotateCcw, Save, AlertCircle, Loader2 } from 'lucide-react';
import type {
  PromptListItem,
  GetPromptResponse,
  UnknownVariablesError,
} from '../../shared/api/settings';
import type { ApiError } from '../../shared/api/_common';

// Prompt-template editor (global, admin-only). Per-agent provider/model/effort
// is no longer here — it moved to the per-user "Agent Models" tab.
function AgentPromptsTab() {
  const { scriptsDir, refresh: refreshAppSettings } = useAppSettings();
  const [scriptsDirDraft, setScriptsDirDraft] = useState(scriptsDir);
  const [isSavingScriptsDir, setSavingScriptsDir] = useState(false);
  const [scriptsDirError, setScriptsDirError] = useState<string | null>(null);
  const [scriptsDirStatus, setScriptsDirStatus] = useState<string | null>(null);

  // Keep the draft in sync when the context-level value changes (initial load
  // or another tab refresh).
  useEffect(() => {
    setScriptsDirDraft(scriptsDir);
  }, [scriptsDir]);

  const isScriptsDirDirty = scriptsDirDraft.trim() !== scriptsDir;

  const handleSaveScriptsDir = async () => {
    setScriptsDirError(null);
    setScriptsDirStatus(null);
    setSavingScriptsDir(true);
    try {
      const res = await api.appSettings.update({ scripts_dir: scriptsDirDraft.trim() });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as ApiError & {
          issues?: Array<{ path?: Array<string | number>; message?: string }>;
        };
        const scriptsDirIssue = body.issues?.find((issue) => issue.path?.includes('scripts_dir'));
        setScriptsDirError(scriptsDirIssue?.message || body.error || `Save failed: ${res.status}`);
        return;
      }
      await refreshAppSettings();
      setScriptsDirStatus('Saved');
    } catch (err) {
      setScriptsDirError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSavingScriptsDir(false);
    }
  };

  const [prompts, setPrompts] = useState<PromptListItem[]>([]);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [detail, setDetail] = useState<GetPromptResponse | null>(null);
  const [editContent, setEditContent] = useState('');
  const [isListLoading, setListLoading] = useState(true);
  const [isDetailLoading, setDetailLoading] = useState(false);
  const [isSaving, setSaving] = useState(false);
  const [isResetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const isDirty = !!detail && editContent !== detail.content;

  const loadList = useCallback(async () => {
    setListLoading(true);
    try {
      const res = await api.settings.listPrompts();
      const data = await res.json();
      setPrompts(data);
      if (!selectedName && data.length > 0) {
        setSelectedName(data[0]!.name);
      }
    } catch {
      setError('Failed to load prompts');
    } finally {
      setListLoading(false);
    }
  }, [selectedName]);

  const loadDetail = useCallback(async (name: string) => {
    setDetailLoading(true);
    setError(null);
    setStatusMsg(null);
    try {
      const res = await api.settings.getPrompt(name);
      if (!res.ok) {
        setError('Failed to load prompt');
        return;
      }
      const data = await res.json();
      setDetail(data);
      setEditContent(data.content);
    } catch {
      setError('Failed to load prompt');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedName) void loadDetail(selectedName);
  }, [selectedName, loadDetail]);

  const selectPrompt = (name: string) => {
    if (name === selectedName) return;
    if (isDirty && !window.confirm('You have unsaved changes. Discard them?')) {
      return;
    }
    setSelectedName(name);
  };

  const handleSave = async () => {
    if (!detail) return;
    setSaving(true);
    setError(null);
    setStatusMsg(null);
    try {
      // detail.mtime is `number | null`; the api signature accepts `number | undefined`,
      // but we deliberately pass through `null` so the server treats "no mtime" as
      // "skip optimistic-concurrency" (the original JS behavior the tests assert).
      const res = await api.settings.savePrompt(
        detail.name,
        editContent,
        detail.mtime as number | undefined
      );
      if (res.status === 409) {
        await res.json().catch(() => ({}));
        setError('This prompt was edited in another tab. Reload to see the latest version.');
        setStatusMsg(null);
        return;
      }
      if (res.status === 400) {
        const body = (await res.json()) as unknown as Partial<UnknownVariablesError> & ApiError;
        if (body.unknownVariables?.length) {
          const allowed = body.allowedVariables ?? [];
          setError(
            `Unknown template variables: ${body.unknownVariables.map((v) => `{{${v}}}`).join(', ')}. Allowed: ${allowed.map((v) => `{{${v}}}`).join(', ')}`
          );
        } else {
          setError(body.error || 'Invalid content');
        }
        return;
      }
      if (!res.ok) {
        setError('Failed to save');
        return;
      }
      const body = await res.json();
      setDetail({ ...detail, content: editContent, mtime: body.mtime, isCustomized: true });
      setStatusMsg('Saved');
      setPrompts((prev) => prev.map((p) => (p.name === detail.name ? { ...p, isCustomized: true } : p)));
    } catch {
      setError('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!detail) return;
    if (!window.confirm(`Reset "${detail.label}" to its default content? Your customizations will be lost.`)) {
      return;
    }
    setResetting(true);
    setError(null);
    setStatusMsg(null);
    try {
      const res = await api.settings.resetPrompt(detail.name);
      if (!res.ok && res.status !== 204) {
        setError('Failed to reset');
        return;
      }
      await loadDetail(detail.name);
      setPrompts((prev) => prev.map((p) => (p.name === detail.name ? { ...p, isCustomized: false } : p)));
      setStatusMsg('Reset to default');
    } catch {
      setError('Failed to reset');
    } finally {
      setResetting(false);
    }
  };

  if (isListLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading prompts...
      </div>
    );
  }

  const promptItems = prompts.filter((p) => (p.kind || 'prompt') === 'prompt');
  const templateItems = prompts.filter((p) => p.kind === 'template');

  const renderItem = (p: PromptListItem) => (
    <li key={p.name}>
      <button
        onClick={() => selectPrompt(p.name)}
        className={`w-full text-left px-3 py-2 rounded-md text-sm flex items-center justify-between transition-colors ${
          selectedName === p.name
            ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 font-medium'
            : 'hover:bg-gray-50 dark:hover:bg-gray-800/50 text-foreground'
        }`}
        data-testid={`prompt-list-${p.name}`}
      >
        <span className="truncate">{p.label}</span>
        {p.isCustomized && (
          <span
            className="w-2 h-2 rounded-full bg-blue-500 dark:bg-blue-400 flex-shrink-0 ml-2"
            title="Customized"
          />
        )}
      </button>
    </li>
  );

  return (
    <div className="flex flex-col gap-4 md:gap-6 h-full min-h-[500px]">
      {/* Scripts directory: an absolute path injected into agent prompts as
          {{scriptsDir}}. Agents run inside per-task git worktrees where a
          relative `scripts/foo.ts` doesn't resolve, so completion scripts
          must be invoked via this absolute path. */}
      <div className="border border-border rounded-md p-3 md:p-4 bg-muted/30">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[240px]">
            <label
              htmlFor="scripts-dir-input"
              className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1"
            >
              Scripts Directory
            </label>
            <Input
              id="scripts-dir-input"
              value={scriptsDirDraft}
              onChange={(e) => setScriptsDirDraft(e.target.value)}
              placeholder="/absolute/path/to/ralphy/scripts"
              spellCheck={false}
              data-testid="scripts-dir-input"
              className="font-mono text-xs"
            />
          </div>
          <Button
            variant="default"
            size="sm"
            onClick={handleSaveScriptsDir}
            disabled={!isScriptsDirDirty || isSavingScriptsDir}
            data-testid="scripts-dir-save-button"
          >
            <Save className="w-4 h-4 mr-1" />
            {isSavingScriptsDir ? 'Saving...' : 'Save'}
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Absolute path to Ralphy&apos;s <code className="px-1 py-0.5 bg-muted rounded">scripts/</code> directory.
          Agents run inside per-task git worktrees and invoke completion scripts via this path
          (interpolated into prompts as <code className="px-1 py-0.5 bg-muted rounded">{'{{scriptsDir}}'}</code>).
          Defaults to the running server&apos;s install location.
        </p>
        {scriptsDirError && (
          <div className="mt-2 p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-700 dark:text-red-300 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{scriptsDirError}</span>
          </div>
        )}
        {scriptsDirStatus && !scriptsDirError && (
          <div className="mt-2 p-2 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded text-sm text-emerald-700 dark:text-emerald-300">
            {scriptsDirStatus}
          </div>
        )}
      </div>

      <div className="flex flex-col md:flex-row gap-4 md:gap-6 flex-1 min-h-0">
      {/* Left rail: grouped prompt + template list */}
      <div className="md:w-56 flex-shrink-0 border-b md:border-b-0 md:border-r border-border md:pr-4 pb-4 md:pb-0">
        {promptItems.length > 0 && (
          <>
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Agent Prompts
            </h3>
            <ul className="space-y-1">
              {promptItems.map(renderItem)}
            </ul>
          </>
        )}
        {templateItems.length > 0 && (
          <>
            <h3 className={`text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 ${promptItems.length > 0 ? 'mt-5' : ''}`}>
              Templates
            </h3>
            <ul className="space-y-1">
              {templateItems.map(renderItem)}
            </ul>
          </>
        )}
      </div>

      {/* Right pane: editor */}
      <div className="flex-1 flex flex-col min-w-0">
        {isDetailLoading || !detail ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading...
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3 pb-3 border-b border-border">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-foreground">{detail.label}</h3>
                <div className="mt-1 text-xs text-muted-foreground">
                  {detail.kind === 'template' ? (
                    <span>Free-form markdown template — read as-is by the agent, no variable substitution.</span>
                  ) : (
                    <>
                      Available variables:{' '}
                      {detail.variables.map((v) => (
                        <code
                          key={v}
                          className="inline-block px-1.5 py-0.5 mx-0.5 bg-gray-100 dark:bg-gray-800 rounded text-[11px]"
                        >{`{{${v}}}`}</code>
                      ))}
                    </>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleReset}
                  disabled={!detail.isCustomized || isResetting || isSaving}
                  data-testid="prompt-reset-button"
                >
                  <RotateCcw className="w-4 h-4 mr-1" />
                  {isResetting ? 'Resetting...' : 'Reset to default'}
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleSave}
                  disabled={!isDirty || isSaving || isResetting}
                  data-testid="prompt-save-button"
                >
                  <Save className="w-4 h-4 mr-1" />
                  {isSaving ? 'Saving...' : 'Save'}
                </Button>
              </div>
            </div>

            {error && (
              <div className="mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-700 dark:text-red-300 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {statusMsg && !error && (
              <div className="mt-3 p-2 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded text-sm text-emerald-700 dark:text-emerald-300">
                {statusMsg}
              </div>
            )}

            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              spellCheck={false}
              data-testid="prompt-editor"
              className="mt-3 flex-1 min-h-[400px] p-3 bg-background border border-border rounded-md font-mono text-xs leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </>
        )}
      </div>
      </div>
    </div>
  );
}

export default AgentPromptsTab;
