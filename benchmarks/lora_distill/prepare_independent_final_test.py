#!/usr/bin/env python3
"""Create a sealed intent test with no MMLU-Pro/supplement prompt reuse."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from core import LABELS, normalized_prompt_key, read_jsonl, write_jsonl


TOPICS = {
    "biology": (
        "mitochondrial inheritance", "plant phototropism", "bacterial quorum sensing",
        "CRISPR gene editing", "meiosis and genetic recombination", "enzyme inhibition",
        "ecological succession", "animal camouflage", "RNA splicing", "cellular senescence",
        "microbiome diversity", "epigenetic methylation", "natural selection in island species",
        "immune system memory", "protein folding", "stem cell differentiation",
        "coral reef symbiosis", "viral replication cycles", "plant transpiration",
        "population genetics", "circadian rhythms in animals", "fungal mycelium networks",
        "horizontal gene transfer", "embryonic development", "neuron action potentials",
        "photosynthetic light reactions", "DNA damage repair", "invasive species ecology",
        "hormonal signaling in plants", "predator prey coevolution", "ribosome function",
        "endosymbiotic theory", "antibiotic resistance evolution", "pollinator specialization",
        "cell membrane transport", "bioluminescence", "chromosome abnormalities",
        "nitrogen fixation", "animal migration biology", "telomere shortening",
        "gene regulatory networks", "aquatic food webs", "parasite host adaptation",
        "bone remodeling biology", "seed dormancy", "marine mammal physiology",
        "insect metamorphosis", "blood cell formation", "organ regeneration",
        "ecosystem carrying capacity",
    ),
    "business": (
        "customer acquisition cost", "brand positioning", "inventory turnover",
        "subscription churn", "product market fit", "supplier relationship management",
        "franchise operations", "board governance", "sales pipeline forecasting",
        "employee retention strategy", "merger integration", "working capital management",
        "retail merchandising", "business process outsourcing", "competitive differentiation",
        "market segmentation", "quality assurance programs", "corporate procurement",
        "key account management", "startup runway planning", "channel partner strategy",
        "service level agreements", "organizational restructuring", "customer lifetime value",
        "pricing strategy", "business continuity planning", "warehouse operations",
        "performance management systems", "corporate social responsibility",
        "new product launch planning", "stakeholder communication", "vendor due diligence",
        "direct to consumer sales", "management succession planning", "workplace culture audits",
        "international market entry", "operating margin improvement", "business model innovation",
        "loyalty program design", "commercial contract negotiation", "demand forecasting",
        "manufacturing capacity planning", "professional services utilization",
        "corporate reputation management", "sales territory design", "strategic partnerships",
        "family business governance", "customer support operations", "trade show marketing",
        "enterprise risk management",
    ),
    "chemistry": (
        "Lewis acid base reactions", "electrochemical cell potentials", "polymer crosslinking",
        "chirality in organic molecules", "transition metal catalysts", "buffer capacity",
        "gas chromatography", "crystal lattice energy", "free radical polymerization",
        "reaction rate laws", "solubility product constants", "nuclear magnetic resonance spectra",
        "aromatic substitution", "colloid stability", "oxidation state assignment",
        "molecular orbital theory", "acid catalyzed hydrolysis", "coordination complexes",
        "chemical equilibrium shifts", "mass spectrometry fragmentation", "hydrogen bonding",
        "photochemical reactions", "electrophilic addition", "ionic liquid properties",
        "surface adsorption chemistry", "redox titration", "organometallic reagents",
        "phase diagrams for mixtures", "isotope fractionation", "covalent network solids",
        "esterification reactions", "chemical vapor deposition", "protein crystallization chemistry",
        "combustion stoichiometry", "aqueous complex formation", "pericyclic reactions",
        "battery electrolyte chemistry", "soap micelle formation", "lanthanide chemistry",
        "chemical kinetics of enzymes", "spectrophotometric calibration", "corrosion chemistry",
        "supercritical fluid extraction", "peptide bond formation", "green solvent selection",
        "thermochemical cycles", "halogen exchange reactions", "zeolite catalysis",
        "chemical potential", "amorphous material chemistry",
    ),
    "computer science": (
        "distributed consensus algorithms", "garbage collection strategies", "database indexing",
        "public key infrastructure", "compiler register allocation", "container orchestration",
        "graph traversal algorithms", "cache coherence protocols", "functional programming",
        "network congestion control", "database transaction isolation", "memory safe languages",
        "software dependency injection", "approximate nearest neighbor search", "zero trust security",
        "event driven architectures", "binary search trees", "type inference",
        "operating system scheduling", "federated learning systems", "API versioning",
        "data serialization formats", "race condition debugging", "virtual memory paging",
        "code review automation", "stream processing", "cryptographic hash functions",
        "software testing pyramids", "load balancing algorithms", "columnar databases",
        "static program analysis", "web accessibility engineering", "message queue semantics",
        "GPU kernel optimization", "domain name resolution", "continuous integration pipelines",
        "computer vision segmentation", "recommender system feedback loops", "microservice tracing",
        "regular expression engines", "data structure amortized analysis", "secure boot chains",
        "distributed file systems", "programming language interpreters", "database query planners",
        "edge computing architecture", "lossless compression algorithms", "robot motion planning",
        "identity and access management", "fault tolerant software design",
    ),
    "economics": (
        "inflation expectations", "comparative advantage", "labor market monopsony",
        "central bank balance sheets", "price elasticity of demand", "sovereign debt sustainability",
        "network effects in markets", "carbon taxation", "behavioral economics nudges",
        "currency exchange rate regimes", "income inequality measurement", "auction market design",
        "public goods provision", "housing supply constraints", "economic productivity growth",
        "trade tariff incidence", "minimum wage effects", "consumer surplus",
        "bank runs and deposit insurance", "fiscal multipliers", "agricultural subsidies",
        "monetary policy transmission", "informal labor markets", "antitrust economics",
        "pension system funding", "recession leading indicators", "externalities and regulation",
        "human capital investment", "commodity price cycles", "game theory in bargaining",
        "economic rent seeking", "urban agglomeration economies", "healthcare market incentives",
        "real interest rates", "tax progressivity", "development economics institutions",
        "supply chain economic shocks", "unemployment duration", "insurance adverse selection",
        "economies of scale", "current account deficits", "platform economy competition",
        "land value taxation", "intergenerational mobility", "capital depreciation",
        "remittance driven economies", "consumer confidence indexes", "wage price spirals",
        "market liquidity", "demographic economic transitions",
    ),
    "engineering": (
        "reinforced concrete design", "heat exchanger sizing", "aircraft wing fatigue",
        "control system stability", "stormwater drainage design", "industrial robot calibration",
        "power grid protection", "composite material failure", "water treatment membranes",
        "wind turbine foundations", "traffic signal coordination", "pressure vessel safety",
        "manufacturing tolerance analysis", "earthquake resistant structures", "pump cavitation",
        "printed circuit board thermal design", "railway track geometry", "hydraulic actuator design",
        "nondestructive weld inspection", "solar farm electrical layout", "geotechnical soil testing",
        "aerodynamic drag reduction", "chemical process hazard analysis", "mechanical vibration isolation",
        "bridge load rating", "battery pack thermal management", "satellite attitude control",
        "pipeline integrity monitoring", "acoustic noise control", "industrial sensor calibration",
        "fiber optic network design", "desalination plant efficiency", "automotive braking systems",
        "building ventilation design", "marine propeller efficiency", "semiconductor fabrication yield",
        "reliability block diagrams", "wastewater aeration systems", "electric motor winding design",
        "construction project sequencing", "finite element mesh quality", "fire sprinkler hydraulics",
        "drone flight control", "materials creep testing", "industrial refrigeration systems",
        "dam spillway design", "biomedical prosthetic design", "radio antenna matching",
        "lean production cells", "structural buckling analysis",
    ),
    "health": (
        "managing high blood pressure", "seasonal allergy treatment", "childhood vaccination schedules",
        "iron deficiency symptoms", "physical therapy after knee surgery", "sleep apnea screening",
        "type 2 diabetes monitoring", "food allergy emergencies", "migraine prevention",
        "prenatal nutrition", "antibiotic side effects", "skin cancer warning signs",
        "cholesterol test interpretation", "asthma inhaler technique", "dehydration treatment",
        "postoperative wound care", "hearing loss assessment", "osteoporosis prevention",
        "kidney stone symptoms", "safe strength training", "influenza home care",
        "medication interaction checks", "vision screening", "chronic back pain management",
        "healthy meal planning", "concussion recovery", "dental gum disease prevention",
        "thyroid function testing", "emergency burn first aid", "arthritis pain management",
        "newborn sleep safety", "blood donation eligibility", "smoking cessation treatments",
        "menopause symptom management", "travel vaccination advice", "sprained ankle care",
        "colon cancer screening", "vitamin D deficiency", "heart attack warning signs",
        "occupational hearing protection", "oral rehydration therapy", "glaucoma monitoring",
        "pregnancy medication safety", "restless legs syndrome", "sports injury rehabilitation",
        "acid reflux treatment", "routine pediatric checkups", "insulin storage safety",
        "heat exhaustion response", "annual physical examinations",
    ),
    "history": (
        "the Meiji Restoration", "the Haitian Revolution", "Silk Road trade networks",
        "the fall of Constantinople", "the Mughal administrative system", "women in the Progressive Era",
        "the partition of India", "the Mali Empire", "the Congress of Vienna",
        "the Taiping Rebellion", "decolonization in Ghana", "the Byzantine iconoclasm controversy",
        "the Mexican Revolution", "the Abbasid translation movement", "the Dutch Golden Age",
        "the Warsaw Pact", "the unification of Italy", "the Great Zimbabwe civilization",
        "the Opium Wars", "the Spanish transition to democracy", "the Inca road system",
        "the Protestant Reformation", "the Suez Crisis", "the Harlem Renaissance",
        "the Peloponnesian War", "postwar reconstruction in Japan", "the abolition of serfdom in Russia",
        "the Algerian War of Independence", "the Hanseatic League", "the rise of the Ottoman Empire",
        "the New Deal coalition", "the Cultural Revolution in China", "the Viking settlement of Iceland",
        "the Iran Constitutional Revolution", "the collapse of the Soviet Union", "the Ashanti Empire",
        "the English Civil War", "the Bandung Conference", "the ancient city of Carthage",
        "the Cuban Missile Crisis", "the Tokugawa shogunate", "the Prague Spring",
        "the trans Saharan salt trade", "the reconstruction of Europe after 1945", "the Zulu Kingdom",
        "the Glorious Revolution", "the Philippine independence movement", "the Roman Republic reforms",
        "the Lebanese civil war", "the history of the printing press",
    ),
    "law": (
        "contract consideration requirements", "judicial review", "tenant eviction procedures",
        "patent infringement standards", "criminal intent requirements", "administrative rulemaking",
        "workplace discrimination claims", "international maritime law", "consumer warranty rights",
        "search warrant probable cause", "corporate fiduciary duties", "copyright fair use",
        "child custody jurisdiction", "environmental impact review", "evidence hearsay exceptions",
        "data privacy consent", "bankruptcy automatic stays", "negligence duty of care",
        "constitutional equal protection", "trade secret protection", "immigration asylum standards",
        "antitrust merger review", "legal professional privilege", "product liability",
        "zoning variance procedures", "criminal sentencing appeals", "arbitration agreements",
        "freedom of information requests", "tax residency rules", "employment noncompete clauses",
        "international treaty enforcement", "medical malpractice standards", "securities disclosure duties",
        "estate probate administration", "police interrogation rights", "class action certification",
        "government sovereign immunity", "landlord habitability obligations", "online platform liability",
        "indigenous land rights", "insurance bad faith claims", "public procurement law",
        "campaign finance restrictions", "defamation of public figures", "juvenile justice procedures",
        "cross border extradition", "statutory interpretation methods", "whistleblower protections",
        "electronic evidence authentication", "conflict of laws",
    ),
    "math": (
        "Fourier series convergence", "Bayesian probability", "eigenvalue decomposition",
        "modular arithmetic", "graph coloring", "partial differential equations",
        "convex optimization", "prime number distribution", "Markov chains",
        "topological compactness", "combinatorial generating functions", "numerical integration",
        "group homomorphisms", "linear regression geometry", "complex contour integration",
        "stochastic differential equations", "Boolean algebra", "matrix condition numbers",
        "non Euclidean geometry", "integer partitions", "Lagrange multipliers",
        "measure theory", "recurrence relations", "singular value decomposition",
        "mathematical induction", "spline interpolation", "set cardinality",
        "dynamical system bifurcations", "queueing theory", "tensor notation",
        "Diophantine equations", "probability generating functions", "finite field arithmetic",
        "calculus of variations", "random graph theory", "orthogonal polynomials",
        "fixed point theorems", "multivariate hypothesis testing", "wavelet transforms",
        "projective geometry", "quadratic programming", "continued fractions",
        "mathematical logic completeness", "Monte Carlo integration", "algebraic topology",
        "time series stationarity", "differential geometry curvature", "extremal combinatorics",
        "kernel density estimation", "fractional calculus",
    ),
    "other": (
        "planning a weekend camping trip", "baking sourdough bread", "choosing a birthday gift",
        "learning basic watercolor painting", "organizing a small apartment", "writing a mystery story",
        "planning a family game night", "repairing a loose cabinet hinge", "choosing hiking boots",
        "growing herbs on a balcony", "photographing a sunset", "packing for a beach vacation",
        "training a puppy to sit", "preparing a vegetarian dinner", "starting a book club",
        "decorating a home office", "learning acoustic guitar chords", "planning a wedding toast",
        "removing a coffee stain", "choosing a science fiction movie", "building a daily journaling habit",
        "finding a new podcast", "hosting a neighborhood picnic", "making homemade pasta",
        "planning a museum visit", "selecting a board game", "writing a thank you note",
        "caring for a houseplant", "organizing digital photographs", "choosing a bicycle helmet",
        "creating a travel itinerary", "learning to knit", "planning a surprise party",
        "improving smartphone photography", "making a weekly cleaning schedule", "adopting a rescue cat",
        "choosing curtains for a bedroom", "starting a vegetable garden", "preparing for a road trip",
        "recording a family recipe", "learning conversational Italian", "selecting camping cookware",
        "writing song lyrics", "planning a movie marathon", "restoring an old wooden chair",
        "choosing flowers for a celebration", "creating a scrapbook", "practicing public speaking",
        "setting up a home aquarium", "planning a community potluck",
    ),
    "philosophy": (
        "the trolley problem", "Cartesian skepticism", "Aristotelian virtue ethics",
        "the problem of personal identity", "existentialist authenticity", "the veil of ignorance",
        "philosophy of scientific realism", "the mind body problem", "Stoic views of control",
        "Kantian moral duty", "the paradox of tolerance", "phenomenology of perception",
        "free will and determinism", "utilitarian theories of justice", "the Gettier problem",
        "philosophy of language reference", "moral luck", "the ship of Theseus",
        "social contract theory", "epistemic injustice", "the ethics of artificial intelligence",
        "logical positivism", "the problem of induction", "Confucian role ethics",
        "philosophical pessimism", "animal rights ethics", "the nature of consciousness",
        "pragmatist theories of truth", "the simulation argument", "aesthetic judgments",
        "the ethics of civil disobedience", "Plato's theory of forms", "absurdism",
        "distributive justice", "the philosophy of time", "moral relativism",
        "the principle of double effect", "feminist standpoint epistemology", "theodicy",
        "philosophy of mathematical objects", "Buddhist concepts of self", "the ethics of punishment",
        "causal theories of knowledge", "the meaning of life", "political legitimacy",
        "environmental ethics", "the sorites paradox", "hermeneutics",
        "the philosophy of friendship", "rights based ethics",
    ),
    "physics": (
        "quantum tunneling", "gravitational lensing", "fluid boundary layers",
        "electromagnetic induction", "entropy in isolated systems", "neutrino oscillations",
        "wave particle duality", "blackbody radiation", "special relativity time dilation",
        "superconducting flux quantization", "chaotic pendulum motion", "nuclear fusion confinement",
        "Doppler shifts in astronomy", "surface tension", "conservation of angular momentum",
        "plasma instabilities", "photoelectric effect", "acoustic resonance",
        "cosmic microwave background", "semiconductor band gaps", "Brownian motion",
        "magnetic hysteresis", "optical diffraction", "tidal forces",
        "viscous fluid flow", "radioactive decay chains", "laser population inversion",
        "phonons in solids", "general relativity curvature", "electric field shielding",
        "ballistic projectile motion", "quantum entanglement", "heat conduction",
        "cyclotron motion", "fluid turbulence", "dark matter evidence",
        "piezoelectric effects", "stellar nucleosynthesis", "capillary action",
        "Lagrangian mechanics", "X ray scattering", "rotational inertia",
        "thermoelectric effects", "harmonic oscillator energy", "magnetohydrodynamics",
        "polarization of light", "vacuum fluctuations", "shock wave propagation",
        "orbital resonance", "electrostatic potential energy",
    ),
    "psychology": (
        "working memory capacity", "classical conditioning", "attachment styles",
        "cognitive dissonance", "confirmation bias", "intrinsic motivation",
        "social identity formation", "learned helplessness", "child language development",
        "group conformity", "emotional regulation", "the placebo effect",
        "decision fatigue", "personality trait measurement", "bystander behavior",
        "sleep and memory consolidation", "developmental object permanence", "stereotype threat",
        "operant reinforcement schedules", "grief coping processes", "visual attention",
        "self efficacy beliefs", "interpersonal attribution", "moral development stages",
        "habit formation", "psychological resilience", "false memory formation",
        "procrastination behavior", "empathy development", "risk perception",
        "language framing effects", "parenting style outcomes", "implicit attitudes",
        "burnout symptoms", "peer influence in adolescence", "goal setting theory",
        "facial emotion recognition", "rumination and mood", "creativity assessment",
        "conflict resolution styles", "cognitive load", "self determination theory",
        "collective memory", "psychological reactance", "attention deficit assessment",
        "post traumatic growth", "consumer decision psychology", "loneliness and social connection",
        "metacognitive monitoring", "therapy therapeutic alliance",
    ),
}

TEMPLATES = (
    "Can you explain {topic} in plain language?",
    "What are the main ideas behind {topic}?",
    "I need a practical overview of {topic}.",
    "What should a beginner understand about {topic}?",
    "How does {topic} work, and why does it matter?",
    "Help me understand the key issues in {topic}.",
    "Could you walk me through {topic}?",
    "What are common misconceptions about {topic}?",
    "Give me a concise introduction to {topic}.",
    "How would you describe {topic} to a newcomer?",
)


def normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--near-duplicate-threshold", type=float, default=0.90)
    args = parser.parse_args()

    if tuple(TOPICS) != LABELS:
        raise RuntimeError("curated topic order must match the published label contract")
    if any(len(topics) != 50 for topics in TOPICS.values()):
        raise RuntimeError("final test requires exactly 50 curated topics per class")
    all_topics = [normalized_text(topic) for topics in TOPICS.values() for topic in topics]
    if len(all_topics) != len(set(all_topics)):
        raise RuntimeError("curated topics must be unique across all classes")

    reference = list(read_jsonl(args.reference_manifest))
    reference_keys = {row["normalized_sha256"] for row in reference}
    reference_text = [normalized_text(row["prompt"]) for row in reference]
    inverted: dict[str, set[int]] = defaultdict(set)
    for index, text in enumerate(reference_text):
        for token in set(text.split()):
            if len(token) >= 4:
                inverted[token].add(index)

    rows, near_pairs = [], []
    for label in LABELS:
        for topic_index, topic in enumerate(TOPICS[label]):
            for form_index, template_index in enumerate((2 * topic_index % 10, (2 * topic_index + 3) % 10)):
                prompt = TEMPLATES[template_index].format(topic=topic)
                key = normalized_prompt_key(prompt)
                if key in reference_keys:
                    raise RuntimeError(f"final prompt exactly overlaps teacher-source data: {prompt!r}")
                normalized = normalized_text(prompt)
                topic_tokens = {token for token in normalized_text(topic).split() if len(token) >= 4}
                candidates = set().union(*(inverted[token] for token in topic_tokens)) if topic_tokens else set()
                best_ratio, best_index = 0.0, None
                for candidate in candidates:
                    ratio = difflib.SequenceMatcher(None, normalized, reference_text[candidate]).ratio()
                    if ratio > best_ratio:
                        best_ratio, best_index = ratio, candidate
                if best_ratio >= args.near_duplicate_threshold:
                    near_pairs.append({
                        "prompt": prompt,
                        "reference_prompt": reference[best_index]["prompt"],
                        "similarity": best_ratio,
                    })
                rows.append({
                    "prompt": prompt,
                    "source_dataset": "xsr-independent-curated-routing-v1",
                    "source_revision": "1",
                    "source_split": "sealed_test",
                    "source_index": len(rows),
                    "topic_cluster_id": f"{label}:{topic_index}",
                    "prompt_form": form_index,
                    "ground_truth_class": label,
                    "student_split": "final_test",
                    "normalized_sha256": key,
                })

    keys = [row["normalized_sha256"] for row in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError("final test prompts are not unique")
    if near_pairs:
        raise RuntimeError(
            f"{len(near_pairs)} final prompts exceed near-duplicate threshold; inspect and revise"
        )
    write_jsonl(args.output, rows)
    counts = Counter(row["ground_truth_class"] for row in rows)
    summary = {
        "dataset": "xsr-independent-curated-routing-v1",
        "rows": len(rows),
        "topic_clusters": len(set(row["topic_cluster_id"] for row in rows)),
        "prompts_per_topic": 2,
        "rows_per_class": {label: counts[label] for label in LABELS},
        "topics_per_class": {label: len(TOPICS[label]) for label in LABELS},
        "reference_manifest_sha256": hashlib.sha256(args.reference_manifest.read_bytes()).hexdigest(),
        "final_manifest_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "exact_normalized_prompt_overlaps": 0,
        "near_duplicate_threshold": args.near_duplicate_threshold,
        "near_duplicates_at_or_above_threshold": 0,
        "independence_scope": (
            "Exact and >=threshold textual overlap checked against the complete local MMLU-Pro "
            "plus category-classifier-supplement manifest. This does not prove semantic novelty "
            "against undocumented teacher pretraining corpora."
        ),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
