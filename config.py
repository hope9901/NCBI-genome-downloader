import os

# --- Smart .env Loader (Using Python Standard Libraries) ---
def load_env_file():
    """
    Manually parses the .env file if it exists in the project directory,
    and sets them as environment variables without requiring external libraries.
    """
    # Look for .env file in the directory of config.py
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip('"\'')  # Strip out quotes
                        os.environ[key] = val
        except Exception as e:
            print(f"[WARNING] Failed to load .env file dynamically: {e}")

# Load .env variables first
load_env_file()

# Base directory setup
DEFAULT_PROJECT_ROOT = os.path.expanduser(os.path.join("~", "fungi_project"))

# Read directories from environment variables (now populated from .env if present)
PROJECT_ROOT = os.getenv("FUNGI_PROJECT_ROOT", DEFAULT_PROJECT_ROOT)
BASE_DIR = os.path.join(PROJECT_ROOT, "data", "fungi")

# Subdirectories for organized files
ALL_GENOMES_DIR = os.path.join(BASE_DIR, "all_genomes")
TMP_DIR = os.path.join(PROJECT_ROOT, "data", "tmp")

# Type-specific folders
FNA_DIR = os.path.join(BASE_DIR, "fna")
GFF_DIR = os.path.join(BASE_DIR, "gff")
CDS_DIR = os.path.join(BASE_DIR, "cds")
FAA_DIR = os.path.join(BASE_DIR, "faa")

# Database & Overview paths
DB_PATH = os.path.join(BASE_DIR, "genomes_metadata.json")
OVERVIEW_PATH = os.path.join(BASE_DIR, "download_overview.txt")
LOG_PATH = os.path.join(PROJECT_ROOT, "pipeline.log")

# NCBI Datasets API Configuration
API_DELAY = float(os.getenv("NCBI_API_DELAY", "1.0"))
MAX_RETRIES = int(os.getenv("NCBI_MAX_RETRIES", "3"))
BATCH_SIZE = int(os.getenv("NCBI_BATCH_SIZE", "5"))

# Ensure all structural base directories exist
def init_directories():
    directories = [
        PROJECT_ROOT,
        BASE_DIR,
        ALL_GENOMES_DIR,
        TMP_DIR,
        FNA_DIR,
        GFF_DIR,
        CDS_DIR,
        FAA_DIR
    ]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            print(f"[INFO] Created directory: {directory}")

if __name__ == "__main__":
    init_directories()
    print("Project Root:", PROJECT_ROOT)
    print("DB Path:", DB_PATH)
