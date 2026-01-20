# Ralphy

Outil d'aide au développement de code par IA basé sur Claude Code.

Ralphy transforme un PRD (Product Requirements Document) en Pull Request mergeable via une boucle autonome avec validation humaine aux étapes clés.

## Installation

```bash
pip install -e ".[dev]"
```

## Prérequis

- Python 3.11+
- Claude Code CLI installé et authentifié (`claude --version`)
- Git configuré
- GitHub CLI (`gh`) authentifié pour créer les PR

## Limitations

- **Windows**: Non supporté (limitation technique sur `select()`)

## Utilisation

### 1. Préparer le projet

Créer un fichier `PRD.md` à la racine du projet :

```markdown
# Mon Projet

## Contexte
[Décrivez le contexte et le problème à résoudre]

## Objectif
[Ce que le projet doit accomplir]

## Fonctionnalités
- Feature 1 : description
- Feature 2 : description

## Contraintes
- Stack technique souhaitée
- Dépendances existantes
- Contraintes de temps/perf
```

### 2. Lancer le workflow

```bash
ralphy start /path/to/project
```

### 3. Suivre le statut

```bash
ralphy status
```

### 4. Interrompre si nécessaire

```bash
ralphy abort
```

## Workflow

```
PRD.md → [SPEC] → Validation → [DEV] → [QA] → Validation → [PR] → Done
```

| Phase | Agent | Produit | Durée max |
|-------|-------|---------|-----------|
| 1. SPECIFICATION | spec-agent | SPEC.md + TASKS.md | 30 min |
| 2. VALIDATION #1 | humain | Approuve les specs | - |
| 3. IMPLEMENTATION | dev-agent | Code + tests | 4h |
| 4. QA | qa-agent | QA_REPORT.md | 30 min |
| 5. VALIDATION #2 | humain | Approuve le rapport QA | - |
| 6. PR | pr-agent | Pull Request GitHub | 10 min |

### Validations humaines

**Validation #1 (specs)** : Vérifiez que SPEC.md et TASKS.md correspondent à vos attentes avant l'implémentation.

**Validation #2 (QA)** : Vérifiez le rapport QA avant la création de la PR. Le rapport liste les problèmes de qualité/sécurité détectés.

### En cas de rejet

Si vous rejetez à une validation, le workflow passe en état `REJECTED`. Pour relancer :

```bash
ralphy start /path/to/project
```

## Configuration

Créer `.ralphy/config.yaml` pour personnaliser (optionnel) :

```yaml
project:
  name: mon-projet

stack:
  language: python          # ou typescript, go, rust...
  test_command: pytest      # commande pour lancer les tests

timeouts:
  specification: 1800       # 30 min
  implementation: 14400     # 4h
  qa: 1800                  # 30 min
  pr: 600                   # 10 min

retry:
  max_attempts: 2           # 1 = pas de retry
  delay_seconds: 5

circuit_breaker:
  enabled: true
  inactivity_timeout: 60    # secondes sans output
  max_repeated_errors: 3    # même erreur répétée
  task_stagnation_timeout: 600  # 10 min sans tâche complétée
```

## Structure générée

```
my-project/
├── .ralphy/
│   ├── state.json          # État du workflow
│   └── config.yaml         # Configuration (optionnel)
├── specs/
│   ├── SPEC.md             # Spécifications + architecture
│   ├── TASKS.md            # Tâches ordonnées
│   └── QA_REPORT.md        # Rapport qualité/sécurité
├── PRD.md                  # Votre input
├── src/                    # Code généré
└── tests/                  # Tests générés
```

## Conseils pour un bon PRD

1. **Soyez précis** sur les fonctionnalités attendues
2. **Spécifiez la stack** si vous avez des préférences
3. **Listez les contraintes** (perf, sécurité, compatibilité)
4. **Donnez des exemples** d'usage si pertinent
5. **Gardez un scope raisonnable** - un PRD = une PR

## Licence

MIT
