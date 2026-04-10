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

# ── Import des valeurs par défaut depuis config.py ────────────────────────────
from config import (
    OXELTIS_CONTEXT      as DEFAULT_OXELTIS_CONTEXT,
    SCORING_RULES        as DEFAULT_SCORING_RULES,
    INDUSTRY_KEYWORDS    as DEFAULT_INDUSTRY_KEYWORDS,
    ACADEMIC_KEYWORDS    as DEFAULT_ACADEMIC_KEYWORDS,
    SKIP_DOMAINS         as DEFAULT_SKIP_DOMAINS,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Oxeltis — PubMed Lead Finder",
    page_icon="🔬",
    layout="wide"
)

# ── Initialisation de la session (valeurs par défaut au premier chargement) ───
if "oxeltis_context" not in st.session_state:
    st.session_state.oxeltis_context   = DEFAULT_OXELTIS_CONTEXT
if "scoring_rules" not in st.session_state:
    st.session_state.scoring_rules     = DEFAULT_SCORING_RULES
if "industry_kw" not in st.session_state:
    st.session_state.industry_kw       = "\n".join(DEFAULT_INDUSTRY_KEYWORDS)
if "academic_kw" not in st.session_state:
    st.session_state.academic_kw       = "\n".join(DEFAULT_ACADEMIC_KEYWORDS)
if "skip_domains" not in st.session_state:
    st.session_state.skip_domains      = "\n".join(DEFAULT_SKIP_DOMAINS)


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_system_prompt():
    """Construit le prompt Claude à partir des valeurs de la session."""
    return f"""Tu es un expert en analyse de biotechs pour qualifier des prospects pour Oxeltis.

{st.session_state.oxeltis_context}

Analyse le contenu d'un site web de biotech et retourne UNIQUEMENT un JSON valide,
sans texte avant ni après, sans markdown, sans backticks.

{st.session_state.scoring_rules}

Format JSON attendu :
{{
  "modalite": "small_molecule|biologics|mixte|inconnu",
  "stade": "hit_to_lead|lead_opt|preclinique|clinique|inconnu",
  "score": <entier 0 à 5>,
  "accroche": "<une phrase de prospection en français, personnalisée, mentionnant la société et leur programme>"
}}"""


def get_industry_kw():
    return [k.strip() for k in st.session_state.industry_kw.splitlines() if k.strip()]

def get_academic_kw():
    return [k.strip() for k in st.session_state.academic_kw.splitlines() if k.strip()]

def get_skip_domains():
    return [d.strip() for d in st.session_state.skip_domains.splitlines() if d.strip()]


# ── PubMed helpers ─────────────────────────────────────────────────────────────

def pubmed_search(query, max_results=30, months_back=12):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months_back * 30)
    date_filter = f"{start_date.strftime('%Y/%m/%d')}:{end_date.strftime('%Y/%m/%d')}[pdat]"
    full_query = f"({query}) AND {date_filter}"
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": full_query, "retmax": max_results,
                    "retmode": "json", "sort": "relevance"},
            timeout=15
        )
        r.raise_for_status()
        return r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        st.error(f"Erreur PubMed search : {e}")
        return []


def pubmed_fetch(pmids):
    if not pmids:
        return []
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"},
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
        affiliations = [aff.text for aff in article.findall(".//Affiliation") if aff.text]
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else ""
        papers.append({"pmid": pmid, "title": title, "abstract": abstract[:300], "affiliations": affiliations})

    return papers


def extract_companies(affiliations):
    """Utilise les mots-clés de la session pour distinguer industrie vs académique."""
    industry_kw = get_industry_kw()
    academic_kw = get_academic_kw()
    companies = []
    for aff in affiliations:
        aff_lower = aff.lower()
        if any(kw in aff_lower for kw in academic_kw):
            continue
        if any(kw in aff_lower for kw in industry_kw):
            name = aff.split(",")[0].strip()
            name = re.sub(r'\s+', ' ', name)
            if 3 < len(name) < 80:
                companies.append(name)
    return list(set(companies))


