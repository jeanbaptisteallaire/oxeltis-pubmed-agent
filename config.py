"""
config.py — Oxeltis PubMed Agent — Business parameters
========================================================
This file contains ALL the qualification criteria ("secret sauce").
It can be modified by the Oxeltis expert without touching the application code.

Sections:
  1. OXELTIS_CONTEXT       → Description of Oxeltis services (injected into Claude)
  2. SCORING_RULES         → Scoring rules 0-5 (injected into Claude)
  3. INDUSTRY_KEYWORDS     → Words signaling an industry affiliation in PubMed
  4. ACADEMIC_KEYWORDS     → Words signaling an academic lab (to exclude)
  5. SKIP_DOMAINS          → Websites to ignore when searching for a company URL
"""

# ══════════════════════════════════════════════════════════════════════════════
# 1. OXELTIS CONTEXT
#    Describes what Oxeltis does and does NOT do.
#    Claude uses this to evaluate whether a company is in scope.
#    → Update when Oxeltis adds/removes services or changes focus.
# ══════════════════════════════════════════════════════════════════════════════

OXELTIS_CONTEXT = """
Oxeltis
- Medicinal chemistry services
- Fine organic chemistry services
- Early drug discovery support
- Hit-to-lead optimization
- Lead generation
- Lead optimization
- Drug candidate selection
- FTE chemist support

Biomedical focus
- Antivirals
- Antibacterials
- Oncology

Chemical capabilities
- Nucleoside chemistry
- Nucleotide chemistry
- Base-modified analogs
- Sugar-modified analogs
- Monophosphates
- Diphosphates
- Triphosphates
- Phosphoramidites
- Dinucleotides
- Oligosaccharides
- Monosaccharides
- Iminosugars
- Sugar phosphates
- Unnatural sugars
- Saccharide antigens
- Heterocyclic chemistry
- Macrocyclic chemistry
- Peptide chemistry
- ADC linkers
- Phosphorus chemistry
- Fluorine chemistry

Custom synthesis
- NCE synthesis
- Building blocks
- Scaffolds
- Intermediates
- Metabolites
- Impurities
- Reference compounds

Research and diagnostic tools
- Nucleoside analogs
- Nucleotide analogs
- Fluorescent dyes
- Diagnostic kit reagents

Scale
- mg to 50-100 g in-house
- 20 g to kg via external partners

Relevant buyer fit
- Antiviral drug developers
- Nucleos(t)ide drug developers
- Anti-infective biotech
- Oncology biotech
- Pharma discovery teams
- CRO outsourcing buyers
- Diagnostic and assay developers

What Oxeltis does NOT do:
- Biological therapies: monoclonal antibodies, protein therapeutics
- Gene therapy, cell therapy, CAR-T
- mRNA vaccines
- Advanced clinical-stage programs (Phase II/III) with no need for new compounds
"""


# ══════════════════════════════════════════════════════════════════════════════
# 2. SCORING RULES (0 to 5)
#    These rules are sent to Claude to assign a score to each company.
#    Context: companies are sourced from PubMed paper affiliations —
#    they already publish on drug discovery. The key differentiators are
#    company size (does it need a CRO?) and chemistry fit with Oxeltis.
#    → Update if Oxeltis qualification criteria change.
# ══════════════════════════════════════════════════════════════════════════════

