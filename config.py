"""
config.py — Paramètres métier de l'agent PubMed Oxeltis
========================================================
Ce fichier contient TOUTE la "sauce secrète" de qualification des leads.
Il peut être modifié par l'expert Oxeltis sans toucher au code de l'application.

Sections :
  1. OXELTIS_CONTEXT       → Description des services d'Oxeltis (injecté dans Claude)
  2. SCORING_RULES         → Règles de score 0-5 (injecté dans Claude)
  3. INDUSTRY_KEYWORDS     → Mots qui signalent une affiliation industrie dans PubMed
  4. ACADEMIC_KEYWORDS     → Mots qui signalent un labo académique (à exclure)
  5. SKIP_DOMAINS          → Sites web à ignorer lors de la recherche d'URL
"""

# ══════════════════════════════════════════════════════════════════════════════
# 1. CONTEXTE OXELTIS
#    Décrit ce qu'Oxeltis fait et ne fait PAS.
#    Claude s'en sert pour évaluer si une société est dans le scope.
#    → Modifier si Oxeltis ajoute/retire des services ou change de focus.
# ══════════════════════════════════════════════════════════════════════════════

OXELTIS_CONTEXT = """
Oxeltis est un CRO (Contract Research Organization) spécialisé en chimie médicinale
et chimie organique fine.

Services proposés :
- Hit-to-Lead optimization et Lead optimization (petites molécules / small molecules)
- Synthèse custom : nucléosides, nucléotides, phosphoramidites, PROTACs, ADC linkers, peptides
- Chimiothèque focalisée (10-100 composés), scouting de routes de synthèse (mg à 100g)
- Chimies complexes : hétérocycliques, macrocycles, fluor, phosphore
- ADME/PK in vitro, analyse SAR, sélection de candidats médicaments
- In silico design (CADD, SBDD, LBDD, AI/ML) via partenariats
- Criblage in vitro et profilage pharmacologique précoce

Domaines thérapeutiques prioritaires :
- Antiviraux (nucléosides, analogues de nucléotides)
- Antibactériens / résistance aux antibiotiques
- Oncologie early-stage (inhibiteurs de kinases, dégradeurs PROTAC)
- Maladies rares / orphelines
- Neurologie (composés BBB-penetrant)

Ce qu'Oxeltis NE fait PAS :
- Thérapies biologiques : anticorps monoclonaux, protéines thérapeutiques
- Gene therapy, cell therapy, CAR-T
- Vaccins mRNA
- Programmes en phase clinique avancée (Phase II/III) sans besoin de nouveaux composés
"""


# ══════════════════════════════════════════════════════════════════════════════
# 2. RÈGLES DE SCORING (0 à 5)
#    Ces règles sont envoyées à Claude pour qu'il attribue un score à chaque société.
#    → Modifier si les critères de qualification d'Oxeltis changent.
#    → Modifier la règle "accroche" pour changer le ton des messages de prospection.
# ══════════════════════════════════════════════════════════════════════════════

SCORING_RULES = """
MODALITE (type de programme) :
- small_molecule : détecte "small molecule", "medicinal chemistry", "CADD", "SBDD",
  "drug discovery", "hit-to-lead", "lead optimization", "synthesis", "compound",
  "nucleoside", "PROTAC", "fragment", "HTS", "SAR", "chemical matter"
- biologics : détecte "antibody", "biologics", "gene therapy", "cell therapy",
  "mRNA", "CAR-T", "protein therapeutic", "monoclonal" SANS mention small molecule
- mixte : les deux familles sont présentes
- inconnu : aucun signal clair

STADE (avancement du programme) :
- hit_to_lead : "hit identification", "hit-to-lead", "fragment screening", "HTS", "early discovery"
- lead_opt : "lead optimization", "lead candidate", "IND-enabling", "preclinical optimization"
- preclinique : "preclinical", "in vivo", "animal model", "IND filed" (sans lead opt)
- clinique : "Phase I", "Phase II", "Phase III", "clinical trial", "clinical stage"
- inconnu : aucun signal clair

SCORE (1 à 5) — pertinence pour Oxeltis :
- 5 : small_molecule + hit_to_lead ou lead_opt → prospect chaud idéal
- 4 : small_molecule + stade préclinique ou inconnu (peut avoir besoin de nouvelles molécules)
- 3 : small_molecule probable/mixte OU nucléoside/PROTAC/fragment mentionné
- 2 : modalité incertaine, stade clinique avancé, ou société trop grande
- 1 : biologics / gene therapy / cell therapy / mRNA / CAR-T (hors scope Oxeltis)
- 0 : contenu insuffisant ou site inaccessible

ACCROCHE — règles de rédaction :
- Une phrase en français, personnalisée, mentionnant le nom de la société
- Mentionner leur programme ou domaine thérapeutique si identifié
- Expliquer concrètement comment Oxeltis peut aider (ex: synthèse, hit-to-lead, etc.)
- Ton professionnel et direct (pas de formules génériques)
- Si score=1 → écrire "Hors scope Oxeltis — programme biologics/gene therapy"
- Si score=0 → écrire "Contenu insuffisant pour qualifier ce prospect"
"""


