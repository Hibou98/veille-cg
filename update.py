#!/usr/bin/env python3
"""
VeilleCG - Script de mise a jour automatique du news.json
Sources : Legifrance, BOFiP, ANC, Compta Online, Village Justice, Francis Lefebvre
"""

import json
import re
import os
from datetime import datetime, timezone
from html.parser import HTMLParser


try:
    import feedparser
except ImportError:
    print("ERREUR : feedparser non installe. Executez : pip install feedparser")
    exit(1)

try:
    import requests
except ImportError:
    print("ERREUR : requests non installe. Executez : pip install requests")
    exit(1)

# ??? CONFIGURATION ????????????????????????????????????????????????????????????

SOURCES = [
    {
        "name": "Expert-Sup - Droit fiscal",
        "url": "https://www.expert-sup.com/spip.php?page=backend&id_rubrique=53",
        "category_hint": "fiscal",
    },
    {
        "name": "Expert-Sup - Comptable",
        "url": "https://www.expert-sup.com/spip.php?page=backend&id_rubrique=56",
        "category_hint": "compta",
    },
    {
        "name": "Fiscalonline",
        "url": "https://fiscalonline.com/rss",
        "category_hint": "fiscal",
    },
    {
        "name": "Valoxy",
        "url": "https://valoxy.org/blog/feed/",
        "category_hint": None,
    },
    {
        "name": "Village Justice - Fiscal",
        "url": "https://www.village-justice.com/articles/backend.php?op=rss&rubrique=fiscal",
        "category_hint": "fiscal",
    },
    {
        "name": "Compta Online - Comptabilite",
        "url": "https://www.compta-online.com/comptabilite?format=feed&type=rss",
        "category_hint": "compta",
    },
    {
        "name": "Compta Online - Fiscalite",
        "url": "https://www.compta-online.com/fiscalite?format=feed&type=rss",
        "category_hint": "fiscal",
    },
    {
        "name": "BOSS",
        "url": "http://boss.gouv.fr/portail/fil-rss/pagecontent/flux-actualites.rss",
        "category_hint": "compta",
    },
]

# Francis Lefebvre n'expose pas de flux RSS public gratuit.
# Si tu as un abonnement, tu peux ajouter l'URL ici.
SOURCES_INDISPONIBLES = [
    "Francis Lefebvre (pas de flux RSS public - verification manuelle requise)"
]

# ??? MOTS-CLES D'EXCLUSION (articles hors scope compta/fiscal) ????????????????

MOTS_EXCLUSION = [
    "nomination ", "affectation ", "mutation ", "concours de ",
    "militaire", "armee", "defense nationale", "legion d'honneur", "medaille",
    "droit social", "droit du travail", "licenciement", "rupture conventionnelle",
    "droit de la famille", "divorce", "garde d'enfant",
    "urbanisme", "permis de construire", "droit de l'environnement",
    "droit de la sante", "droit de la consommation",
    "propriete intellectuelle", "marque deposee", "brevet d'invention",
    "droit penal", "infraction", "garde a vue", "tribunal correctionnel",
]

# Mots exclus specifiquement dans le TITRE
TITRES_EXCLUSION = [
    "decret", "arrete", "ordonnance", "circulaire",
    "nomination", "avis de vacance", "avis de concours",
    "portant nomination", "portant organisation",
    "relatif aux traitements", "relatif a l'organisation",
    "portant diverses dispositions",
]

# ??? MOTS-CLES POUR LA CATEGORISATION ?????????????????????????????????????????

MOTS_FISCAL = [
    "tva", "impot", "taxe", "fiscal", "is ", "ir ", "prelevement",
    "pas ", "cfe", "cvae", "liasse", "dgfip", "bofip", "declaration fiscale",
    "credit d'impot", "deficit", "plus-value", "exoneration fiscale",
    "cotisation", "acompte fiscal", "revenus fonciers", "micro-bic",
    "micro-bnc", "benefices industriels", "benefices non commerciaux",
    "facturation electronique", "e-invoicing", "pepite", "jeune entreprise",
    "jei ", "cice", "contribution", "droits d'enregistrement", "isf",
    "ifi ", "succession", "donation", "droits de mutation"
]

MOTS_COMPTA = [
    "comptable", "comptabilite", "pcg", "plan comptable", "anc",
    "norme", "amortissement", "provision", "bilan", "resultat",
    "capitaux propres", "immobilisation", "stock", "creance", "dette",
    "tresorerie", "flux de tresorerie", "consolidation", "ifrs",
    "commissaire aux comptes", "cac", "audit", "annexe", "ecart",
    "passif", "actif", "compte de resultat", "charge", "produit",
    "ecriture comptable", "journal", "grand livre", "balance",
    "depreciation", "reevaluation", "subvention", "engagement hors bilan"
]


# ??? UTILITAIRES ??????????????????????????????????????????????????????????????

class HTMLStripper(HTMLParser):
    """Supprime les balises HTML d'un texte."""
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ' '.join(self.fed)


def strip_html(text):
    if not text:
        return ""
    s = HTMLStripper()
    s.feed(text)
    clean = s.get_data()
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def truncate(text, max_chars=300):
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(' ', 1)[0] + '...'


