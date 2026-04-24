# Magnet Match Backend App

Vraie petite application locale en Flask + SQLite.

## Fonctions

- inscription
- connexion
- profil utilisateur simple
- manquants et doubles
- matching
- demandes d'echange
- validation par les deux personnes
- chat apres accord pour regler les details
- avis apres echange

## Lancer

```powershell
& "C:\Users\Kima\AppData\Local\Programs\Python\Python312\python.exe" app.py
```

Puis ouvrir:

`http://127.0.0.1:5000`

## Comptes

Tu peux maintenant creer uniquement tes propres comptes de test dans l'application.

## Deploiement

Les fichiers de preparation au deploiement sont presents:

- `requirements.txt`
- `Procfile`
- `render.yaml`
- `.env.example`
- `DEPLOY.md`

La prochaine vraie etape pour une mise en ligne solide est la migration de `SQLite` vers `PostgreSQL`.
