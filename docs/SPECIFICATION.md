# Ralphy - Spécification Technique (MVP)

> Outil personnel d'aide au développement de code par IA basé sur Claude Code

**Version**: 2.1.0
**Date**: 2026-01-19
**Statut**: Draft

---

## 1. Vision

Ralphy transforme un PRD en Pull Request mergeable via une boucle autonome avec **validation humaine aux étapes clés**.

---

## 2. Architecture simplifiée

```
┌─────────────────────────────────────────────────────────────┐
│                      TERMINAL (CLI)                          │
│         Logs en temps réel + prompts de validation           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    SCRIPT PYTHON                             │
│                                                              │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │ Orch. SPEC  │─▶│ Orch. DEV   │─▶│ Orch. QA/PR │        │
│   │  (Phase 1)  │  │  (Phase 2)  │  │ (Phase 3-4) │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │              CIRCUIT BREAKER                         │   │
│   │  Surveille: inactivité, erreurs répétées, stagnation │   │
│   │  Actions: warning → kill process → FAILED            │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                              │
│   Timeout par phase + gestion état via fichiers              │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ subprocess
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              CLAUDE CODE CLI (subscription)                  │
│  claude --print --dangerously-skip-permissions -p "..."     │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Agents (4 au total)

| Agent | Phase | Entrée | Sortie |
|-------|-------|--------|--------|
| `spec-agent` | 1 | PRD.md | SPEC.md + TASKS.md |
| `dev-agent` | 2 | TASKS.md | Code + Tests |
| `qa-agent` | 3 | Code | QA_REPORT.md |
| `pr-agent` | 4 | Code + QA_REPORT.md | Pull Request |

### 3.1 spec-agent

Génère en une passe :
- Principes et conventions du projet
- User stories et règles métier
- Architecture technique
- Liste de tâches ordonnées

### 3.2 dev-agent

**Une seule invocation** qui traite toutes les tâches :
- Lit TASKS.md
- Pour chaque tâche `pending` : implémente, teste, met à jour le statut
- Émet `EXIT_SIGNAL: true` quand toutes les tâches sont `completed`

> Note : Claude gère lui-même la séquence des tâches. L'orchestrateur ne fait qu'une seule invocation.

### 3.3 qa-agent

Analyse en une passe :
- Qualité du code
- Vulnérabilités de sécurité (OWASP Top 10)
- Rapport dans QA_REPORT.md

### 3.4 pr-agent

Crée la PR :
- Branche feature
- Commit + push
- PR via `gh pr create`

---

## 4. Workflow

```
PRD.md
   │
   ▼
┌──────────────────────────────────────┐
│  PHASE 1: SPECIFICATION              │
│  spec-agent génère SPEC.md + TASKS.md│
└──────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────┐
│  VALIDATION HUMAINE #1               │
│  [Approuver] ou [Rejeter]            │
│  (attente infinie)                   │
└──────────────────────────────────────┘
   │ [Approuver]
   ▼
┌──────────────────────────────────────┐
│  PHASE 2: IMPLEMENTATION             │
│  dev-agent traite toutes les tâches  │
│  (une seule invocation)              │
│                                      │
│  Contrôle: [Abort] disponible        │
└──────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────┐
│  PHASE 3: QA                         │
│  qa-agent génère QA_REPORT.md        │
└──────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────┐
│  VALIDATION HUMAINE #2               │
│  [Approuver] ou [Rejeter]            │
│  (attente infinie)                   │
└──────────────────────────────────────┘
   │ [Approuver]
   ▼
┌──────────────────────────────────────┐
│  PHASE 4: PR                         │
│  pr-agent crée la Pull Request       │
└──────────────────────────────────────┘
   │
   ▼
 COMPLETED