# ── Firecrawl helpers ──────────────────────────────────────────────────────────

def firecrawl_search_url(company_name, api_key):
    skip = get_skip_domains()
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": f"{company_name} official website biotech drug discovery", "limit": 5},
            timeout=15
        )
        if r.status_code == 200:
            for result in r.json().get("data", []):
                url = result.get("url", "")
                if not any(d in url for d in skip):
                    parsed = urlparse(url)
                    return f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        pass
    return None


def firecrawl_scrape(url, api_key):
    try:
        r = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
    system_prompt = build_system_prompt()
    user_msg = f"Société : {company_name}"
    if paper_title:
        user_msg += f"\nPaper PubMed associé : {paper_title}"
    user_msg += f"\n\nContenu du site :\n{site_content}"

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}]
            )
            raw = re.sub(r"```(?:json)?", "", response.content[0].text.strip()).strip()
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
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Leads PubMed')
        ws = writer.sheets['Leads PubMed']
        from openpyxl.styles import PatternFill, Font
        green  = PatternFill("solid", fgColor="C6EFCE")
        yellow = PatternFill("solid", fgColor="FFEB9C")
        pink   = PatternFill("solid", fgColor="FFC7CE")
        gray   = PatternFill("solid", fgColor="EFEFEF")
        for cell in ws[1]:
            cell.font = Font(bold=True)
        score_col = next((i for i, c in enumerate(ws[1], 1) if c.value == "Score"), None)
        if score_col:
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                score = row[score_col - 1].value or 0
                fill = green if score >= 4 else (yellow if score >= 2 else (pink if score == 1 else gray))
                for cell in row:
                    cell.fill = fill
        for col, width in {"A": 30, "B": 60, "C": 30, "D": 15, "E": 8, "F": 15, "G": 70, "H": 12}.items():
            ws.column_dimensions[col].width = width
        ws.auto_filter.ref = ws.dimensions
    return output.getvalue()


def stars(score):
    return "☆☆☆☆☆" if score == 0 else "★" * score + "☆" * (5 - score)


# ══════════════════════════════════════════════════════════════════════════════
# UI — deux onglets : Recherche | Critères de qualification
# ══════════════════════════════════════════════════════════════════════════════

st.title("🔬 Oxeltis — PubMed Lead Finder")
st.caption("Identifie des biotechs avec des programmes drug discovery actifs via les publications scientifiques récentes")

tab_search, tab_config = st.tabs(["🔍 Recherche", "⚙️ Critères de qualification"])


