"""
Novelty scrapers for MovieAll Push Notification System.
Fetches latest novelties from:
1. French Stream (Films, Séries, Animations)
2. French Manga (Animes / Mangas)
3. Anime-Sama (Animes)
"""

import re
import html
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def _clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    # Remove redundant whitespaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _truncate_description(desc: str, max_chars: int = 160) -> str:
    cleaned = _clean_text(desc)
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars - 3].rstrip() + "..."


def scrape_french_stream(target_types: Optional[List[str]] = None) -> List[Dict]:
    """
    Scrapes latest additions from French Stream.
    Supports types: 'film', 'serie', 'animation'
    """
    results = []
    base_urls = ["https://french-stream.net", "https://french-stream.one"]
    base_url = base_urls[0]

    type_mapping = [
        ('film', 'films'),
        ('serie', 's-tv'),
        ('animation', 'films/animations'),
    ]

    for ctype, path in type_mapping:
        if target_types and ctype not in target_types:
            continue

        url = f"{base_url}/{path}/"
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
            if resp.status_code != 200:
                continue

            resp.encoding = resp.apparent_encoding or 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')
            shorts = soup.select('div.short')

            for s in shorts[:15]:
                link_el = s.select_one('a.short-poster') or s.select_one("a[href*='newsid=']") or s.select_one('a')
                href = link_el.get('href') if link_el else ''

                id_match = re.search(r'newsid=(\d+)', href) or re.search(r'/(\d+)-', href)
                item_id = f"fs-{id_match.group(1)}" if id_match else None

                title_el = s.select_one('.short-title')
                title = title_el.get_text(strip=True) if title_el else ''
                title = title.replace(' affiche', '').strip()

                img_el = s.select_one('img')
                poster = ''
                if img_el:
                    poster = img_el.get('data-src') or img_el.get('src') or ''
                    if not title and img_el.get('alt'):
                        title = img_el.get('alt').replace(' affiche', '').strip()

                if poster and not poster.startswith('http'):
                    poster = f"{base_url.rstrip('/')}/{poster.lstrip('/')}"

                desc_el = s.select_one("[id^='desc-']") or s.select_one('.short-text')
                desc = desc_el.get_text(strip=True) if desc_el else ''

                if not title or not item_id:
                    continue

                if not desc:
                    if ctype == 'film':
                        desc = f"Découvrez le film {title} dès maintenant en streaming sur MovieAll !"
                    elif ctype == 'serie':
                        desc = f"Nouveaux épisodes de la série {title} disponibles sur MovieAll !"
                    else:
                        desc = f"{title} est disponible en streaming HD sur MovieAll !"

                results.append({
                    'id': item_id,
                    'title': _clean_text(title),
                    'type': ctype,
                    'poster': poster,
                    'description': _truncate_description(desc),
                    'source': 'french-stream',
                    'url': href if href.startswith('http') else f"{base_url.rstrip('/')}/{href.lstrip('/')}",
                })
        except Exception as e:
            print(f"[French-Stream] Error scraping {path}: {e}")

    return results


def scrape_french_manga(target_types: Optional[List[str]] = None) -> List[Dict]:
    """
    Scrapes latest additions from French Manga.
    Supports type: 'anime'
    """
    if target_types and 'anime' not in target_types:
        return []

    results = []
    base_url = "https://w16.french-manga.net"
    sections = ['manga-streaming-1', 'mangas-vf', 'mangas-vostfr']

    for section in sections[:1]:  # Main page contains latest releases
        url = f"{base_url}/{section}/"
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
            if resp.status_code != 200:
                continue

            resp.encoding = resp.apparent_encoding or 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')
            shorts = soup.select('div.short')

            for s in shorts[:15]:
                link_el = s.select_one('a.short-poster') or s.select_one("a[href*='newsid=']") or s.select_one('a')
                href = link_el.get('href') if link_el else ''

                id_match = re.search(r'newsid=(\d+)', href) or re.search(r'/(\d+)-', href)
                item_id = f"fm-{id_match.group(1)}" if id_match else None

                title_el = s.select_one('.short-title')
                title = title_el.get_text(strip=True) if title_el else ''

                img_el = s.select_one('img')
                poster = ''
                if img_el:
                    poster = img_el.get('data-src') or img_el.get('src') or ''
                    if not title and img_el.get('alt'):
                        title = img_el.get('alt').strip()

                if poster and not poster.startswith('http'):
                    poster = f"{base_url.rstrip('/')}/{poster.lstrip('/')}"

                desc_el = s.select_one("[id^='desc-']") or s.select_one('.short-text')
                desc = desc_el.get_text(strip=True) if desc_el else ''

                if not title or not item_id:
                    continue

                if not desc:
                    desc = f"L'anime {title} est disponible dès maintenant sur MovieAll !"

                results.append({
                    'id': item_id,
                    'title': _clean_text(title),
                    'type': 'anime',
                    'poster': poster,
                    'description': _truncate_description(desc),
                    'source': 'french-manga',
                    'url': href if href.startswith('http') else f"{base_url.rstrip('/')}/{href.lstrip('/')}",
                })
        except Exception as e:
            print(f"[French-Manga] Error scraping {section}: {e}")

    return results


