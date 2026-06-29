import os
import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger("fungi_pipeline")

class JsonDbManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lock = threading.Lock()  # Ensure thread-safety for concurrent writes
        self._init_db()

    def _init_db(self):
        """Ensure the JSON file exists. Create with empty dict if not."""
        with self.lock:
            if not os.path.exists(self.db_path):
                db_dir = os.path.dirname(self.db_path)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                self._save_unlocked({})
                logger.info(f"Initialized new JSON database at {self.db_path}")

    def _load_unlocked(self):
        """Loads database from disk (Internal use, caller must hold lock)."""
        if not os.path.exists(self.db_path):
            return {}
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load JSON database at {self.db_path}: {e}. Returning empty dictionary.")
            return {}

    def _save_unlocked(self, data):
        """Saves data atomically (Internal use, caller must hold lock)."""
        tmp_path = f"{self.db_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.db_path)
        except Exception as e:
            logger.error(f"Failed to save JSON database atomically: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise e

    def get_genome(self, accession):
        """Fetch metadata for a single accession. Thread-safe."""
        with self.lock:
            data = self._load_unlocked()
            return data.get(accession)

    def get_all_records(self):
        """Fetch all genome records in the database. Thread-safe."""
        with self.lock:
            return self._load_unlocked()

    def upsert_genomes(self, metadata_list):
        """
        Inserts new genomes from a list of metadata dictionaries.
        Thread-safe write operation.
        """
        with self.lock:
            data = self._load_unlocked()
            updated_count = 0
            new_count = 0

            for item in metadata_list:
                accession = item.get("accession")
                if not accession:
                    continue

                existing = data.get(accession)
                if existing:
                    existing.update({
                        "organism_name": item.get("organism_name", existing.get("organism_name")),
                        "strain": item.get("strain", existing.get("strain")),
                        "assembly_level": item.get("assembly_level", existing.get("assembly_level")),
                        "folder_name": item.get("folder_name", existing.get("folder_name")),
                        "tax_id": item.get("tax_id", existing.get("tax_id")),
                        "phylum": item.get("phylum", existing.get("phylum")),
                        "class": item.get("class", existing.get("class")),
                        "order": item.get("order", existing.get("order")),
                        "family": item.get("family", existing.get("family")),
                        "genus": item.get("genus", existing.get("genus")),
                    })
                    updated_count += 1
                else:
                    data[accession] = {
                        "organism_name": item.get("organism_name"),
                        "strain": item.get("strain"),
                        "assembly_level": item.get("assembly_level"),
                        "folder_name": item.get("folder_name"),
                        "tax_id": item.get("tax_id"),
                        "phylum": item.get("phylum"),
                        "class": item.get("class"),
                        "order": item.get("order"),
                        "family": item.get("family"),
                        "genus": item.get("genus"),
                        "download_status": "pending",
                        "has_fna": 0,
                        "has_gff": 0,
                        "has_cds": 0,
                        "has_faa": 0,
                        "downloaded_at": None,
                        "error_log": None
                    }
                    new_count += 1

            self._save_unlocked(data)
            logger.info(f"Database sync complete. New: {new_count}, Updated: {updated_count}")
            return new_count

    def update_download_status(self, accession, status, has_fna=0, has_gff=0, has_cds=0, has_faa=0, error_log=None):
        """Update download status and file presence metrics. Thread-safe."""
        with self.lock:
            data = self._load_unlocked()
            if accession not in data:
                logger.warning(f"Attempted to update status for non-existent accession: {accession}")
                return False

            record = data[accession]
            record["download_status"] = status
            record["has_fna"] = int(has_fna)
            record["has_gff"] = int(has_gff)
            record["has_cds"] = int(has_cds)
            record["has_faa"] = int(has_faa)
            
            if status == "completed":
                record["downloaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                record["error_log"] = None
            else:
                record["downloaded_at"] = None
                record["error_log"] = error_log

            self._save_unlocked(data)
            logger.debug(f"Updated status for {accession} to {status} (FNA:{has_fna}, GFF:{has_gff})")
            return True

    def get_pending_accessions(self):
        """Retrieve list of pending accessions. Thread-safe."""
        with self.lock:
            data = self._load_unlocked()
            pending = []
            for accession, info in data.items():
                if info.get("download_status") in ("pending", "failed"):
                    pending.append((accession, info))
            return pending
