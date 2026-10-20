#!/usr/bin/env python3
"""
MovieAll - GitHub Actions Automated Push Notification Dispatcher.
Controls:
 - Config stored in Firestore: 'app_config/notifications'
 - User FCM tokens stored in Firestore: 'users' collection
 - Hourly schedule & daily quotas
 - Scrapes novelties across French Stream, French Manga, and Anime-Sama
"""

import os
import sys
import json
import base64
import glob
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple, Set

# Ensure utf-8 encoding for console output on Windows and Linux runners
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Timezone support
try:
    import zoneinfo
    def get_tz(name: str):
        try:
            return zoneinfo.ZoneInfo(name)
        except Exception:
            return None
except ImportError:
    try:
        import pytz
        def get_tz(name: str):
            try:
                return pytz.timezone(name)
            except Exception:
                return None
    except ImportError:
        def get_tz(name: str):
            return None

import firebase_admin
from firebase_admin import credentials, firestore, messaging

from scrapers import fetch_latest_novelties

DEFAULT_TIMEZONE = "Europe/Paris"
DEFAULT_CONFIG = {
    'enabled': True,
    'max_per_day': 3,
    'allowed_hours': [9, 12, 15, 18, 21],
    'content_types': ['film', 'serie', 'anime', 'animation'],
    'source_providers': ['french-stream', 'french-manga', 'anime-sama'],
    'today_sent_count': 0,
    'last_sent_date': '',
    'last_sent_at': None,
    'last_sent_title': '',
    'last_sent_poster': '',
    'last_sent_type': '',
    'timezone': DEFAULT_TIMEZONE,
    'force_test_send': False,
}


def init_firebase(service_account_arg: Optional[str] = None):
    """
    Initializes Firebase Admin SDK using:
    1. CLI argument `--service-account`
    2. Environment variable `FIREBASE_SERVICE_ACCOUNT` (raw JSON, Base64, or file path)
    3. Auto-detected local `*firebase-adminsdk*.json` file
    """
    if firebase_admin._apps:
        return firestore.client()

    cred = None

    # 1. From CLI argument
    if service_account_arg and os.path.exists(service_account_arg):
        print(f"[Firebase] Using service account from argument: {service_account_arg}")
        cred = credentials.Certificate(service_account_arg)

    # 2. From environment variable
    if not cred and os.environ.get('FIREBASE_SERVICE_ACCOUNT'):
        raw = os.environ['FIREBASE_SERVICE_ACCOUNT'].strip()
        # Could be a file path
        if os.path.exists(raw):
            print(f"[Firebase] Using service account file from ENV: {raw}")
            cred = credentials.Certificate(raw)
        else:
            # Could be JSON string or base64 encoded JSON
            try:
                json_data = json.loads(raw)
                print("[Firebase] Using service account from raw JSON in ENV.")
                cred = credentials.Certificate(json_data)
            except Exception:
                try:
                    decoded = base64.b64decode(raw).decode('utf-8')
                    json_data = json.loads(decoded)
                    print("[Firebase] Using service account from Base64 decoded ENV.")
                    cred = credentials.Certificate(json_data)
                except Exception as b64_err:
                    print(f"[Firebase] Warning: Failed to parse FIREBASE_SERVICE_ACCOUNT: {b64_err}")

    # 3. Auto-detect local service account in workspace
    if not cred:
        search_paths = [
            ".",
            "..",
            os.path.join(os.path.dirname(__file__), ".."),
            os.path.join(os.path.dirname(__file__), "..", "movieall"),
        ]
        candidate_files = []
        for p in search_paths:
            candidate_files.extend(glob.glob(os.path.join(p, "*firebase-adminsdk*.json")))
            candidate_files.extend(glob.glob(os.path.join(p, "*.json")))

        for candidate in candidate_files:
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                    if content.get('type') == 'service_account' and 'project_id' in content:
                        print(f"[Firebase] Auto-detected service account: {candidate}")
                        cred = credentials.Certificate(candidate)
                        break
            except Exception:
                continue

    if not cred:
        raise RuntimeError(
            "No Firebase service account found. Set FIREBASE_SERVICE_ACCOUNT environment variable "
            "or place a service account JSON file in the project directory."
        )

    firebase_admin.initialize_app(cred)
    return firestore.client()


def get_current_time(tz_name: str) -> datetime:
    tz = get_tz(tz_name) or get_tz(DEFAULT_TIMEZONE)
    if tz:
        return datetime.now(tz)
    return datetime.now()


def load_config(db) -> Dict:
    doc_ref = db.collection('app_config').document('notifications')
    doc = doc_ref.get()
    if not doc.exists:
        print("[Config] 'app_config/notifications' does not exist. Initializing with defaults.")
        doc_ref.set(DEFAULT_CONFIG, merge=True)
        return DEFAULT_CONFIG.copy()

    data = doc.to_dict() or {}
    config = DEFAULT_CONFIG.copy()
    config.update(data)
    return config


