# Intégrer Ralphy dans un projet existant

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

### Option A: Installation avec pipx (recommandé pour CLI)

`pipx` installe les outils CLI Python dans des environnements isolés :

```bash
# Installer pipx si nécessaire
brew install pipx
pipx ensurepath

# Installer Ralphy depuis le repo local
cd /Users/thibautbaissac/code/ThibautBaissac/Ralphy/
pipx install -e .

# Ou depuis un chemin absolu
pipx install -e /Users/thibautbaissac/code/ThibautBaissac/Ralphy/
```

### Option B: Installation avec uv (le plus rapide)

`uv` est un gestionnaire de paquets Python ultra-rapide :

```bash
# Installer uv si nécessaire
curl -LsSf https://astral.sh/uv/install.sh | sh

# Installer Ralphy
uv tool install -e /Users/thibautbaissac/code/ThibautBaissac/Ralphy/
```

### Option C: Installation en développement (pour contribuer)

Créez un virtualenv pour développer sur Ralphy :

```bash
cd /Users/thibautbaissac/code/ThibautBaissac/Ralphy/

# Créer et activer le virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Installer en mode éditable avec dépendances de dev
pip install -e ".[dev]"
```

### Vérification de l'installation

```bash
ralphy --version
```

### Désinstallation

```bash
# Si installé avec pipx
pipx uninstall ralphwiggum

# Si installé avec uv
uv tool uninstall ralphwiggum
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

Créez `.ralphy/config.yaml` pour personnaliser :

```yaml
project:
  name: mon-projet

models:
  specification: sonnet     # ou opus, haiku
  implementation: opus      # modèle le plus puissant pour l'implémentation
  qa: sonnet
  pr: haiku                 # modèle rapide pour la création de PR

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
ralphy start /path/to/mon-projet-existant

# Ou depuis le projet
cd /path/to/mon-projet-existant
ralphy start .
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
ralphy status /path/to/mon-projet

# Interrompre si nécessaire
ralphy abort /path/to/mon-projet

# Réinitialiser l'état
ralphy reset /path/to/mon-projet
```

## 7. Structure générée

Après exécution, votre projet aura :

```
mon-projet-existant/
├── .ralphy/
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
ralphy start .
```

## 10. Dépannage

### Erreur "externally-managed-environment"

Si vous voyez cette erreur avec `pip3 install`, c'est normal sur macOS avec Python Homebrew. **Utilisez pipx ou uv** (voir section Installation ci-dessus).

```bash
# ❌ Ne fonctionne pas (erreur externally-managed-environment)
pip3 install -e .

# ✅ Utilisez pipx
pipx install -e /chemin/vers/Ralphy/

# ✅ Ou uv
uv tool install -e /chemin/vers/Ralphy/
```

### Le workflow est bloqué

```bash
# Vérifier le statut
ralphy status .

# Forcer l'arrêt
ralphy abort .

# Réinitialiser complètement
ralphy reset .
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