```

---

## 5. Condition de sortie

**Signal unique** : L'agent émet `EXIT_SIGNAL: true` quand sa tâche est terminée.

Chaque prompt d'agent contient :
```
Quand tu as terminé ta tâche, émets "EXIT_SIGNAL: true" à la fin de ta réponse.
```

---

## 6. Timeouts (MVP)

| Phase | Timeout |
|-------|---------|
| Specification | 30 min |
| Implementation | 4 heures |
| QA | 30 min |
| PR | 10 min |
| Agent (par exécution) | 5 min |

Dépassement = état `FAILED`.

---

## 6.1 Circuit Breaker

Le circuit breaker protège contre les boucles infinies et les agents bloqués. Il complète les timeouts avec une détection d'anomalies plus fine.

### Déclencheurs

| Trigger | Seuil | Description |
|---------|-------|-------------|
| **Inactivité output** | 60s | Aucune sortie stdout pendant 60 secondes |
| **Répétition erreur** | 3x | Même erreur/pattern répété 3 fois consécutives |
| **Stagnation tâches** | 10 min | Aucune tâche passée à `completed` pendant 10 min (dev-agent uniquement) |
| **Taille output** | 500 KB | Output cumulé dépasse 500 KB (protection mémoire) |

### Comportement

```
[Trigger détecté]
       │
       ▼
┌──────────────────────────────┐
│  WARNING affiché             │
│  Compteur: attempt += 1      │
└──────────────────────────────┘
       │
       ▼
   attempt < 3 ?
    │         │
   Oui       Non
    │         │
    ▼         ▼
 Continue   CIRCUIT_OPEN
            (kill process)
            État → FAILED
```

### États du circuit

| État | Description |
|------|-------------|
| `CLOSED` | Fonctionnement normal |
| `HALF_OPEN` | Warning émis, surveillance renforcée |
| `OPEN` | Agent terminé, workflow en échec |

### Logs circuit breaker

```
[14:35:22] ⚠ Circuit breaker: inactivité détectée (60s sans output)
[14:35:22] ⚠ Circuit breaker: attempt 1/3, surveillance renforcée
[14:36:25] ⚠ Circuit breaker: inactivité détectée (60s sans output)
[14:36:25] ⚠ Circuit breaker: attempt 2/3
[14:37:30] ✗ Circuit breaker: OPEN - agent terminé après 3 tentatives
[14:37:30] État: FAILED (raison: circuit_breaker_triggered)
```

### Détection répétition d'erreur

Pattern matching sur les 10 dernières lignes d'output :
- Hash des lignes (ignorant timestamps/numéros de ligne)
- Si 3 hashes consécutifs identiques → trigger

Exemple de boucle détectée :
```
Error: Cannot find module 'foo'
Error: Cannot find module 'foo'
Error: Cannot find module 'foo'  ← Trigger
```

### Configuration

```yaml
# .ralphy/config.yaml
circuit_breaker:
  enabled: true
  inactivity_timeout: 60      # secondes
  max_repeated_errors: 3
  task_stagnation_timeout: 600  # 10 min, dev-agent uniquement
  max_output_size: 524288     # 500 KB
  max_attempts: 3             # warnings avant OPEN
```

### Interaction avec retry

Le circuit breaker est **indépendant** du retry d'agent :
- Retry : relance l'agent après timeout/erreur Claude
- Circuit breaker : tue l'agent pendant son exécution si anomalie

```
┌─────────────────────────────────────────────────────┐
│                    Agent Run                         │
│  ┌───────────────────────────────────────────────┐  │
│  │  Claude Process                               │  │
│  │                                               │  │
│  │   ←── Circuit Breaker surveille en continu   │  │
│  │                                               │  │
│  └───────────────────────────────────────────────┘  │
│                       │                              │
│            [Timeout/Erreur/CB]                       │
│                       │                              │
│                       ▼                              │
│              Retry si applicable                     │
└─────────────────────────────────────────────────────┘
```

### Cas particuliers

1. **Validation humaine** : Circuit breaker désactivé pendant l'attente de validation
2. **Phase PR** : Seuil inactivité augmenté à 120s (opérations git lentes)
3. **Tests longs** : Si `test_command` détecté dans output, seuil inactivité = 300s

---

## 7. Fichiers générés

### Structure projet cible

```
my-project/
├── .ralphy/
│   └── state.json          # État du workflow
├── specs/
│   ├── SPEC.md             # Spécifications + architecture
│   ├── TASKS.md            # Tâches ordonnées
│   └── QA_REPORT.md        # Rapport qualité/sécurité
├── PRD.md                  # Input utilisateur
├── src/                    # Code généré
└── tests/                  # Tests générés
```

### Format PRD.md (minimum requis)

```markdown
# [Titre du projet]