def fetch_registered_fcm_tokens(db) -> Set[str]:
    """
    Retrieves all valid FCM tokens from 'users' collection in Firestore.
    """
    tokens = set()
    users_ref = db.collection('users')
    docs = users_ref.stream()

    for doc in docs:
        user_data = doc.to_dict() or {}
        # Verify user has notifications enabled if specified
        if user_data.get('notificationsEnabled') is False:
            continue
        token = user_data.get('fcmToken')
        if token and isinstance(token, str) and len(token.strip()) > 10:
            tokens.add(token.strip())

    return tokens


def fetch_recently_notified_ids(db, limit: int = 100) -> Set[str]:
    """
    Fetches IDs of items already notified from 'notifications_history'
    to avoid notifying the exact same item repeatedly.
    """
    history_ref = db.collection('notifications_history')
    recent_docs = history_ref.order_by('sent_at', direction=firestore.Query.DESCENDING).limit(limit).stream()
    return {doc.id for doc in recent_docs}


def format_notification(item: Dict) -> Tuple[str, str]:
    """
    Formats an engaging notification title and body.
    """
    ctype = item.get('type', 'film')
    raw_title = item.get('title', 'Nouveauté')
    desc = item.get('description', '')

    if ctype == 'film':
        title = f"🎬 Nouveau Film : {raw_title}"
    elif ctype == 'serie':
        title = f"📺 Nouvelle Série : {raw_title}"
    elif ctype == 'anime':
        title = f"⛩️ Nouvel Anime : {raw_title}"
    elif ctype == 'animation':
        title = f"🎨 Animation : {raw_title}"
    else:
        title = f"🔥 Nouveauté MovieAll : {raw_title}"

    body = desc if desc else f"Disponible dès maintenant en streaming haute qualité sur MovieAll !"
    return title, body


def send_multicast_notifications(tokens: List[str], item: Dict) -> Tuple[int, int, List[str]]:
    """
    Sends multicast push notification using Firebase Cloud Messaging.
    Batch size max 500 per request.
    Returns (success_count, failure_count, failed_tokens_to_clean).
    """
    if not tokens:
        return 0, 0, []

    notif_title, notif_body = format_notification(item)
    poster_url = item.get('poster') or ''

    notification = messaging.Notification(
        title=notif_title,
        body=notif_body,
        image=poster_url if poster_url.startswith('http') else None,
    )

    data_payload = {
        'id': str(item.get('id', '')),
        'title': str(item.get('title', '')),
        'type': str(item.get('type', '')),
        'poster': str(poster_url),
        'source': str(item.get('source', '')),
        'click_action': 'FLUTTER_NOTIFICATION_CLICK',
    }

    # Android specific styling
    android_config = messaging.AndroidConfig(
        priority='high',
        notification=messaging.AndroidNotification(
            icon='ic_notification',
            color='#6366F1',
            channel_id='movieall_novelties',
            sound='default',
            default_vibrate_timings=True,
            image=poster_url if poster_url.startswith('http') else None,
        ),
    )

    total_success = 0
    total_failure = 0
    dead_tokens = []

    # Batch in chunks of 500
    batch_size = 500
    for i in range(0, len(tokens), batch_size):
        chunk = tokens[i:i + batch_size]
        message = messaging.MulticastMessage(
            tokens=chunk,
            notification=notification,
            data=data_payload,
            android=android_config,
        )

        try:
            response = messaging.send_each_for_multicast(message)
            total_success += response.success_count
            total_failure += response.failure_count

            # Check for invalid / expired tokens
            for idx, resp in enumerate(response.responses):
                if not resp.success and resp.exception:
                    err_code = getattr(resp.exception, 'code', str(resp.exception))
                    if 'registration-token-not-registered' in str(err_code).lower() or 'unregistered' in str(err_code).lower():
                        dead_tokens.append(chunk[idx])
        except Exception as e:
            print(f"[FCM] Error sending chunk {i}-{i+len(chunk)}: {e}")
            total_failure += len(chunk)

    return total_success, total_failure, dead_tokens


