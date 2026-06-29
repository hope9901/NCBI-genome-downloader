import os
import json
import logging
import threading
from datetime import datetime

logger = logging.getLogger("fungi_pipeline")

class JsonDbManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lock = threading.Lock()
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
        Keeps download and annotation statuses intact for existing entries.
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
                        "paired_accession": item.get("paired_accession", existing.get("paired_accession")),
                    })
                    if "ncbi" not in existing:
                        existing["ncbi"] = {
                            "download_status": item.get("download_status", "pending"),
                            "downloaded_at": item.get("downloaded_at"),
                            "has_annotation": item.get("has_annotation", 0),
                            "has_fna": item.get("has_fna", 0),
                            "has_gff": item.get("has_gff", 0),
                            "has_cds": item.get("has_cds", 0),
                            "has_faa": item.get("has_faa", 0),
                            "error_log": item.get("error_log")
                        }
                    else:
                        existing["ncbi"]["has_annotation"] = item.get("has_annotation", existing["ncbi"].get("has_annotation", 0))

                    if "custom" not in existing:
                        existing["custom"] = {
                            "annotation_status": "pending",
                            "annotated_at": None,
                            "has_gff": 0,
                            "has_cds": 0,
                            "has_faa": 0,
                            "pipeline_version": None,
                            "error_log": None
                        }
                    updated_count += 1
                else:
                    data[accession] = {
                        "organism_name": item.get("organism_name"),
                        "strain": item.get("strain"),
                        "assembly_level": item.get("assembly_level"),
                        "folder_name": item.get("folder_name"),
                        "tax_id": item.get("tax_id"),
                        "paired_accession": item.get("paired_accession"),  # Set GCA/GCF partner
                        "phylum": None,
                        "class": None,
                        "order": None,
                        "family": None,
                        "genus": None,
                        "ncbi": {
                            "download_status": "pending",
                            "downloaded_at": None,
                            "has_annotation": item.get("has_annotation", 0),
                            "has_fna": 0,
                            "has_gff": 0,
                            "has_cds": 0,
                            "has_faa": 0,
                            "error_log": None
                        },
                        "custom": {
                            "annotation_status": "pending",
                            "annotated_at": None,
                            "has_gff": 0,
                            "has_cds": 0,
                            "has_faa": 0,
                            "pipeline_version": None,
                            "error_log": None
                        }
                    }
                    new_count += 1

            self._save_unlocked(data)
            logger.info(f"Database sync complete. New: {new_count}, Updated: {updated_count}")
            return new_count

    def update_ncbi_status(self, accession, status, has_fna=0, has_gff=0, has_cds=0, has_faa=0, error_log=None):
        """Update NCBI source download status. Thread-safe."""
        with self.lock:
            data = self._load_unlocked()
            if accession not in data:
                logger.warning(f"Attempted to update NCBI status for non-existent accession: {accession}")
                return False

            record = data[accession]
            if "ncbi" not in record:
                record["ncbi"] = {}

            ncbi = record["ncbi"]
            ncbi["download_status"] = status
            ncbi["has_fna"] = int(has_fna)
            ncbi["has_gff"] = int(has_gff)
            ncbi["has_cds"] = int(has_cds)
            ncbi["has_faa"] = int(has_faa)
            
            if status == "completed":
                ncbi["downloaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ncbi["error_log"] = None
            else:
                ncbi["downloaded_at"] = None
                ncbi["error_log"] = error_log

            self._save_unlocked(data)
            logger.debug(f"Updated NCBI status for {accession} to {status}")
            return True

    def update_custom_status(self, accession, status, has_gff=0, has_cds=0, has_faa=0, pipeline_version=None, error_log=None):
        """Update custom re-annotation status. Thread-safe."""
        with self.lock:
            data = self._load_unlocked()
            if accession not in data:
                logger.warning(f"Attempted to update custom annotation status for non-existent accession: {accession}")
                return False

            record = data[accession]
            if "custom" not in record:
                record["custom"] = {}

            custom = record["custom"]
            custom["annotation_status"] = status
            custom["has_gff"] = int(has_gff)
            custom["has_cds"] = int(has_cds)
            custom["has_faa"] = int(has_faa)
            custom["pipeline_version"] = pipeline_version
            
            if status == "completed":
                custom["annotated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                custom["error_log"] = None
            else:
                custom["annotated_at"] = None
                custom["error_log"] = error_log

            self._save_unlocked(data)
            logger.info(f"Updated Custom annotation status for {accession} to {status} (GFF:{has_gff})")
            return True

    def update_taxonomy_info(self, accession, phylum, klass, order, family, genus):
        """Updates taxonomic lineage fields for a specific accession. Thread-safe."""
        with self.lock:
            data = self._load_unlocked()
            if accession not in data:
                return False
            
            record = data[accession]
            record["phylum"] = phylum
            record["class"] = klass
            record["order"] = order
            record["family"] = family
            record["genus"] = genus
            
            self._save_unlocked(data)
            logger.debug(f"Updated taxonomy lineage for {accession}: Phylum={phylum}, Class={klass}")
            return True

    def get_pending_accessions(self):
        """Retrieve list of accessions needing downloading."""
        with self.lock:
            data = self._load_unlocked()
            pending = []
            for accession, info in data.items():
                ncbi = info.get("ncbi", {})
                if ncbi.get("download_status") in ("pending", "failed"):
                    pending.append((accession, info))
            return pending

    def get_pending_custom_annotations(self):
        """Retrieve list of successfully downloaded genomes that are pending custom re-annotation."""
        with self.lock:
            data = self._load_unlocked()
            pending = []
            for accession, info in data.items():
                ncbi = info.get("ncbi", {})
                custom = info.get("custom", {})
                if ncbi.get("download_status") == "completed" and ncbi.get("has_fna") == 1:
                    if custom.get("annotation_status") in ("pending", "failed"):
                        pending.append((accession, info))
            return pending
