# Ralphy Web UI Dashboard

## Overview

A centralized web interface to manage Ralphy workflows across multiple local codebases. Users can start workflows, monitor progress in real-time, approve/reject at validation gates, and abort or reset workflows—all from a single dashboard.

## Problem Statement

Currently, Ralphy operates purely through CLI commands. When managing multiple codebases or features simultaneously, users must:
- Open multiple terminal windows or tabs
- Remember which terminal corresponds to which codebase
- Manually switch between terminals to check status or respond to validation prompts
- Risk missing validation gates that block workflow progress

A web UI provides a unified view of all active workflows with real-time status updates and centralized control.

## Goals

1. **Unified Dashboard**: Single view showing all registered codebases and their current workflow status
2. **Real-time Monitoring**: WebSocket-based streaming of workflow progress and output
3. **Validation Handling**: Review SPEC.md and QA_REPORT.md artifacts directly in the UI with approve/reject actions
4. **Workflow Control**: Start new workflows, abort running ones, and reset workflow state
5. **Persistence**: Workflows continue running independently even if the browser is closed

## Non-Goals (v1)

- Remote/SSH access to codebases on other machines
- User authentication or multi-user access
- Auto-discovery of codebases (manual registration only)
- Persistent log history beyond current state.json
- Mobile-optimized responsive design

## Technical Approach

### Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Backend | FastAPI | Async Python, native WebSocket support, fits Ralphy's Python stack |
| Frontend | htmx + Jinja2 | Minimal JS, server-driven reactivity, fast development |
| Styling | Pico CSS or similar | Classless CSS framework for clean defaults |
| Real-time | WebSocket | Native FastAPI support, enables live output streaming |

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser (localhost)                     │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                    htmx Frontend                        ││
│  │  - Dashboard list view                                  ││
│  │  - Status badges (idle, running, awaiting approval)     ││
│  │  - WebSocket connection for live updates                ││
│  │  - Modal for approval workflows                         ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ REST API     │  │ WebSocket    │  │ Process Manager   │  │
│  │ - /codebases │  │ /ws/stream   │  │ - Start workflows │  │
│  │ - /status    │  │              │  │ - Abort/Reset     │  │
│  │ - /start     │  │              │  │ - Read state.json │  │
│  │ - /approve   │  │              │  │                   │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    File System                               │
│  ~/.ralphy/                                                  │
│    └── web_config.json    # Registered codebases            │
│                                                              │
│  /path/to/codebase/                                          │
│    └── docs/features/<feature>/.ralphy/                      │
│        ├── state.json     # Workflow state                   │
│        └── claude.pid     # Running process PID              │
└─────────────────────────────────────────────────────────────┘
```

### Packaging

- Optional dependency group: `pip install ralphy[web]`
- New CLI command: `ralphy web [--port 8420] [--host localhost]`
- Default port: 8420 (arbitrary, unlikely to conflict)

## Implementation Phases

### Phase 1: Backend API (PR 1)

**Scope**: Core FastAPI application with REST endpoints and WebSocket support.

**Deliverables**:

1. **FastAPI Application** (`ralphy/web/app.py`)
   - ASGI app factory
   - CORS configuration for localhost
   - Static file serving for future frontend

2. **Codebase Registry** (`ralphy/web/registry.py`)
   - Store registered codebases in `~/.ralphy/web_config.json`
   - CRUD operations: add, remove, list codebases
   - Validate paths exist and contain valid projects

3. **REST Endpoints** (`ralphy/web/routes.py`)
   ```
   GET  /api/codebases              # List registered codebases
   POST /api/codebases              # Register new codebase
   DELETE /api/codebases/{id}       # Remove codebase

   GET  /api/codebases/{id}/status  # Get workflow status for codebase
   GET  /api/codebases/{id}/features # List features in codebase
   GET  /api/codebases/{id}/features/{feature}/status # Feature status

   POST /api/codebases/{id}/features/{feature}/start   # Start workflow
   POST /api/codebases/{id}/features/{feature}/abort   # Abort workflow
   POST /api/codebases/{id}/features/{feature}/reset   # Reset state
   POST /api/codebases/{id}/features/{feature}/approve # Approve gate
   POST /api/codebases/{id}/features/{feature}/reject  # Reject gate

   GET  /api/codebases/{id}/features/{feature}/artifacts/{name} # Read SPEC.md, etc.
   ```

4. **WebSocket Endpoint** (`ralphy/web/websocket.py`)
   ```
   WS /ws/stream/{codebase_id}/{feature}  # Stream workflow output
   ```
   - Tail claude output in real-time
   - Send state change notifications
   - Handle client reconnection gracefully

5. **Process Manager** (`ralphy/web/process.py`)
   - Start `ralphy start` as subprocess
   - Track PIDs for abort capability
   - Non-blocking status checks

6. **CLI Command** (`ralphy/cli.py`)
   ```bash
   ralphy web                    # Start on localhost:8420
   ralphy web --port 9000        # Custom port
   ralphy web --host 0.0.0.0     # Bind to all interfaces (use with caution)
   ```

**Acceptance Criteria**:
- [ ] `ralphy web` starts FastAPI server
- [ ] Can register/unregister codebases via curl
- [ ] Can get status of registered codebases via curl
- [ ] Can start a workflow via API and see it running
- [ ] WebSocket streams workflow output in real-time

### Phase 2: Read-Only UI (PR 2)

**Scope**: htmx-based frontend for viewing status across codebases.

**Deliverables**:

1. **Base Templates** (`ralphy/web/templates/`)
   - `base.html`: Layout with htmx, CSS framework
   - `dashboard.html`: Main codebase list view
   - `feature.html`: Single feature detail view

2. **Dashboard View**
   - List of registered codebases with:
     - Codebase name/path
     - Number of features
     - Active workflow indicator
   - Click to expand/view features
   - Status badges: `idle`, `running`, `awaiting-approval`, `completed`, `failed`

3. **Feature Detail View**
   - Current phase and progress bar
   - Task completion count (e.g., "3/7 tasks completed")
   - Live output stream (WebSocket-powered)
   - Phase history

4. **Real-time Updates**
   - htmx WebSocket extension for live status updates
   - Auto-refresh dashboard every 5s as fallback
   - Visual indicators for state changes

5. **Codebase Management**
   - Form to add new codebase (path input)
   - Remove codebase button with confirmation

**Acceptance Criteria**:
- [ ] Dashboard shows all registered codebases
- [ ] Clicking a codebase shows its features
- [ ] Status badges update in real-time
- [ ] Live output streaming works
- [ ] Can add/remove codebases from UI

### Phase 3: Workflow Actions (PR 3)

**Scope**: Add interactive controls for workflow management.

**Deliverables**:

1. **Start Workflow**
   - Form with text input for feature name or description
   - Dropdown to select existing feature (if PRD exists) or create new
   - Start button with loading state
   - Redirect to feature detail view on start

2. **Approval Modal**
   - Trigger: Status badge shows "awaiting-approval"
   - Modal contents:
     - Phase indicator (Specification or QA)
     - Artifact content (SPEC.md or QA_REPORT.md) with syntax highlighting
     - Approve / Reject buttons
   - Close modal and refresh status on action

3. **Abort/Reset Controls**
   - Abort button (visible when workflow running)
     - Confirmation dialog
     - Sends SIGTERM to workflow process
   - Reset button (visible when workflow in error/rejected state)
     - Confirmation dialog
     - Clears state.json

4. **Error Handling**
   - Toast notifications for action results
   - Error states displayed clearly
   - Retry suggestions for common failures

**Acceptance Criteria**:
- [ ] Can start a workflow from the UI
- [ ] Approval modal shows correct artifact content
- [ ] Approve/Reject actions update workflow state
- [ ] Abort successfully stops running workflow
- [ ] Reset clears workflow state

## User Experience

### Dashboard Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Ralphy Dashboard                              [Add Codebase]│
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  📁 my-project                                               │
│     /Users/me/code/my-project                                │
│     ├── auth-feature        ● Running (Implementation 4/7)  │
│     ├── api-refactor        ◐ Awaiting Approval (QA)        │
│     └── dark-mode           ○ Idle                          │
│                                                    [Remove]  │
│  ─────────────────────────────────────────────────────────  │
│  📁 another-project                                          │
│     /Users/me/code/another-project                           │
│     └── user-dashboard      ✓ Completed                      │
│                                                    [Remove]  │
└─────────────────────────────────────────────────────────────┘
```