def run_notification_cycle(
    force: bool = False,
    service_account: Optional[str] = None,
    type_override: Optional[str] = None,
    dry_run: bool = False,
):
    print("=" * 60)
    print("MovieAll Push Notification Dispatcher")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # 1. Initialize DB
    db = init_firebase(service_account)

    # 2. Load Firestore Config
    config = load_config(db)
    tz_name = config.get('timezone', DEFAULT_TIMEZONE)
    current_dt = get_current_time(tz_name)
    today_str = current_dt.strftime('%Y-%m-%d')
    current_hour = current_dt.hour

    print(f"[Schedule] Local time: {current_dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name})")
    print(f"[Schedule] Current hour: {current_hour}h | Allowed: {config.get('allowed_hours')}")
    print(f"[Quota] Max per day: {config.get('max_per_day')} | Sent today: {config.get('today_sent_count')}")

    # Reset quota if date changed
    last_sent_date = config.get('last_sent_date', '')
    today_sent_count = config.get('today_sent_count', 0)
    if last_sent_date != today_str:
        print(f"[Quota] Resetting daily counter (new day {today_str} vs {last_sent_date})")
        today_sent_count = 0
        db.collection('app_config').document('notifications').set({
            'today_sent_count': 0,
            'last_sent_date': today_str,
        }, merge=True)

    # Check force flag from Firestore (Admin panel test trigger)
    firestore_test_send = config.get('force_test_send', False)
    if firestore_test_send:
        print("[Trigger] Admin panel requested an immediate force test send!")
        force = True

    # 3. Schedule & Quota Verifications
    if not force:
        if not config.get('enabled', True):
            print("[SKIP] Push notifications are currently DISABLED in MovieAll Admin.")
            return

        allowed_hours = config.get('allowed_hours', [])
        if current_hour not in allowed_hours:
            print(f"[SKIP] Hour {current_hour}h is not in allowed hours list {allowed_hours}.")
            return

        max_per_day = config.get('max_per_day', 3)
        if today_sent_count >= max_per_day:
            print(f"[SKIP] Daily notification quota reached ({today_sent_count}/{max_per_day}).")
            return

    # 4. Determine Target Types & Sources
    target_types = [type_override] if type_override else config.get('content_types', ['film', 'serie', 'anime', 'animation'])
    target_sources = config.get('source_providers', ['french-stream', 'french-manga', 'anime-sama'])

    print(f"[Scraper] Target types: {target_types} | Sources: {target_sources}")

    # Fetch candidate novelties
    novelties = fetch_latest_novelties(target_types=target_types, target_sources=target_sources)
    print(f"[Scraper] Total fresh novelties scraped: {len(novelties)}")

    if not novelties:
        print("[WARNING] No novelties could be scraped. Aborting cycle.")
        return

    # Filter out items already notified in history
    sent_ids = fetch_recently_notified_ids(db, limit=150)
    candidate_items = [it for it in novelties if it.get('id') not in sent_ids]

    if candidate_items:
        selected_item = candidate_items[0]
        print(f"[Selection] Picked unnotified novelty: {selected_item['title']} ({selected_item['type']}, {selected_item['source']})")
    else:
        # If all candidates were already sent, pick the newest one
        selected_item = novelties[0]
        print(f"[Selection] All candidates in history, picking newest: {selected_item['title']}")

    # 5. Fetch FCM Tokens
    tokens = list(fetch_registered_fcm_tokens(db))
    print(f"[FCM] Found {len(tokens)} active registered device token(s) in Firestore.")

    if not tokens:
        print("[INFO] No FCM device tokens found in Firestore 'users'. Nothing to dispatch.")
        # If dry run or test, still update admin stats
        if not dry_run:
            db.collection('app_config').document('notifications').set({
                'last_sent_at': current_dt.isoformat(),
                'last_sent_title': selected_item['title'],
                'last_sent_poster': selected_item.get('poster', ''),
                'last_sent_type': selected_item.get('type', ''),
                'force_test_send': False,
            }, merge=True)
        return

    # 6. Dispatch Notifications
    if dry_run:
        title, body = format_notification(selected_item)
        print("[DRY-RUN] Would send notification:")
        print(f"  Title: {title}")
        print(f"  Body:  {body}")
        print(f"  Image: {selected_item.get('poster')}")
        print(f"  To:    {len(tokens)} devices")
        return

    success_count, failure_count, dead_tokens = send_multicast_notifications(tokens, selected_item)
    print(f"[FCM Result] Sent: {success_count} success, {failure_count} failure.")

    # 7. Update Firestore History & Admin Config
    # Record in history
    db.collection('notifications_history').document(selected_item['id']).set({
        'id': selected_item['id'],
        'title': selected_item['title'],
        'type': selected_item['type'],
        'source': selected_item['source'],
        'poster': selected_item.get('poster', ''),
        'description': selected_item.get('description', ''),
        'url': selected_item.get('url', ''),
        'sent_at': firestore.SERVER_TIMESTAMP,
        'sent_at_iso': current_dt.isoformat(),
        'recipients_count': len(tokens),
        'success_count': success_count,
        'failure_count': failure_count,
    })

    # Update config
    new_today_count = today_sent_count + 1
    db.collection('app_config').document('notifications').set({
        'today_sent_count': new_today_count,
        'last_sent_date': today_str,
        'last_sent_at': current_dt.isoformat(),
        'last_sent_title': selected_item['title'],
        'last_sent_poster': selected_item.get('poster', ''),
        'last_sent_type': selected_item.get('type', ''),
        'force_test_send': False,
    }, merge=True)

    print(f"[Done] Cycle completed successfully. Updated today quota to {new_today_count}.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="MovieAll GitHub Actions Notification Dispatcher")
    parser.add_argument('--force', action='store_true', help="Force dispatch bypassing quota & hour constraints")
    parser.add_argument('--dry-run', action='store_true', help="Simulate execution without sending FCM pushes")
    parser.add_argument('--type', type=str, default=None, help="Override content type (film, serie, anime, animation)")
    parser.add_argument('--service-account', type=str, default=None, help="Path to Firebase service account JSON")

    args = parser.parse_args()
    run_notification_cycle(
        force=args.force,
        service_account=args.service_account,
        type_override=args.type,
        dry_run=args.dry_run,
    )