# ══════════════════════════════════════════════════════════════════════════════
# 3. MOTS-CLÉS : AFFILIATIONS INDUSTRIE
#    Si UNE de ces expressions est trouvée dans l'affiliation d'un auteur PubMed,
#    la société est considérée comme industrielle (biotech/pharma) et sera analysée.
#    → Ajouter des termes si des affiliations pertinentes sont manquées.
#    → Retirer des termes si trop de faux positifs sont générés.
# ══════════════════════════════════════════════════════════════════════════════

INDUSTRY_KEYWORDS = [
    # Types de sociétés
    "therapeutics",
    "biosciences",
    "biotech",
    "pharma",
    "pharmaceuticals",
    "biopharmaceutical",
    "biopharma",
    "biotechnology",
    "drug discovery",
    "medicines",
    # Formes juridiques (signalent une entreprise privée)
    " inc.",
    " inc,",
    " llc",
    " llc,",
    " ltd",
    " ltd.",
    " gmbh",
    " s.a.",
    " s.a.s.",
    " b.v.",
    " ag,",
    " ag ",
    " corp.",
    " corporation",
    # Termes complémentaires
    "sciences inc",
    "bioscience",
]


# ══════════════════════════════════════════════════════════════════════════════
# 4. MOTS-CLÉS : AFFILIATIONS ACADÉMIQUES (à exclure)
#    Si UNE de ces expressions est trouvée, l'affiliation est considérée comme
#    un labo académique et sera ignorée (pas un prospect pour Oxeltis).
#    → Ajouter des termes si des labos passent encore dans les résultats.
# ══════════════════════════════════════════════════════════════════════════════

ACADEMIC_KEYWORDS = [
    "university",
    "université",
    "universitat",
    "università",
    "universidad",
    "universidade",
    "college",
    "institute of",
    "hospital",
    "school of",
    "faculty",
    "department of",
    "national institutes",
    "national institute",
    "nih ",
    "cnrs",
    "inserm",
    "max planck",
    "academy of",
    "center for",
    "centre for",
    "laborator",
    "research foundation",
    "medical center",
    "medical centre",
    "cancer center",
    "cancer centre",
    "école",
    "ecole",
]


# ══════════════════════════════════════════════════════════════════════════════
# 5. DOMAINES À IGNORER (lors de la recherche d'URL d'une société)
#    Ces domaines ne sont jamais retenus comme site officiel d'une société.
#    → Ajouter un domaine si Firecrawl retourne trop souvent des agrégateurs.
# ══════════════════════════════════════════════════════════════════════════════

SKIP_DOMAINS = [
    # Réseaux sociaux
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "youtube.com",
    # Bases de données scientifiques
    "pubmed.ncbi",
    "ncbi.nlm.nih.gov",
    "biorxiv.org",
    "medrxiv.org",
    "nature.com",
    "science.org",
    "researchgate.net",
    "academia.edu",
    # Agrégateurs business
    "crunchbase.com",
    "bloomberg.com",
    "reuters.com",
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
    "sec.gov",
    "pitchbook.com",
    "zoominfo.com",
    "dnb.com",
    "wikipedia.org",
    "indeed.com",
    "glassdoor.com",
    "nih.gov",
]
