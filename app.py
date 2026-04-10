"""
Oxeltis — PubMed Lead Finder
Trouve des biotechs avec des programmes drug discovery actifs via PubMed
"""

import streamlit as st
import requests
import anthropic
import pandas as pd
import time
import re
import json
from io import BytesIO
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import urlparse

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Oxeltis — PubMed Lead Finder",
    page_icon="🔬",
    layout="wide"
)

# ── Oxeltis context ───────────────────────────────────────────────────────────
OXELTIS_CONTEXT = """
Oxeltis est un CRO spécialisé en chimie médicinale et chimie organique fine.
Services : Hit-to-Lead, Lead optimization, synthèse custom (nucléosides, nucléotides,
phosphoramidites, PROTACs, ADC linkers), ADME/PK in vitro, analyse SAR.
Domaines cibles : antiviraux, antibactériens, oncologie early-stage.
NE fait PAS : biologics, anticorps, CAR-T, gene therapy, mRNA vaccines.
"""

SYSTEM_PROMPT = f"""Tu es un expert en analyse de biotechs pour qualifier des prospects pour Oxeltis.

{OXELTIS_CONTEXT}

Analyse le contenu d'un site web de biotech et retourne UNIQUEMENT un JSON valide,
sans texte avant ni après, sans markdown, sans backticks.

Règles score (1 à 5) :
- 5 : small_molecule + hit_to_lead ou lead_opt → prospect chaud idéal
- 4 : small_molecule + stade préclinique ou inconnu
- 3 : small_molecule probable/mixte ou nucleoside/PROTAC mentionné
- 2 : modalité incertaine ou stade clinique avancé
- 1 : biologics/gene therapy/cell therapy/mRNA (hors scope)
- 0 : contenu insuffisant

Format JSON attendu :
{{
  "modalite": "small_molecule|biologics|mixte|inconnu",
  "stade": "hit_to_lead|lead_opt|preclinique|clinique|inconnu",
  "score": <entier 0 à 5>,
  "accroche": "<une phrase de prospection en français, personnalisée, mentionnant la société et leur programme>"
}}"""

# ── PubMed helpers ─────────────────────────────────────────────────────────────