SCORING_RULES = """
MODALITY (type of program):
- small_molecule: detects "small molecule", "medicinal chemistry", "CADD", "SBDD",
  "drug discovery", "hit-to-lead", "lead optimization", "synthesis", "compound",
  "nucleoside", "PROTAC", "fragment", "HTS", "SAR", "chemical matter"
- biologics: detects "antibody", "biologics", "gene therapy", "cell therapy",
  "mRNA", "CAR-T", "protein therapeutic", "monoclonal" WITHOUT mention of small molecule
- mixed: both families are present
- unknown: no clear signal

STAGE (program advancement):
- hit_to_lead: "hit identification", "hit-to-lead", "fragment screening", "HTS", "early discovery"
- lead_opt: "lead optimization", "lead candidate", "IND-enabling", "preclinical optimization"
- preclinical: "preclinical", "in vivo", "animal model", "IND filed" (without lead opt)
- clinical: "Phase I", "Phase II", "Phase III", "clinical trial", "clinical stage"
- unknown: no clear signal

SCORE (0 to 5) — relevance for Oxeltis as a CRO partner:

Key principle: companies are sourced from PubMed, so they already do drug discovery.
The score must reflect: (1) company size/need for external chemistry support,
(2) chemistry fit with Oxeltis expertise, (3) therapeutic area alignment.

- 5: Early-stage startup or small biotech (< ~50 employees suggested), small molecule program,
     AND topic directly matches Oxeltis specialty: nucleoside/nucleotide chemistry, antiviral,
     antibacterial, PROTAC, fragment-based, oncology early-stage. Ideal hot prospect.

- 4: Small-to-mid biotech (~50-200 employees), small molecule program, early or preclinical stage.
     Likely to outsource chemistry. Good prospect.

- 3: Mid-size biotech (200-1000 employees), small molecule, uncertain outsourcing need.
     Or small biotech with general chemistry not perfectly aligned with Oxeltis.
     Worth qualifying manually.

- 2: Large biotech (> 1000 employees) with possible outsourcing, or company at clinical stage
     where new chemistry needs are limited. Low priority.

- 1: Top 20 global pharma (Roche, Pfizer, Novartis, AstraZeneca, Merck, Lilly, J&J, BMS,
     Sanofi, GSK, AbbVie, Amgen, Gilead, Takeda, Bayer, Boehringer, etc.) — they have
     hundreds of internal chemists and will never outsource to a small CRO.
     OR pure biologics/gene therapy/cell therapy company (out of Oxeltis scope).

- 0: Academic institution incorrectly detected, or insufficient content to qualify.

OUTREACH MESSAGE rules:
- One sentence in English, personalized, mentioning the company name
- Reference their specific program or therapeutic area if identified
- Explain concretely how Oxeltis can help (synthesis, hit-to-lead, nucleoside chemistry, etc.)
- Professional and direct tone (no generic formulas)
- If score=1 → write "Out of scope for Oxeltis — large pharma or biologics program"
- If score=0 → write "Insufficient content to qualify this prospect"
"""


# ══════════════════════════════════════════════════════════════════════════════
# 3. KEYWORDS: INDUSTRY AFFILIATIONS
#    If ONE of these expressions is found in a PubMed author affiliation,
#    the company is considered an industry (biotech/pharma) entity and will be analyzed.
#    → Add terms if relevant affiliations are being missed.
#    → Remove terms if too many false positives are generated.
# ══════════════════════════════════════════════════════════════════════════════

INDUSTRY_KEYWORDS = [
    # Company types
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
    # Legal forms (signal a private company)
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
    # Complementary terms
    "sciences inc",
    "bioscience",
]


# ══════════════════════════════════════════════════════════════════════════════
# 4. KEYWORDS: ACADEMIC AFFILIATIONS (to exclude)
#    If ONE of these expressions is found, the affiliation is considered
#    an academic lab and will be ignored (not a prospect for Oxeltis).
#    → Add terms if academic labs still appear in results.
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
# 5. DOMAINS TO IGNORE (when searching for a company URL)
#    These domains are never retained as the official website of a company.
#    → Add a domain if Firecrawl keeps returning aggregator sites.
# ══════════════════════════════════════════════════════════════════════════════

SKIP_DOMAINS = [
    # Social media
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "youtube.com",
    # Scientific databases
    "pubmed.ncbi",
    "ncbi.nlm.nih.gov",
    "biorxiv.org",
    "medrxiv.org",
    "nature.com",
    "science.org",
    "researchgate.net",
    "academia.edu",
    # Business aggregators
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