### Feature Detail View

```
┌─────────────────────────────────────────────────────────────┐
│  ← Back to Dashboard                                         │
│                                                              │
│  my-project / auth-feature                                   │
│  ══════════════════════════════════════════════════════════ │
│                                                              │
│  Phase: Implementation                                       │
│  ████████████░░░░░░░░  4/7 tasks (57%)                      │
│                                                              │
│  [Abort Workflow]                                            │
│                                                              │
│  ─────────────────────────────────────────────────────────  │
│  Live Output                                                 │
│  ─────────────────────────────────────────────────────────  │
│  │ Implementing login form validation...                    │
│  │ ✓ Created src/components/LoginForm.tsx                   │
│  │ Running tests...                                         │
│  │ $ npm test                                               │
│  │ PASS src/components/LoginForm.test.tsx                   │
│  │ ▌                                                        │
│  └──────────────────────────────────────────────────────────│
└─────────────────────────────────────────────────────────────┘
```

### Approval Modal

```
┌─────────────────────────────────────────────────────────────┐
│  Review Specification                                    [X] │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ # Specification: auth-feature                          │ │
│  │                                                        │ │
│  │ ## Overview                                            │ │
│  │ Implement user authentication with JWT tokens...       │ │
│  │                                                        │ │
│  │ ## Tasks                                               │ │
│  │ 1. Create login endpoint                               │ │
│  │ 2. Implement JWT token generation                      │ │
│  │ 3. Add protected route middleware                      │ │
│  │ ...                                                    │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  7 tasks identified                                          │
│                                                              │
│                              [Reject]  [Approve & Continue]  │
└─────────────────────────────────────────────────────────────┘
```

## Data Model

### Web Config (`~/.ralphy/web_config.json`)

```json
{
  "codebases": [
    {
      "id": "abc123",
      "name": "my-project",
      "path": "/Users/me/code/my-project",
      "added_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### API Response: Codebase Status

```json
{
  "id": "abc123",
  "name": "my-project",
  "path": "/Users/me/code/my-project",
  "features": [
    {
      "name": "auth-feature",
      "phase": "IMPLEMENTATION",
      "status": "running",
      "tasks_completed": 4,
      "tasks_total": 7,
      "last_updated": "2024-01-15T10:35:00Z"
    }
  ]
}
```

## Security Considerations

- **Localhost only**: Server binds to 127.0.0.1 by default
- **No authentication**: Relies on localhost trust model
- **Path validation**: Reject paths outside user's home directory or with suspicious characters
- **No remote execution**: All operations execute locally via subprocess

## Testing Strategy

### Unit Tests
- Registry CRUD operations
- State parsing and status derivation
- API endpoint responses

### Integration Tests
- Full workflow: register → start → approve → complete
- WebSocket connection and streaming
- Abort and reset operations

### Manual Testing
- Multi-browser behavior
- Browser close/reconnect
- Concurrent workflows across codebases

## Future Enhancements (Post-v1)

- **Remote access**: SSH-based codebase management
- **Authentication**: Token-based auth for non-localhost access
- **Notifications**: Desktop notifications for validation gates
- **History**: Workflow execution history and logs
- **Metrics**: Success rates, average durations, token usage
- **Keyboard shortcuts**: Quick actions without mouse
