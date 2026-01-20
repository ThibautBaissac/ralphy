# Intégrer RalphWiggum dans un projet existant

## 1. Prérequis

Vérifiez que vous avez :

```bash
# Claude Code CLI installé et authentifié
claude --version

# Git configuré
git --version

# GitHub CLI authentifié (pour créer les PR)
gh auth status
```

## 2. Installation

```bash
# Option A: Installation globale depuis le repo RalphWiggum
pip install -e /Users/thibautbaissac/code/ThibautBaissac/RalphWiggum/

# Option B: Installation dans un virtualenv
cd /Users/thibautbaissac/code/ThibautBaissac/RalphWiggum/
pip install -e ".[dev]"
```

Vérifiez l'installation :

```bash
ralph --version
```

## 3. Préparer votre projet

### 3.1 Créer le PRD.md (obligatoire)

À la racine de votre projet existant :

```bash
cd /path/to/mon-projet-existant
```

Créez `PRD.md` :

```markdown
# Titre de la Feature

## Contexte
[Décrivez le contexte existant du projet et pourquoi cette feature est nécessaire]

## Objectif
[Ce que vous voulez accomplir]

## Fonctionnalités
- Feature 1 : description détaillée
- Feature 2 : description détaillée

## Contraintes
- Stack existante : Rails 8 / React / etc.
- Dépendances existantes à respecter
- Conventions de code du projet
- Tests requis (RSpec, Jest, etc.)

## Exemples d'usage
[Optionnel : exemples concrets d'utilisation]
```

### 3.2 Configuration optionnelle

Créez `.ralph/config.yaml` pour personnaliser :

```yaml
project:
  name: mon-projet

stack:
  language: ruby           # ou typescript, python, go...
  test_command: bundle exec rspec

timeouts:
  specification: 1800      # 30 min
  implementation: 14400    # 4h
  qa: 1800                 # 30 min
  pr: 600                  # 10 min

circuit_breaker:
  enabled: true
  inactivity_timeout: 60
  max_repeated_errors: 3
```

## 4. Lancer le workflow

```bash
# Depuis n'importe où
ralph start /path/to/mon-projet-existant

# Ou depuis le projet
cd /path/to/mon-projet-existant
ralph start .
```

## 5. Workflow interactif

```
[14:30:01] Phase: SPECIFICATION
[14:30:45] Agent: spec-agent completed
[14:30:45] === VALIDATION REQUISE ===
[14:30:45] Fichiers générés:
[14:30:45]   - specs/SPEC.md
[14:30:45]   - specs/TASKS.md (8 tâches)
[14:30:45]
[14:30:45] Approuver ? [y/n]: _     ← Vérifiez les specs avant de continuer
```

**Vous validez 2 fois** :

1. Après génération des specs (SPEC.md + TASKS.md)
2. Après le rapport QA (avant création de la PR)

## 6. Commandes utiles

```bash
# Voir le statut
ralph status /path/to/mon-projet

# Interrompre si nécessaire
ralph abort /path/to/mon-projet

# Réinitialiser l'état
ralph reset /path/to/mon-projet
```

## 7. Structure générée

Après exécution, votre projet aura :

```
mon-projet-existant/
├── .ralph/
│   ├── state.json          # État du workflow
│   └── config.yaml         # Config (si créée)
├── specs/
│   ├── SPEC.md             # Spécifications générées
│   ├── TASKS.md            # Liste des tâches
│   └── QA_REPORT.md        # Rapport qualité
├── PRD.md                  # Votre input
├── src/                    # Code généré/modifié
└── tests/                  # Tests générés
```

## 8. Bonnes pratiques

| Do | Don't |
|----|-------|
| PRD précis et détaillé | PRD vague ("améliorer le code") |
| Scope limité (1 feature = 1 PR) | Scope trop large |
| Spécifier la stack existante | Laisser deviner |
| Mentionner les conventions | Ignorer le style existant |
| Relire SPEC.md avant validation | Valider à l'aveugle |

## 9. Exemple concret

```markdown
# PRD.md - Ajout authentification OAuth

## Contexte
Application Rails 8 existante avec Devise pour l'auth classique.
Besoin d'ajouter l'authentification Google OAuth.

## Objectif
Permettre aux utilisateurs de se connecter via leur compte Google.

## Fonctionnalités
- Bouton "Se connecter avec Google" sur la page de login
- Création automatique de compte si premier login OAuth
- Liaison compte existant si email correspond

## Contraintes
- Utiliser la gem `omniauth-google-oauth2`
- Respecter le design existant (Tailwind CSS)
- Tests RSpec pour les nouveaux controllers
- Ne pas casser l'auth Devise existante

## Variables d'environnement
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
```

Puis :

```bash
ralph start .
```

## 10. Dépannage

### Le workflow est bloqué

```bash
# Vérifier le statut
ralph status .

# Forcer l'arrêt
ralph abort .

# Réinitialiser complètement
ralph reset .
```

### Erreur "PRD.md non trouvé"

Assurez-vous que le fichier `PRD.md` existe à la racine du projet cible.

### Erreur "Claude Code CLI non trouvé"

```bash
# Installer Claude Code
npm install -g @anthropic-ai/claude-code

# Vérifier l'authentification
claude --version
```

### Erreur "gh non trouvé"

```bash
# macOS
brew install gh

# Puis s'authentifier
gh auth login
```

## 11. Limitations

- **Windows** : Non supporté (limitation technique sur `select()`)
- **Un workflow à la fois** : Un seul workflow peut tourner par projet
- **Scope raisonnable** : Un PRD = une PR mergeable
