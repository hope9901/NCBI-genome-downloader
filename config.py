import os

# Base directory setup
# expansion of "~" automatically resolves to user home in both Linux (~/fungi_project) and Windows.
DEFAULT_PROJECT_ROOT = os.path.expanduser(os.path.join("~", "fungi_project"))

# Read directories from environment variables or use smart defaults
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
API_DELAY = float(os.getenv("NCBI_API_DELAY", "1.0"))  # Seconds to wait between downloads to prevent IP bans
MAX_RETRIES = int(os.getenv("NCBI_MAX_RETRIES", "3"))  # Max download attempts for failed items
BATCH_SIZE = int(os.getenv("NCBI_BATCH_SIZE", "5"))    # Number of parallel download processes (if applicable)

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