# ── ONGLET 2 : Critères (affiché en premier pour la logique de session) ────────
with tab_config:
    st.subheader("⚙️ Critères de qualification — modifiables pour chaque session")
    st.info("Ces réglages s'appliquent à la prochaine recherche. Ils sont **remis à zéro** si tu recharges la page.")

    st.markdown("### 1. Description des services Oxeltis")
    st.caption("Ce texte est envoyé à Claude pour qu'il sache ce qu'Oxeltis fait et ne fait pas.")
    new_context = st.text_area(
        "Contexte Oxeltis",
        value=st.session_state.oxeltis_context,
        height=220,
        label_visibility="collapsed"
    )

    st.markdown("### 2. Règles de scoring (0 à 5)")
    st.caption("Définit ce qui est un prospect chaud (5), tiède (3), ou hors scope (1). Modifie les descriptions selon les retours terrain.")
    new_scoring = st.text_area(
        "Règles de scoring",
        value=st.session_state.scoring_rules,
        height=320,
        label_visibility="collapsed"
    )

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### 3. Mots-clés — Affiliations INDUSTRIE")
        st.caption("Un mot par ligne. Si trouvé dans l'affiliation d'un auteur PubMed → la société est retenue pour analyse.")
        new_industry = st.text_area(
            "Mots-clés industrie",
            value=st.session_state.industry_kw,
            height=250,
            label_visibility="collapsed"
        )

    with col_right:
        st.markdown("### 4. Mots-clés — Affiliations ACADÉMIQUES (à exclure)")
        st.caption("Un mot par ligne. Si trouvé → l'affiliation est ignorée (labo, université, hôpital...).")
        new_academic = st.text_area(
            "Mots-clés académiques",
            value=st.session_state.academic_kw,
            height=250,
            label_visibility="collapsed"
        )

    st.markdown("### 5. Domaines web à ignorer")
    st.caption("Un domaine par ligne. Ces sites ne seront jamais retenus comme site officiel d'une société.")
    new_skip = st.text_area(
        "Domaines à ignorer",
        value=st.session_state.skip_domains,
        height=180,
        label_visibility="collapsed"
    )

    col_btn1, col_btn2 = st.columns([1, 3])
    with col_btn1:
        if st.button("💾 Appliquer les modifications", type="primary", use_container_width=True):
            st.session_state.oxeltis_context = new_context
            st.session_state.scoring_rules   = new_scoring
            st.session_state.industry_kw     = new_industry
            st.session_state.academic_kw     = new_academic
            st.session_state.skip_domains    = new_skip
            st.success("✅ Critères mis à jour ! La prochaine recherche utilisera ces réglages.")
    with col_btn2:
        if st.button("↺ Remettre les valeurs par défaut", use_container_width=True):
            st.session_state.oxeltis_context = DEFAULT_OXELTIS_CONTEXT
            st.session_state.scoring_rules   = DEFAULT_SCORING_RULES
            st.session_state.industry_kw     = "\n".join(DEFAULT_INDUSTRY_KEYWORDS)
            st.session_state.academic_kw     = "\n".join(DEFAULT_ACADEMIC_KEYWORDS)
            st.session_state.skip_domains    = "\n".join(DEFAULT_SKIP_DOMAINS)
            st.rerun()


