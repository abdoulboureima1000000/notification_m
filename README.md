# 🚀 MovieAll - GitHub Actions Push Notification System

Système automatisé de notifications Push pour **MovieAll** orchestré par **GitHub Actions**, piloté en temps réel depuis le panneau d'administration **MovieAll Admin Suite**, et connecté à **Cloud Firestore** & **Firebase Cloud Messaging (FCM)**.

---

## 🎯 Fonctionnalités Principales

- 🔄 **Contrôle Total depuis `movieall_admin`** :
  - **Activation / Désactivation globale** du service de notifications.
  - **Quota journalier configurable** (nombre de notifications max par jour : 1, 2, 3, etc.).
  - **Heures de diffusion ciblées** (sélection précise des heures autorisées : ex. 12h, 18h, 21h).
  - **Types de contenus filtrables** : `Films`, `Séries`, `Animes`, `Animations`.
  - **Sources sélectionnables** : `French-Stream`, `French-Manga`, `Anime-Sama`.
  - **Bouton de test immédiat** direct depuis le panneau Admin.

- 🕷️ **Scraping Automatique des Nouveautés** :
  - **French Stream** : Nouveaux films (`/films/`), séries TV (`/s-tv/`), animations (`/films/animations/`).
  - **French Manga** : Nouveaux animes et mangas en VF / VOSTFR (`/manga-streaming-1/`).
  - **Anime-Sama** : Nouvelles sorties du catalogue Anime-Sama (`/catalogue/fragment.php`).
  - Extraction automatique : Titre, Affiche HD (TMDB / CDN), Synopsis concis (150 caractères), Catégorie et source.

- 🛡️ **Anti-Doublons & Suivi** :
  - Historique stocké dans la collection Firestore `notifications_history`.
  - Chaque média envoyé n'est jamais re-notifié une deuxième fois.
  - Suivi des succès et échecs d'envoi FCM.

- 📱 **Envoi Multicast FCM Optimisé** :
  - Lecture directe des tokens FCM enregistrés dans la collection Firestore `users` (`fcmToken`).
  - Découpage par lots (batches de 500 tokens).
  - Notification enrichie avec image d'affiche et action de clic.

---

## ⚙️ Configuration du Secret GitHub Actions

Pour permettre à GitHub Actions d'envoyer les notifications et de communiquer avec Firestore :

1. Rendez-vous sur votre dépôt GitHub : `Settings` > `Secrets and variables` > `Actions`.
2. Cliquez sur **New repository secret**.
3. Nom du secret : `FIREBASE_SERVICE_ACCOUNT`.
4. Valeur : Collez l'intégralité du contenu du fichier JSON de votre clé de compte de service Firebase (situé par exemple dans `movieall/movieall-8e5c1-firebase-adminsdk-*.json`).
5. Cliquez sur **Add secret**.

---

## ⏰ Fonctionnement du Déclenchement Automatique

Le workflow GitHub Actions (`.github/workflows/notify.yml`) est configuré pour s'exécuter **toutes les heures** (`cron: '0 * * * *'`).

À chaque heure :
1. Le script Python démarre et charge la configuration depuis `app_config/notifications` dans Firestore.
2. Il convertit l'heure actuelle selon le fuseau horaire (`Europe/Paris`).
3. Il vérifie si l'heure actuelle fait partie des `allowed_hours` configurées dans MovieAll Admin.
4. Il vérifie si le quota `today_sent_count` < `max_per_day`.
5. Si les conditions sont réunies :
   - Il scrape les nouveautés selon les types choisis.
   - Il sélectionne la meilleure nouveauté non encore envoyée.
   - Il envoie la notification push à tous les utilisateurs enregistrés.
   - Il incrémente le compteur journalier et enregistre l'historique.

---

## 🧪 Test Manuel & Déclenchement Forcé

### Via GitHub Actions :
Dans l'onglet **Actions** sur GitHub > `MovieAll Push Notifications` > **Run workflow** :
- `force_send` : Cocher pour forcer l'envoi immédiat sans tenir compte de l'heure ni du quota.
- `type_override` : Sélectionner un type précis (`film`, `serie`, `anime`, etc.).
- `dry_run` : Cocher pour tester sans envoyer de message réel aux téléphones.

### En local (sur votre machine) :
```bash
cd notification_github_action
pip install -r requirements.txt

# Simulation (Dry Run)
python notify.py --dry-run --force

# Envoi réel immédiat
python notify.py --force
```