def categorize(title, summary, hint):
    """Determine la categorie fiscal ou compta par mots-cles.
    Retourne None si l'article est hors scope (exclu)."""
    title_lower = title.lower()
    text = (title + " " + summary).lower()

    # Exclusion sur le titre seul - rejette decrets, arretes etc.
    if any(mot in title_lower for mot in TITRES_EXCLUSION):
        return None

    score_fiscal = sum(1 for mot in MOTS_FISCAL if mot in text)
    score_compta = sum(1 for mot in MOTS_COMPTA if mot in text)
    is_excluded = any(mot in text for mot in MOTS_EXCLUSION)

    if is_excluded and score_fiscal == 0 and score_compta == 0:
        return None  # article hors scope

    if hint in ("fiscal", "compta") and not is_excluded:
        return hint

    if score_fiscal == 0 and score_compta == 0:
        return None  # aucun mot-cle, on n'inclut pas

    return "fiscal" if score_fiscal >= score_compta else "compta"


def parse_date(entry):
    """Extrait et normalise la date d'une entree RSS."""
    try:
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        date_display = dt.strftime('%d/%m/%Y')
        date_iso = dt.strftime('%Y-%m-%d')
        return date_display, date_iso
    except Exception:
        now = datetime.now(timezone.utc)
        return now.strftime('%d/%m/%Y'), now.strftime('%Y-%m-%d')


# ??? CHARGEMENT DE L'HISTORIQUE ???????????????????????????????????????????????

def load_existing(filepath='news.json'):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"  ! Impossible de lire {filepath} : {e}")
    return []


# ??? SCRAPING RSS ?????????????????????????????????????????????????????????????

def fetch_source(source):
    """Recupere et parse le flux RSS d'une source."""
    print(f"  > {source['name']} : {source['url']}")
    articles = []

    try:
        # On passe par requests pour gerer les timeouts et les redirections
        headers = {'User-Agent': 'VeilleCG/1.0 (+https://github.com/veille-cg)'}
        resp = requests.get(source['url'], headers=headers, timeout=15)
        resp.raise_for_status()

        feed = feedparser.parse(resp.content)

        if feed.bozo and not feed.entries:
            print("    X Flux invalide ou inaccessible")
            return articles

        print(f"    OK {len(feed.entries)} entrees trouvees")

        for entry in feed.entries[:30]:  # max 30 par source
            title = strip_html(getattr(entry, 'title', 'Sans titre'))
            summary_raw = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
            summary = truncate(strip_html(summary_raw), 300)
            link = getattr(entry, 'link', '#')
            date_display, date_iso = parse_date(entry)
            category = categorize(title, summary, source['category_hint'])

            if not title or title == 'Sans titre':
                continue

            if category is None:
                continue  # article hors scope compta/fiscal

            articles.append({
                "id": link,  # utilise pour la deduplication
                "date": date_display,
                "date_iso": date_iso,
                "title": title,
                "summary": summary if summary else "Resume non disponible.",
                "source": source['name'],
                "link": link,
                "category": category
            })

    except requests.exceptions.Timeout:
        print("    X Timeout - source inaccessible")
    except requests.exceptions.ConnectionError:
        print("    X Erreur de connexion")
    except requests.exceptions.HTTPError as e:
        print(f"    X Erreur HTTP {e.response.status_code}")
    except Exception as e:
        print(f"    X Erreur inattendue : {e}")

    return articles


# ??? FUSION & DEDUPLICATION ???????????????????????????????????????????????????

def merge(existing, new_articles):
    existing_ids = {item['id'] for item in existing if 'id' in item}
    # Pour les anciens items sans id, on utilise le lien
    existing_links = {item.get('link', '') for item in existing}

    added = 0
    for article in new_articles:
        if article['id'] not in existing_ids and article['link'] not in existing_links:
            existing.append(article)
            existing_ids.add(article['id'])
            existing_links.add(article['link'])
            added += 1

    # Tri par date decroissante
    existing.sort(key=lambda x: x.get('date_iso', ''), reverse=True)
    return existing, added


# ??? SAUVEGARDE ???????????????????????????????????????????????????????????????

def save(data, filepath='news.json'):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nOK {filepath} sauvegarde ({len(data)} articles au total)")


# ??? MAIN ?????????????????????????????????????????????????????????????????????

def main():
    print("=" * 55)
    print(f"  VeilleCG - Mise a jour du {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    # Sources indisponibles
    if SOURCES_INDISPONIBLES:
        print("\n! Sources sans RSS public (verification manuelle) :")
        for s in SOURCES_INDISPONIBLES:
            print(f"  - {s}")

    # Chargement de l'historique
    print(f"\nChargement de l'historique...")
    existing = load_existing('news.json')
    print(f"  {len(existing)} articles en base")

    # Scraping
    print(f"\nRecuperation des flux RSS...")
    all_new = []
    for source in SOURCES:
        articles = fetch_source(source)
        all_new.extend(articles)

    print(f"\n  {len(all_new)} articles recuperes au total")

    # Fusion
    merged, added = merge(existing, all_new)
    print(f"  {added} nouveaux articles ajoutes")

    # Repartition par categorie
    fiscal = sum(1 for a in merged if a.get('category') == 'fiscal')
    compta = sum(1 for a in merged if a.get('category') == 'compta')
    print(f"  Repartition : {fiscal} fiscal | {compta} compta")

    # Sauvegarde
    save(merged, 'news.json')
    print("=" * 55)


if __name__ == '__main__':
    main()
