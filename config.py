import os

# --- Smart .env Loader (Using Python Standard Libraries) ---
def load_env_file():
    """
    Manually parses the .env file if it exists in the project directory,
    and sets them as environment variables without requiring external libraries.
    """
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip('"\'')
                        os.environ[key] = val
        except Exception as e:
            print(f"[WARNING] Failed to load .env file dynamically: {e}")

# Load .env variables first
load_env_file()

# --- Generalization Configs ---
TARGET_TAXON = os.getenv("NCBI_TARGET_TAXON", "Fungi")
API_KEY = os.getenv("NCBI_API_KEY")

# --- Dynamic PATH Resolution for datasets CLI ---
CUSTOM_DATASETS_PATH = os.getenv("NCBI_DATASETS_PATH")
if CUSTOM_DATASETS_PATH:
    os.environ["PATH"] = f"{CUSTOM_DATASETS_PATH}{os.pathsep}{os.environ.get('PATH', '')}"

# Base directory setup - Prepares fallback for legacy FUNGI_PROJECT_ROOT
DEFAULT_PROJECT_ROOT = os.path.expanduser(os.path.join("~", "ncbi_project"))
PROJECT_ROOT = os.getenv("NCBI_PROJECT_ROOT", os.getenv("FUNGI_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))

# Route data outputs to a taxon-specific subdirectory
BASE_DIR = os.path.join(PROJECT_ROOT, "data", TARGET_TAXON.lower())

# Subdirectories per Taxon
ALL_GENOMES_DIR = os.path.join(BASE_DIR, "all_genomes")
TMP_DIR = os.path.join(PROJECT_ROOT, "data", "tmp")

# Taxonomic hierarchical browsing folder
TAXONOMY_DIR = os.path.join(BASE_DIR, "taxonomy")

# Type-specific parent folders
FNA_DIR = os.path.join(BASE_DIR, "fna")
GFF_DIR = os.path.join(BASE_DIR, "gff")
CDS_DIR = os.path.join(BASE_DIR, "cds")
FAA_DIR = os.path.join(BASE_DIR, "faa")

# Type-specific NCBI folders
FNA_NCBI_DIR = os.path.join(FNA_DIR, "ncbi")
GFF_NCBI_DIR = os.path.join(GFF_DIR, "ncbi")
CDS_NCBI_DIR = os.path.join(CDS_DIR, "ncbi")
FAA_NCBI_DIR = os.path.join(FAA_DIR, "ncbi")

# Type-specific CUSTOM folders
FNA_CUSTOM_DIR = os.path.join(FNA_DIR, "custom")
GFF_CUSTOM_DIR = os.path.join(GFF_DIR, "custom")
CDS_CUSTOM_DIR = os.path.join(CDS_DIR, "custom")
FAA_CUSTOM_DIR = os.path.join(FAA_DIR, "custom")

# Database & Overview paths (Isolated per Taxon)
DB_PATH = os.path.join(BASE_DIR, "genomes_metadata.json")
OVERVIEW_PATH = os.path.join(BASE_DIR, "download_overview.txt")
LOG_PATH = os.path.join(PROJECT_ROOT, "pipeline.log")

try:
    API_DELAY = float(os.getenv("NCBI_API_DELAY", "0.5"))
except ValueError:
    print("[WARNING] Invalid NCBI_API_DELAY. Falling back to default: 0.5")
    API_DELAY = 0.5

try:
    MAX_RETRIES = int(os.getenv("NCBI_MAX_RETRIES", "3"))
except ValueError:
    print("[WARNING] Invalid NCBI_MAX_RETRIES. Falling back to default: 3")
    MAX_RETRIES = 3

try:
    PARALLEL_WORKERS = int(os.getenv("NCBI_PARALLEL_WORKERS", os.getenv("FUNGI_PARALLEL_WORKERS", "4")))
except ValueError:
    print("[WARNING] Invalid NCBI_PARALLEL_WORKERS. Falling back to default: 4")
    PARALLEL_WORKERS = 4

def init_directories():
    directories = [
        PROJECT_ROOT,
        BASE_DIR,
        ALL_GENOMES_DIR,
        TMP_DIR,
        TAXONOMY_DIR,
        FNA_DIR, GFF_DIR, CDS_DIR, FAA_DIR,
        FNA_NCBI_DIR, GFF_NCBI_DIR, CDS_NCBI_DIR, FAA_NCBI_DIR,
        FNA_CUSTOM_DIR, GFF_CUSTOM_DIR, CDS_CUSTOM_DIR, FAA_CUSTOM_DIR
    ]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"[INFO] Created directory: {directory}")

if __name__ == "__main__":
    init_directories()
    print("Project Root:", PROJECT_ROOT)
    print("Target Taxon:", TARGET_TAXON)
    print("Taxonomy Directory:", TAXONOMY_DIR)