def pubmed_search(query, max_results=30, months_back=12):
    """Cherche des papers sur PubMed, retourne les PMIDs."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months_back * 30)
    date_filter = f"{start_date.strftime('%Y/%m/%d')}:{end_date.strftime('%Y/%m/%d')}[pdat]"
    full_query = f"({query}) AND {date_filter}"

    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": full_query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance"
            },
            timeout=15
        )
        r.raise_for_status()
        return r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        st.error(f"Erreur PubMed search : {e}")
        return []


def pubmed_fetch(pmids):
    """Récupère les détails (titre, abstract, affiliations) pour une liste de PMIDs."""
    if not pmids:
        return []
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "xml",
                "rettype": "abstract"
            },
            timeout=30
        )
        r.raise_for_status()
    except Exception as e:
        st.error(f"Erreur PubMed fetch : {e}")
        return []

    papers = []
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return []

    for article in root.findall(".//PubmedArticle"):
        title_el = article.find(".//ArticleTitle")
        title = (title_el.text or "") if title_el is not None else ""

        abstract_texts = article.findall(".//AbstractText")
        abstract = " ".join([(el.text or "") for el in abstract_texts])

        affiliations = []
        for aff in article.findall(".//Affiliation"):
            if aff.text:
                affiliations.append(aff.text)

        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        papers.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract[:300],
            "affiliations": affiliations,
        })

    return papers


def extract_companies(affiliations):
    """Extrait les noms de sociétés (pas les labos académiques) des affiliations."""
    # Mots-clés = industrie biotech/pharma
    industry_kw = [
        "therapeutics", "biosciences", "biotech", "pharma", "pharmaceuticals",
        "biopharmaceutical", "drug discovery", "medicines", "biotechnology",
        " inc.", " inc,", " llc", " ltd", " gmbh", " s.a.", " b.v.", " ag,",
        " ag ", " corp.", " corporation", "sciences inc", "biopharma"
    ]
    # Mots-clés = académique (à exclure)
    academic_kw = [
        "university", "université", "universitat", "college", "institute of",
        "hospital", "school of", "faculty", "department of", "national institutes",
        "nih ", "cnrs", "inserm", "max planck", "academy of", "center for",
        "centre for", "laborator"
    ]

    companies = []
    for aff in affiliations:
        aff_lower = aff.lower()
        if any(kw in aff_lower for kw in academic_kw):
            continue
        if any(kw in aff_lower for kw in industry_kw):
            # Prendre la première partie avant la virgule comme nom
            name = aff.split(",")[0].strip()
            name = re.sub(r'\s+', ' ', name)
            if 3 < len(name) < 80:
                companies.append(name)

    return list(set(companies))


# ── Firecrawl helpers ──────────────────────────────────────────────────────────

SKIP_DOMAINS = [
    'linkedin.com', 'crunchbase.com', 'bloomberg.com', 'reuters.com',
    'businesswire.com', 'prnewswire.com', 'sec.gov', 'wikipedia.org',
    'twitter.com', 'x.com', 'facebook.com', 'pubmed.ncbi', 'ncbi.nlm.nih.gov',
    'nature.com', 'science.org', 'biorxiv.org', 'medrxiv.org',
    'researchgate.net', 'academia.edu', 'nih.gov'
]


def firecrawl_search_url(company_name, api_key):
    """Cherche le site officiel d'une société via Firecrawl."""
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={"query": f"{company_name} official website biotech drug discovery", "limit": 5},
            timeout=15
        )
        if r.status_code == 200:
            results = r.json().get("data", [])
            for result in results:
                url = result.get("url", "")
                if not any(d in url for d in SKIP_DOMAINS):
                    parsed = urlparse(url)
                    return f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        pass
    return None


def firecrawl_scrape(url, api_key):
    """Scrape une URL avec Firecrawl, retourne le markdown (max 2500 chars)."""
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            timeout=20
        )
        if r.status_code == 200:
            content = r.json().get("data", {}).get("markdown", "")
            if content and len(content) > 100:
                return content[:2500]
    except Exception:
        pass
    return None


# ── Claude helper ──────────────────────────────────────────────────────────────

def analyze_company(company_name, site_content, client, paper_title=""):
    """Envoie le contenu à Claude Haiku et retourne le dict parsé."""
    user_msg = f"Société : {company_name}"
    if paper_title:
        user_msg += f"\nPaper PubMed associé : {paper_title}"
    user_msg += f"\n\nContenu du site :\n{site_content}"

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}]
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r"```(?:json)?", "", raw).strip()
            result = json.loads(raw)
            assert "score" in result and "accroche" in result
            result["score"] = max(0, min(5, int(result["score"])))
            return result
        except Exception:
            if attempt < 2:
                time.sleep(2)

    return {"modalite": "inconnu", "stade": "inconnu", "score": 0,
            "accroche": "Erreur d'analyse — vérification manuelle requise"}


# ── Excel export ───────────────────────────────────────────────────────────────

