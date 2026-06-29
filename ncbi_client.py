import os
import re
import shutil
import zipfile
import subprocess
import time
import json
import logging
import sys
import hashlib

logger = logging.getLogger("fungi_pipeline")

def sanitize_name(text):
    """
    Sanitizes taxonomic names and strings to be safe for filenames.
    Replaces spaces, parenthesis, slashes, commas, colons, and dots with underscores.
    Collapses multiple underscores into one.
    """
    if not text:
        return ""
    # Strip leading/trailing spaces
    text = text.strip()
    # Replace unsafe characters with underscores
    sanitized = re.sub(r'[\s\(\)\/\\,\.:]+', '_', text)
    # Collapse multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores
    return sanitized.strip('_')

def calculate_md5(file_path):
    """Calculates the MD5 checksum of a file in chunks to optimize memory."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except IOError as e:
        logger.error(f"Failed to read file for MD5 calculation at {file_path}: {e}")
        raise e

class NcbiDatasetsClient:
    def __init__(self, api_delay=1.0, max_retries=3):
        self.api_delay = api_delay
        self.max_retries = max_retries
        self.taxonomy_cache = {}
        self.datasets_bin = self._find_datasets_binary()

    def _find_datasets_binary(self):
        """Locates the 'datasets' CLI tool in system PATH."""
        binary = shutil.which("datasets")
        if not binary:
            logger.error("NCBI Datasets CLI binary ('datasets') not found in PATH.")
            print("[WARNING] 'datasets' binary not found. Please install the NCBI Datasets CLI tool.", file=sys.stderr)
        else:
            logger.info(f"Found NCBI Datasets binary at: {binary}")
        return binary

    def check_cli_installed(self):
        """Returns True if the datasets CLI is available, False otherwise."""
        if not self.datasets_bin:
            self.datasets_bin = self._find_datasets_binary()
        return self.datasets_bin is not None

    def fetch_fungal_metadata(self):
        """
        Executes 'datasets summary genome taxon 4751 --annotated --as-json-lines'
        to retrieve all annotated fungal genomes. Returns a parsed list of metadata dicts.
        """
        if not self.check_cli_installed():
            raise RuntimeError("NCBI Datasets CLI is not installed or not in PATH.")

        cmd = [self.datasets_bin, "summary", "genome", "taxon", "4751", "--annotated", "--as-json-lines"]
        logger.info("Fetching Fungi genome metadata from NCBI...")
        print("Fetching Fungi genome metadata from NCBI (Taxon 4751, annotated)...")

        try:
            # Execute command and capture output
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"NCBI metadata command failed: {e.stderr}")
            raise RuntimeError(f"NCBI Datasets CLI failed: {e.stderr}")

        metadata_list = []
        lines = result.stdout.strip().split("\n")
        
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if "error" in record:
                    logger.warning(f"Error record found in metadata summary: {record['error']}")
                    continue

                reports = record.get("reports", [])
                for report in reports:
                    accession = report.get("accession")
                    if not accession:
                        continue
                    
                    assembly_info = report.get("assemblyInfo", {})
                    organism = report.get("organism", {})
                    
                    org_name = organism.get("organismName", "")
                    tax_id = organism.get("taxId")
                    
                    strain = ""
                    infra_names = organism.get("infraspecificNames", {})
                    if isinstance(infra_names, dict):
                        strain = infra_names.get("strain", "")
                    
                    assembly_level = assembly_info.get("assemblyLevel", "unspecified")
                    
                    san_org = sanitize_name(org_name)
                    san_strain = sanitize_name(strain)
                    san_level = sanitize_name(assembly_level)
                    san_acc = accession.strip()
                    
                    if san_strain:
                        folder_name = f"{san_org}_{san_strain}_{san_acc}_{san_level}"
                    else:
                        folder_name = f"{san_org}_{san_acc}_{san_level}"
                        
                    folder_name = re.sub(r'_+', '_', folder_name)

                    metadata_list.append({
                        "accession": accession,
                        "organism_name": org_name,
                        "strain": strain,
                        "assembly_level": assembly_level,
                        "folder_name": folder_name,
                        "tax_id": tax_id,
                        "phylum": None,
                        "class": None,
                        "order": None,
                        "family": None,
                        "genus": None
                    })
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON line: {e}")
                continue

        logger.info(f"Retrieved {len(metadata_list)} fungal genome metadata records.")
        return metadata_list

    def fetch_taxonomy_lineage(self, tax_id):
        """Retrieves taxonomic lineage. Uses memory cache."""
        if not tax_id:
            return {}
        
        if tax_id in self.taxonomy_cache:
            return self.taxonomy_cache[tax_id]

        if not self.check_cli_installed():
            return {}

        time.sleep(self.api_delay)

        cmd = [self.datasets_bin, "summary", "taxonomy", "taxon", str(tax_id), "--as-json-lines"]
        logger.debug(f"Querying taxonomy for TaxID {tax_id}...")

        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            lines = result.stdout.strip().split("\n")
            if not lines or not lines[0].strip():
                return {}
            
            tax_record = json.loads(lines[0])
            reports = tax_record.get("reports", [])
            if not reports:
                return {}
            
            taxonomy = reports[0].get("taxonomy", {})
            classification = {}
            
            lineage = taxonomy.get("lineage", [])
            for node in lineage:
                rank = node.get("rank")
                name = node.get("name")
                if rank in ("phylum", "class", "order", "family", "genus"):
                    classification[rank] = name
            
            self.taxonomy_cache[tax_id] = classification
            logger.debug(f"TaxID {tax_id} lineage: {classification}")
            return classification
            
        except Exception as e:
            logger.warning(f"Failed to fetch taxonomy for TaxID {tax_id}: {e}")
            return {}

    def download_genome_package(self, accession, tmp_dir):
        """Downloads a genome data package for a specific accession."""
        if not self.check_cli_installed():
            raise RuntimeError("NCBI Datasets CLI is not installed.")

        zip_filename = f"{accession}.zip"
        zip_path = os.path.join(tmp_dir, zip_filename)

        os.makedirs(tmp_dir, exist_ok=True)

        cmd = [
            self.datasets_bin, "download", "genome", "accession", accession,
            "--include", "genome,gff3,rna,cds,protein",
            "--filename", zip_path
        ]
        
        logger.info(f"Downloading {accession} to {zip_path}...")
        
        # execution of the single subcommand. Retry is managed at main.py loop for MD5 verification as well.
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Download command execution failed for {accession}: {e.stderr.strip()}")
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
            raise RuntimeError(f"NCBI Download command failed: {e.stderr.strip()}")
        
        return zip_path

    def verify_md5sums(self, temp_extract_dir):
        """
        Parses md5sum.txt inside the extracted directory and validates the MD5 hash
        of each file. Raises ValueError if checksum fails or files are corrupted.
        """
        md5_file_path = os.path.join(temp_extract_dir, "md5sum.txt")
        if not os.path.exists(md5_file_path):
            logger.warning(f"md5sum.txt not found in extracted directory {temp_extract_dir}. Skipping checksum validation.")
            return True

        logger.info(f"Verifying MD5 checksums using {md5_file_path}...")
        
        try:
            with open(md5_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except IOError as e:
            raise RuntimeError(f"Failed to read md5sum.txt: {e}")

        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Split by whitespace (MD5 is 32 chars, then space(s) and filepath)
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                logger.warning(f"Malformed md5sum line: {line}")
                continue
                
            expected_md5 = parts[0].strip().lower()
            relative_file_path = parts[1].strip()
            
            # Form absolute path
            target_file_path = os.path.join(temp_extract_dir, relative_file_path)
            
            # NCBI datasets package includes md5sum.txt for all files in the base package,
            # but since we filter download with '--include', some files might not be extracted.
            # We ONLY verify files that were actually extracted.
            if not os.path.exists(target_file_path):
                logger.debug(f"File skipped in verification (not extracted/included): {relative_file_path}")
                continue

            # Calculate actual MD5
            actual_md5 = calculate_md5(target_file_path).lower()
            
            if actual_md5 != expected_md5:
                logger.error(f"MD5 checksum MISMATCH for {relative_file_path}!")
                logger.error(f"Expected: {expected_md5}")
                logger.error(f"Actual:   {actual_md5}")
                raise ValueError(f"MD5 checksum verification failed for file: {relative_file_path}")
            
            logger.debug(f"MD5 verified successfully: {relative_file_path}")

        logger.info("All extracted files passed MD5 checksum validation.")
        return True

    def extract_and_organize(self, accession, zip_path, temp_extract_dir, final_dest_dir, folder_name):
        """
        Extracts downloaded zip, verifies MD5 checksums, detects genomic files,
        moves them to the final structured destination, and returns the presence of files.
        """
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
        os.makedirs(temp_extract_dir, exist_ok=True)

        # Unzip
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
        except zipfile.BadZipFile as e:
            raise RuntimeError(f"Downloaded file is a bad zip package: {e}")

        # --- MD5 Verification Step ---
        # If verification fails, it raises ValueError, causing caller (main.py) to delete and retry.
        self.verify_md5sums(temp_extract_dir)

        # Locate files in the extracted directory structure
        ncbi_data_path = os.path.join(temp_extract_dir, "ncbi_dataset", "data", accession)
        search_root = ncbi_data_path if os.path.exists(ncbi_data_path) else temp_extract_dir

        found_files = {
            "fna": None,
            "gff": None,
            "cds": None,
            "faa": None
        }

        # Walk through the directories to search files
        for root, dirs, files in os.walk(search_root):
            for file in files:
                file_lower = file.lower()
                full_path = os.path.join(root, file)

                if file_lower.endswith(".gff") or file_lower.endswith(".gff3"):
                    found_files["gff"] = full_path
                elif file_lower.endswith(".faa") or (file_lower.endswith(".fasta") and "protein" in file_lower):
                    found_files["faa"] = full_path
                elif "cds" in file_lower and (file_lower.endswith(".fna") or file_lower.endswith(".fasta")):
                    found_files["cds"] = full_path
                elif (file_lower.endswith(".fna") or file_lower.endswith(".fasta")) and "cds" not in file_lower and "rna" not in file_lower:
                    found_files["fna"] = full_path

        if not found_files["faa"]:
            for root, dirs, files in os.walk(search_root):
                faa_files = [os.path.join(root, f) for f in files if f.lower().endswith(".faa")]
                if faa_files:
                    found_files["faa"] = faa_files[0]
                    break

        os.makedirs(final_dest_dir, exist_ok=True)

        results = {
            "has_fna": 0,
            "has_gff": 0,
            "has_cds": 0,
            "has_faa": 0
        }

        target_names = {
            "fna": f"{folder_name}_genomic.fna",
            "gff": f"{folder_name}_genomic.gff",
            "cds": f"{folder_name}_cds.fna",
            "faa": f"{folder_name}_protein.faa"
        }

        for file_type, source_path in found_files.items():
            if source_path and os.path.exists(source_path):
                dest_filename = target_names[file_type]
                dest_path = os.path.join(final_dest_dir, dest_filename)
                
                shutil.move(source_path, dest_path)
                results[f"has_{file_type}"] = 1
                logger.debug(f"Moved {file_type} file to: {dest_path}")

        # Cleanup extracted temp files
        shutil.rmtree(temp_extract_dir)
        
        return results

    def create_symlinks(self, folder_name, accession, final_dest_dir, type_dirs):
        """Creates symbolic links for quick lookup."""
        file_mapping = {
            "fna": (f"{folder_name}_genomic.fna", "fna"),
            "gff": (f"{folder_name}_genomic.gff", "gff"),
            "cds": (f"{folder_name}_cds.fna", "cds"),
            "faa": (f"{folder_name}_protein.faa", "faa")
        }

        for file_key, (src_name, dir_key) in file_mapping.items():
            src_file_path = os.path.join(final_dest_dir, src_name)
            if not os.path.exists(src_file_path):
                continue

            target_dir = type_dirs.get(dir_key)
            if not target_dir:
                continue

            link_name = f"{accession}.{file_key}"
            link_path = os.path.join(target_dir, link_name)

            try:
                rel_target_path = os.path.relpath(src_file_path, target_dir)
            except ValueError:
                rel_target_path = src_file_path

            if os.path.exists(link_path) or os.path.islink(link_path):
                try:
                    os.remove(link_path)
                except OSError as e:
                    logger.warning(f"Could not remove existing file/link at {link_path}: {e}")

            try:
                os.symlink(rel_target_path, link_path)
                logger.debug(f"Created symlink: {link_path} ➔ {rel_target_path}")
            except OSError as e:
                logger.warning(f"Failed to create symlink at {link_path}: {e}")
                if sys.platform.startswith("win"):
                    try:
                        shutil.copy(src_file_path, link_path)
                        logger.debug(f"Fallback copied file to: {link_path}")
                    except Exception as copy_err:
                        logger.error(f"Fallback copy failed: {copy_err}")
