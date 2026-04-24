# Deploiement de Magnet Match

## Etat actuel

Cette application est maintenant preparee pour un deploiement Flask simple:

- configuration via variables d'environnement
- serveur de production avec Gunicorn
- fichier `Procfile`
- fichier `render.yaml`

## Base de donnees

L'application supporte maintenant:

- `SQLite` en local via `DATABASE_PATH`
- `PostgreSQL` en production via `DATABASE_URL`

## Mise en ligne simple sur Render

1. Mettre le dossier `backend_app` dans un depot GitHub.
2. Creer un nouveau service web sur Render.
3. Pointer vers le repo GitHub.
4. Verifier que Render utilise:

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn wsgi:app`

5. Configurer les variables d'environnement:

- `SECRET_KEY`
- `FLASK_ENV=production`
- `DATABASE_URL` fournie par Render PostgreSQL

## Lancer localement

```powershell
& "C:\Users\Kima\AppData\Local\Programs\Python\Python312\python.exe" app.py
```

## Etape suivante recommandee

Avant vraie ouverture au public:

- ajouter sauvegardes et logs
- gerer les erreurs 500 proprement
- ajouter moderation et signalement
- renforcer la gestion des sessions