## Objectif
[Description de l'objectif principal]
```

### Format TASKS.md

```markdown
## Tâche 1: [Titre]
- **Statut**: pending | in_progress | completed
- **Description**: [description]
- **Fichiers**: [liste des fichiers]
```

### Format state.json

```json
{
  "phase": "implementation",
  "status": "running",
  "started_at": "2026-01-19T14:30:00Z",
  "tasks_completed": 3,
  "tasks_total": 8,
  "circuit_breaker": {
    "state": "closed",
    "attempts": 0,
    "last_trigger": null
  }
}
```

---

## 8. États du workflow

```
IDLE ──▶ SPECIFICATION ──▶ AWAITING_SPEC_VALIDATION
              │                     │
         [CB/Timeout]      [Rejeter]◀──┴──▶[Approuver]
              │                │                 │
              ▼                ▼                 ▼
           FAILED          REJECTED       IMPLEMENTATION
                                               │
                                    ┌──────────┼──────────┐
                                    │          │          │
                              [Abort]    [CB/Timeout]  [EXIT_SIGNAL]
                                    │          │          │
                                    └────▶ FAILED ◀───────┤
                                                          │
                                                          ▼
                                                         QA
                                                          │
                                               ┌──────────┴──────────┐
                                               │                     │
                                          [CB/Timeout]         [EXIT_SIGNAL]
                                               │                     │
                                               ▼                     ▼
                                            FAILED      AWAITING_QA_VALIDATION
                                                                     │
                                                     [Rejeter]◀──────┴──────▶[Approuver]
                                                         │                        │
                                                         ▼                        ▼
                                                      FAILED                     PR
                                                                                  │
                                                                       ┌──────────┴──────────┐
                                                                       │                     │
                                                                  [CB/Timeout]         [EXIT_SIGNAL]
                                                                       │                     │
                                                                       ▼                     ▼
                                                                    FAILED              COMPLETED

Légende: CB = Circuit Breaker (section 6.1)
```

---

## 9. Interface CLI (MVP)

### Commandes

```bash
# Démarrer un workflow
ralphy start /path/to/project

# Voir le statut
ralphy status

# Abort pendant l'implémentation
ralphy abort
```

### Affichage terminal

```
[14:30:01] Phase: SPECIFICATION
[14:30:02] Agent: spec-agent started
[14:30:45] Agent: spec-agent completed
[14:30:45] === VALIDATION REQUISE ===
[14:30:45] Fichiers générés:
[14:30:45]   - specs/SPEC.md
[14:30:45]   - specs/TASKS.md (8 tâches)
[14:30:45]
[14:30:45] Approuver ? [y/n]: _
```

---

## 10. Configuration minimale

Fichier `.ralphy/config.yaml` :

```yaml
project:
  name: "my-project"

timeouts:
  specification: 1800    # 30 min
  implementation: 14400  # 4h
  qa: 1800               # 30 min
  pr: 600                # 10 min
  agent: 300             # 5 min

circuit_breaker:
  enabled: true
  inactivity_timeout: 60       # secondes sans output
  max_repeated_errors: 3       # erreurs identiques consécutives
  task_stagnation_timeout: 600 # 10 min sans progression tâche
  max_output_size: 524288      # 500 KB max
  max_attempts: 3              # warnings avant OPEN

stack:
  language: "rails"
  test_command: "bundle exec rspec"
```

---

## 11. Prérequis

- Claude Code installé et authentifié
- Git configuré
- Projet cible initialisé (git init)
- GitHub CLI (`gh`) pour créer les PR

---

## 12. Évolutions futures (hors MVP)

- Interface web de monitoring
- Heuristiques de complétion additionnelles
- Pause/Resume pendant l'implémentation
- Multi-projets
- Notifications (webhook)