# ── ONGLET 1 : Recherche ───────────────────────────────────────────────────────
with tab_search:
    with st.sidebar:
        st.header("⚙️ Clés API")
        anthropic_key = st.text_input("Clé API Anthropic", type="password", placeholder="sk-ant-api03-...")
        firecrawl_key = st.text_input("Clé API Firecrawl", type="password", placeholder="fc-...")

        st.divider()
        st.header("🔍 Paramètres")
        search_query = st.text_input(
            "Mots-clés PubMed",
            value="small molecule drug discovery hit-to-lead",
            help="Ex: 'antiviral nucleoside synthesis', 'PROTAC degrader oncology'"
        )
        max_papers  = st.slider("Papers à analyser", 10, 100, 30, step=10)
        months_back = st.slider("Période (mois en arrière)", 1, 24, 12)
        min_score   = st.slider("Score minimum à afficher", 0, 5, 3)

        st.divider()
        st.info("💡 30 papers → ~10-20 sociétés → ~0.10-0.20 USD en API.")

        run_button = st.button("🚀 Lancer la recherche", type="primary", use_container_width=True)

    if run_button:
        if not anthropic_key or not firecrawl_key:
            st.error("⚠️ Renseigne les deux clés API dans la sidebar.")
            st.stop()

        client  = anthropic.Anthropic(api_key=anthropic_key)
        results = []

        # ── Étape 1 : PubMed ──────────────────────────────────────────────────
        with st.status("🔍 Étape 1/3 — Recherche PubMed...", expanded=True) as status:
            st.write(f"Requête : `{search_query}` — {months_back} derniers mois")
            pmids = pubmed_search(search_query, max_papers, months_back)

            if not pmids:
                st.error("Aucun paper trouvé. Essaie d'autres mots-clés.")
                st.stop()

            st.write(f"✅ {len(pmids)} papers trouvés")
            papers = pubmed_fetch(pmids)
            st.write(f"✅ {len(papers)} papers récupérés")

            all_companies = {}
            for paper in papers:
                for c in extract_companies(paper["affiliations"]):
                    if c not in all_companies:
                        all_companies[c] = paper["title"]

            n = len(all_companies)
            st.write(f"🏢 **{n} sociétés industrielles identifiées**")
            status.update(label=f"✅ PubMed terminé — {n} sociétés", state="complete")

        if not all_companies:
            st.warning("Aucune société détectée. Les affiliations sont peut-être toutes académiques. Ajuste les mots-clés dans l'onglet ⚙️ Critères.")
            st.stop()

        # ── Étape 2 & 3 : Firecrawl + Claude ─────────────────────────────────
        st.info(f"🔄 Analyse de {n} sociétés via Firecrawl + Claude Haiku...")
        progress_bar = st.progress(0)
        status_text  = st.empty()
        companies_list = list(all_companies.items())

        for i, (company, paper_title) in enumerate(companies_list):
            progress_bar.progress((i + 1) / len(companies_list))
            status_text.text(f"[{i+1}/{len(companies_list)}] {company}...")

            url = firecrawl_search_url(company, firecrawl_key)
            time.sleep(0.5)

            if not url:
                results.append({
                    "Société": company,
                    "Paper PubMed": paper_title[:80] + ("..." if len(paper_title) > 80 else ""),
                    "Site web": "", "Modalite": "inconnu", "Score": 0, "Stade": "inconnu",
                    "Accroche": "URL introuvable — prospection manuelle", "★": "☆☆☆☆☆"
                })
                continue

            content = firecrawl_scrape(url, firecrawl_key)
            time.sleep(0.5)

            if not content:
                results.append({
                    "Société": company,
                    "Paper PubMed": paper_title[:80] + ("..." if len(paper_title) > 80 else ""),
                    "Site web": url, "Modalite": "inconnu", "Score": 0, "Stade": "inconnu",
                    "Accroche": "Site inaccessible — vérification manuelle", "★": "☆☆☆☆☆"
                })
                continue

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

        # ── Résultats ─────────────────────────────────────────────────────────
        df     = pd.DataFrame(results)
        df_all = df.sort_values("Score", ascending=False)
        df_flt = df_all[df_all["Score"] >= min_score]

        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sociétés analysées", len(results))
        c2.metric(f"Score ≥ {min_score} ★", len(df_flt))
        c3.metric("Score 5 ★", len(df_all[df_all["Score"] == 5]))
        c4.metric("Score 4 ★", len(df_all[df_all["Score"] == 4]))

        st.subheader(f"🎯 Leads qualifiés (Score ≥ {min_score})")

        if df_flt.empty:
            st.warning("Aucun lead avec ce score minimum. Baisse le filtre dans la sidebar.")
        else:
            def highlight_score(row):
                s = row["Score"]
                color = "#C6EFCE" if s >= 4 else ("#FFEB9C" if s >= 2 else ("#FFC7CE" if s == 1 else "#EFEFEF"))
                return [f"background-color: {color}"] * len(row)

            st.dataframe(df_flt.style.apply(highlight_score, axis=1), use_container_width=True, height=400)

            st.download_button(
                label="📥 Télécharger Excel (leads qualifiés)",
                data=to_excel(df_flt),
                file_name=f"oxeltis_pubmed_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )

            top = df_flt[df_flt["Score"] >= 4]
            if not top.empty:
                st.subheader(f"🏆 Top Prospects ({len(top)} sociétés ≥ 4★)")
                for _, row in top.iterrows():
                    with st.expander(f"{row['★']} **{row['Société']}** — {row['Modalite']} / {row['Stade']}"):
                        if row["Site web"]:
                            st.write(f"**Site :** {row['Site web']}")
                        st.write(f"**Paper :** {row['Paper PubMed']}")
                        st.write(f"**Accroche :** {row['Accroche']}")

        with st.expander("Voir toutes les sociétés analysées"):
            st.dataframe(df_all, use_container_width=True)
            st.download_button(
                label="📥 Télécharger Excel (toutes)",
                data=to_excel(df_all),
                file_name=f"oxeltis_pubmed_all_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