def scrape_anime_sama(target_types: Optional[List[str]] = None) -> List[Dict]:
    """
    Scrapes latest additions from Anime-Sama.
    Supports type: 'anime'
    """
    if target_types and 'anime' not in target_types:
        return []

    results = []
    base_url = "https://anime-sama.to"
    url = f"{base_url}/catalogue/fragment.php?page=1"
    headers = {
        **DEFAULT_HEADERS,
        'Accept': 'application/json',
        'Referer': f"{base_url}/catalogue/",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            liste_html = data.get('liste', '') if isinstance(data, dict) else resp.text
            soup = BeautifulSoup(liste_html, 'html.parser')
            cards = soup.select('.as-carte, .catalog-card')

            for card in cards[:15]:
                data_url = card.get('data-url') or ''
                if not data_url:
                    link_el = card.select_one('a')
                    data_url = link_el.get('href') if link_el else ''

                slug_match = re.search(r'/catalogue/([^/]+)/?', data_url)
                slug = slug_match.group(1) if slug_match else None
                if not slug:
                    continue
                item_id = f"as-{slug}"

                title_el = card.select_one('.as-carte-titre') or card.select_one('h2, h3, .card-title')
                title = title_el.get_text(strip=True) if title_el else (card.get('data-nom') or slug)

                img_el = card.select_one('img')
                poster = ''
                if img_el:
                    poster = img_el.get('data-src') or img_el.get('src') or ''
                if not poster:
                    poster = card.get('data-img') or ''

                if poster and not poster.startswith('http'):
                    poster = f"{base_url.rstrip('/')}/{poster.lstrip('/')}"

                # Anime-Sama badge check (VF / VOSTFR / Saison)
                badges = [b.get_text(strip=True) for b in card.select('.as-badge')]
                badge_info = f" ({', '.join(badges)})" if badges else ""

                desc = f"L'anime {title}{badge_info} est maintenant disponible sur MovieAll !"

                results.append({
                    'id': item_id,
                    'title': _clean_text(title),
                    'type': 'anime',
                    'poster': poster,
                    'description': _truncate_description(desc),
                    'source': 'anime-sama',
                    'url': data_url if data_url.startswith('http') else f"{base_url.rstrip('/')}/{data_url.lstrip('/')}",
                })
    except Exception as e:
        print(f"[Anime-Sama] Error scraping catalogue: {e}")

    return results


def fetch_latest_novelties(
    target_types: Optional[List[str]] = None,
    target_sources: Optional[List[str]] = None
) -> List[Dict]:
    """
    Aggregates latest novelties across all supported providers based on requested
    types ('film', 'serie', 'anime', 'animation') and sources ('french-stream', 'french-manga', 'anime-sama').
    """
    novelties: List[Dict] = []

    # French Stream (film, serie, animation)
    if not target_sources or 'french-stream' in target_sources:
        fs_items = scrape_french_stream(target_types=target_types)
        novelties.extend(fs_items)

    # French Manga (anime)
    if not target_sources or 'french-manga' in target_sources:
        fm_items = scrape_french_manga(target_types=target_types)
        novelties.extend(fm_items)

    # Anime-Sama (anime)
    if not target_sources or 'anime-sama' in target_sources:
        as_items = scrape_anime_sama(target_types=target_types)
        novelties.extend(as_items)

    # Filter strictly by target_types if specified
    if target_types:
        normalized_types = [t.lower().strip() for t in target_types]
        novelties = [item for item in novelties if item.get('type') in normalized_types]

    # De-duplicate by ID while maintaining freshness order
    seen_ids = set()
    unique_items = []
    for item in novelties:
        item_id = item.get('id')
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            unique_items.append(item)

    return unique_items