def to_excel(df):
    """Convertit le DataFrame en bytes Excel avec coloration par score."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Leads PubMed')
        ws = writer.sheets['Leads PubMed']

        from openpyxl.styles import PatternFill, Font, Alignment
        green  = PatternFill("solid", fgColor="C6EFCE")
        yellow = PatternFill("solid", fgColor="FFEB9C")
        pink   = PatternFill("solid", fgColor="FFC7CE")
        gray   = PatternFill("solid", fgColor="EFEFEF")

        # En-têtes en gras
        for cell in ws[1]:
            cell.font = Font(bold=True)

        # Couleur par score (colonne E = index 5)
        score_col = None
        for col_idx, cell in enumerate(ws[1], 1):
            if cell.value == "Score":
                score_col = col_idx
                break

        if score_col:
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                score_cell = row[score_col - 1]
                score = score_cell.value or 0
                fill = green if score >= 4 else (yellow if score >= 2 else (pink if score == 1 else gray))
                for cell in row:
                    cell.fill = fill

        # Largeurs de colonnes
        col_widths = {"A": 30, "B": 60, "C": 30, "D": 15, "E": 8, "F": 15, "G": 70, "H": 12}
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

        # Auto-filter
        ws.auto_filter.ref = ws.dimensions

    return output.getvalue()


def stars(score):
    if score == 0:
        return "☆☆☆☆☆"
    return "★" * score + "☆" * (5 - score)


# ── UI ─────────────────────────────────────────────────────────────────────────

st.title("🔬 Oxeltis — PubMed Lead Finder")
st.caption("Identifie des biotechs avec des programmes drug discovery actifs via les publications scientifiques récentes")

with st.sidebar:
    st.header("⚙️ Clés API")
    anthropic_key = st.text_input("Clé API Anthropic", type="password",
                                   placeholder="sk-ant-api03-...")
    firecrawl_key = st.text_input("Clé API Firecrawl", type="password",
                                   placeholder="fc-...")

    st.divider()
    st.header("🔍 Paramètres de recherche")

    search_query = st.text_input(
        "Mots-clés PubMed",
        value="small molecule drug discovery hit-to-lead",
        help="Exemples : 'antiviral nucleoside synthesis', 'PROTAC degrader oncology', 'medicinal chemistry lead optimization'"
    )
    max_papers = st.slider("Papers à analyser", 10, 100, 30, step=10)
    months_back = st.slider("Période (mois en arrière)", 1, 24, 12)
    min_score = st.slider("Score minimum à afficher", 0, 5, 3)

    st.divider()
    st.info("💡 **Tip :** Un run de 30 papers analyse ~10-20 sociétés et coûte ~0.10-0.20 USD en API.")

    run_button = st.button("🚀 Lancer la recherche", type="primary", use_container_width=True)

# ── Lancement ──────────────────────────────────────────────────────────────────
if run_button:
    if not anthropic_key or not firecrawl_key:
        st.error("⚠️ Renseigne les deux clés API dans la sidebar avant de lancer.")
        st.stop()

    client = anthropic.Anthropic(api_key=anthropic_key)
    results = []
    seen_companies = set()

    # ── Étape 1 : PubMed ────────────────────────────────────────────────────────
    with st.status("🔍 Étape 1/3 — Recherche PubMed...", expanded=True) as status:
        st.write(f"Requête : `{search_query}` — {months_back} derniers mois")
        pmids = pubmed_search(search_query, max_papers, months_back)

        if not pmids:
            st.error("Aucun paper trouvé. Essaie d'autres mots-clés.")
            st.stop()

        st.write(f"✅ {len(pmids)} papers trouvés")
        papers = pubmed_fetch(pmids)
        st.write(f"✅ {len(papers)} papers récupérés avec affiliations")

        # Extraction des sociétés
        all_companies = {}  # company_name → paper_title
        for paper in papers:
            companies = extract_companies(paper["affiliations"])
            for c in companies:
                if c not in all_companies:
                    all_companies[c] = paper["title"]

        n = len(all_companies)
        st.write(f"🏢 **{n} sociétés industrielles identifiées** dans les affiliations")
        status.update(label=f"✅ PubMed terminé — {n} sociétés trouvées", state="complete")

    if not all_companies:
        st.warning("Aucune société détectée. Les affiliations sont peut-être toutes académiques. Essaie d'autres mots-clés plus orientés industrie.")
        st.stop()

    # ── Étape 2 & 3 : Firecrawl + Claude ────────────────────────────────────────
    st.info(f"🔄 Analyse de {len(all_companies)} sociétés (Firecrawl + Claude Haiku)...")

    progress_bar = st.progress(0)
    status_text = st.empty()
    companies_list = list(all_companies.items())

    for i, (company, paper_title) in enumerate(companies_list):
        progress_bar.progress((i + 1) / len(companies_list))
        status_text.text(f"[{i+1}/{len(companies_list)}] {company}...")

        # Cherche l'URL
        url = firecrawl_search_url(company, firecrawl_key)
        time.sleep(0.5)

        if not url:
            results.append({
                "Société": company,
                "Paper PubMed": paper_title[:80] + ("..." if len(paper_title) > 80 else ""),
                "Site web": "",
                "Modalite": "inconnu",
                "Score": 0,
                "Stade": "inconnu",
                "Accroche": "URL introuvable — prospection manuelle",
                "★": "☆☆☆☆☆"
            })
            continue

        # Scrape le site
        content = firecrawl_scrape(url, firecrawl_key)
        time.sleep(0.5)

        if not content:
            results.append({
                "Société": company,
                "Paper PubMed": paper_title[:80] + ("..." if len(paper_title) > 80 else ""),
                "Site web": url,
                "Modalite": "inconnu",
                "Score": 0,
                "Stade": "inconnu",
                "Accroche": "Site inaccessible — vérification manuelle",
                "★": "☆☆☆☆☆"
            })
            continue

        # Analyse Claude
        r = analyze_company(company, content, client, paper_title)
        time.sleep(0.3)

        results.append({
            "Société": company,
            "Paper PubMed": paper_title[:80] + ("..." if len(paper_title) > 80 else ""),
            "Site web": url,
            "Modalite": r["modalite"],
            "Score": r["score"],
            "Stade": r["stade"],
            "Accroche": r["accroche"],
            "★": stars(r["score"])
        })

    progress_bar.progress(1.0)
    status_text.text("✅ Analyse terminée !")

    # ── Résultats ─────────────────────────────────────────────────────────────────
    df = pd.DataFrame(results)
    df_all = df.sort_values("Score", ascending=False)
    df_filtered = df_all[df_all["Score"] >= min_score]

    st.divider()

    # Métriques
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Sociétés analysées", len(results))
    col2.metric(f"Score ≥ {min_score} ★", len(df_filtered))
    col3.metric("Score 5 ★", len(df_all[df_all["Score"] == 5]))
    col4.metric("Score 4 ★", len(df_all[df_all["Score"] == 4]))

    st.subheader(f"🎯 Leads qualifiés (Score ≥ {min_score})")

    if df_filtered.empty:
        st.warning("Aucun lead avec ce score minimum. Baisse le filtre dans la sidebar.")
    else:
        def highlight_score(row):
            s = row["Score"]
            color = "#C6EFCE" if s >= 4 else ("#FFEB9C" if s >= 2 else ("#FFC7CE" if s == 1 else "#EFEFEF"))
            return [f"background-color: {color}"] * len(row)

        st.dataframe(
            df_filtered.style.apply(highlight_score, axis=1),
            use_container_width=True,
            height=400
        )

        # Bouton téléchargement
        excel_bytes = to_excel(df_filtered)
        st.download_button(
            label="📥 Télécharger Excel (leads qualifiés)",
            data=excel_bytes,
            file_name=f"oxeltis_pubmed_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

        # Détail des top prospects
        top = df_filtered[df_filtered["Score"] >= 4]
        if not top.empty:
            st.subheader(f"🏆 Top Prospects ({len(top)} sociétés ≥ 4★)")
            for _, row in top.iterrows():
                with st.expander(f"{row['★']} **{row['Société']}** — {row['Modalite']} / {row['Stade']}"):
                    if row["Site web"]:
                        st.write(f"**Site :** {row['Site web']}")
                    st.write(f"**Paper :** {row['Paper PubMed']}")
                    st.write(f"**Accroche :** {row['Accroche']}")

    # Option : voir tous les résultats
    with st.expander("Voir toutes les sociétés analysées"):
        st.dataframe(df_all, use_container_width=True)
        excel_all = to_excel(df_all)
        st.download_button(
            label="📥 Télécharger Excel (toutes les sociétés)",
            data=excel_all,
            file_name=f"oxeltis_pubmed_all_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
