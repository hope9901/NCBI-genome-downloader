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
import threading
import config

logger = logging.getLogger("fungi_pipeline")

def sanitize_name(text):
    """
    Sanitizes taxonomic names and strings to be safe for filenames.
    Replaces spaces, parenthesis, slashes, commas, colons, and dots with underscores.
    Collapses multiple underscores into one.
    """
    if not text:
        return ""
    text = text.strip()
    sanitized = re.sub(r'[\s\(\)\/\\,\.:]+', '_', text)
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized.strip('_')

def calculate_md5(file_path):
    """Calculates the MD5 checksum of a file."""
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
        self.api_key = config.API_KEY
        self.tax_lock = threading.Lock()  # Lock to serialize NCBI Taxonomy API calls among threads

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

    def fetch_genome_metadata(self):
        """
        Executes 'datasets summary genome taxon <TARGET_TAXON> --as-json-lines'
        to retrieve all fungal/plant/bacterial genomes.
        Robustly parses both CamelCase and snake_case JSON schemas outputted by NCBI.
        """
        if not self.check_cli_installed():
            raise RuntimeError("NCBI Datasets CLI is not installed or not in PATH.")

        taxon = config.TARGET_TAXON
        cmd = [self.datasets_bin, "summary", "genome", "taxon", taxon, "--as-json-lines"]
        if self.api_key:
            cmd.extend(["--api-key", self.api_key])

        logger.info(f"Fetching {taxon} genome metadata from NCBI...")
        print(f"Fetching {taxon} genome metadata from NCBI (Taxon: {taxon}, ALL genomes)...")

        try:
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

                if "reports" in record:
                    reports = record.get("reports", [])
                elif "accession" in record:
                    reports = [record]
                else:
                    reports = []

                for report in reports:
                    accession = report.get("accession")
                    if not accession:
                        continue
                    
                    # --- Robust Hybrid Schema Parsing (CamelCase + snake_case) ---
                    assembly_info = report.get("assemblyInfo") or report.get("assembly_info") or {}
                    organism = report.get("organism") or {}
                    
                    org_name = organism.get("organismName") or organism.get("organism_name") or ""
                    tax_id = organism.get("taxId") or organism.get("tax_id")
                    
                    strain = ""
                    infra_names = organism.get("infraspecificNames") or organism.get("infraspecific_names") or {}
                    if isinstance(infra_names, dict):
                        strain = infra_names.get("strain") or ""
                    
                    assembly_level = assembly_info.get("assemblyLevel") or assembly_info.get("assembly_level") or "unspecified"
                    
                    paired_accession = assembly_info.get("pairedAssemblyAccession") or assembly_info.get("paired_assembly_accession")
                    if paired_accession:
                        paired_accession = paired_accession.strip()

                    has_annotation = 1 if report.get("annotation_info") or report.get("annotationInfo") else 0
                    
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
                        "has_annotation": has_annotation,
                        "paired_accession": paired_accession,
                        "kingdom": None,
                        "phylum": None,
                        "class": None,
                        "order": None,
                        "family": None,
                        "genus": None
                    })
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON line: {e}")
                continue

        logger.info(f"Retrieved {len(metadata_list)} {taxon} genome metadata records.")
        return metadata_list

    def fetch_taxonomy_lineage(self, tax_id):
        """Retrieves 6 core taxonomic lineage ranks. Uses Double-Checked Locking to serialize API calls."""
        if not tax_id:
            return {}
        
        # Check cache outside lock for fast read
        if tax_id in self.taxonomy_cache:
            return self.taxonomy_cache[tax_id]

        if not self.check_cli_installed():
            return {}

        # Double-Checked Locking Pattern: Serialize API requests
        with self.tax_lock:
            # Recheck cache after acquiring lock
            if tax_id in self.taxonomy_cache:
                return self.taxonomy_cache[tax_id]

            time.sleep(self.api_delay)

            cmd = [self.datasets_bin, "summary", "taxonomy", "taxon", str(tax_id), "--as-json-lines"]
            if self.api_key:
                cmd.extend(["--api-key", self.api_key])

            logger.debug(f"Querying taxonomy for TaxID {tax_id}...")

            try:
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
                lines = result.stdout.strip().split("\n")
                if not lines or not lines[0].strip():
                    return {}
                
                tax_record = json.loads(lines[0])
                reports = tax_record.get("reports", [])
                if not reports:
                    if "taxonomy" in tax_record:
                        reports = [tax_record]
                    else:
                        return {}
                
                taxonomy = reports[0].get("taxonomy", {})
                classification = {
                    "kingdom": None,
                    "phylum": None,
                    "class": None,
                    "order": None,
                    "family": None,
                    "genus": None
                }
                
                # Check top-level superkingdom/kingdom
                classification["kingdom"] = taxonomy.get("kingdom") or taxonomy.get("superkingdom")
                
                lineage = taxonomy.get("lineage", [])
                for node in lineage:
                    rank = node.get("rank")
                    name = node.get("name")
                    if rank in ("superkingdom", "kingdom"):
                        classification["kingdom"] = name
                    elif rank == "phylum":
                        classification["phylum"] = name
                    elif rank == "class":
                        classification["class"] = name
                    elif rank == "order":
                        classification["order"] = name
                    elif rank == "family":
                        classification["family"] = name
                    elif rank == "genus":
                        classification["genus"] = name
                
                self.taxonomy_cache[tax_id] = classification
                logger.debug(f"TaxID {tax_id} 6-rank lineage: {classification}")
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
        if self.api_key:
            cmd.extend(["--api-key", self.api_key])

        logger.info(f"Downloading {accession} to {zip_path}...")
        
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
        """Parses md5sum.txt inside the extracted directory and validates MD5 hashes."""
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
            
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                logger.warning(f"Malformed md5sum line: {line}")
                continue
                
            expected_md5 = parts[0].strip().lower()
            relative_file_path = parts[1].strip()
            
            target_file_path = os.path.join(temp_extract_dir, relative_file_path)
            
            if not os.path.exists(target_file_path):
                logger.debug(f"File skipped in verification (not extracted): {relative_file_path}")
                continue

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
        Extracts downloaded zip, verifies MD5 checksums, moves files to a structured
        'ncbi' subfolder inside the final_dest_dir, and returns file presence flags.
        """
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
        os.makedirs(temp_extract_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
        except zipfile.BadZipFile as e:
            raise RuntimeError(f"Downloaded file is a bad zip package: {e}")

        # MD5 Verification Step
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

        # NCBI original files are structured under 'ncbi' subfolder
        ncbi_final_dir = os.path.join(final_dest_dir, "ncbi")
        os.makedirs(ncbi_final_dir, exist_ok=True)
        
        # Keep an empty 'custom' directory ready for future pipeline re-annotations
        custom_final_dir = os.path.join(final_dest_dir, "custom")
        os.makedirs(custom_final_dir, exist_ok=True)

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
                dest_path = os.path.join(ncbi_final_dir, dest_filename)
                
                shutil.move(source_path, dest_path)
                results[f"has_{file_type}"] = 1
                logger.debug(f"Moved {file_type} file to: {dest_path}")

        # Cleanup extracted temp files
        shutil.rmtree(temp_extract_dir)
        
        return results

    def create_symlinks(self, folder_name, accession, final_dest_dir, type_dirs):
        """Creates symbolic links for quick lookup under fna/ncbi/, gff/ncbi/ directories."""
        # Source files are located under 'ncbi' subdirectory of final_dest_dir
        ncbi_src_dir = os.path.join(final_dest_dir, "ncbi")
        
        file_mapping = {
            "fna": (f"{folder_name}_genomic.fna", "fna"),
            "gff": (f"{folder_name}_genomic.gff", "gff"),
            "cds": (f"{folder_name}_cds.fna", "cds"),
            "faa": (f"{folder_name}_protein.faa", "faa")
        }

        for file_key, (src_name, dir_key) in file_mapping.items():
            src_file_path = os.path.join(ncbi_src_dir, src_name)
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

    def create_taxonomy_symlink(self, folder_name, kingdom, phylum, klass, order, family, genus, final_dest_dir, taxonomy_base_dir):
        """
        Creates hierarchical 6-level taxonomic directory layout (Kingdom ➔ Phylum ➔ Class ➔ Order ➔ Family ➔ Genus)
        and symlinks the downloaded genome directory for browseability.
        If too many core taxonomic definitions are missing (or both Kingdom and Phylum are empty),
        routes the link flatly under taxonomy/Unclassified/ to prevent messy, deep Unknown paths.
        """
        ranks = [kingdom, phylum, klass, order, family, genus]
        missing_count = sum(1 for r in ranks if not r)

        # Smart Unclassified Router: If we lack basic Kingdom & Phylum, or have >= 4 missing standard ranks
        if (not kingdom and not phylum) or missing_count >= 4:
            target_dir = os.path.join(taxonomy_base_dir, "Unclassified")
            os.makedirs(target_dir, exist_ok=True)
            link_path = os.path.join(target_dir, folder_name)
        else:
            # Standard 6-level taxonomy tree with defensive Unknown fallbacks
            king_san = sanitize_name(kingdom or "Unknown_Kingdom")
            phyl_san = sanitize_name(phylum or "Unknown_Phylum")
            clas_san = sanitize_name(klass or "Unknown_Class")
            orde_san = sanitize_name(order or "Unknown_Order")
            fami_san = sanitize_name(family or "Unknown_Family")
            genu_san = sanitize_name(genus or "Unknown_Genus")
            
            target_dir = os.path.join(taxonomy_base_dir, king_san, phyl_san, clas_san, orde_san, fami_san, genu_san)
            os.makedirs(target_dir, exist_ok=True)
            link_path = os.path.join(target_dir, folder_name)
        
        try:
            rel_target_path = os.path.relpath(final_dest_dir, target_dir)
        except ValueError:
            rel_target_path = final_dest_dir

        if os.path.exists(link_path) or os.path.islink(link_path):
            try:
                if os.path.islink(link_path) or os.path.isfile(link_path):
                    os.remove(link_path)
                else:
                    shutil.rmtree(link_path)
            except OSError as e:
                logger.warning(f"Could not clean up existing taxonomy symlink at {link_path}: {e}")

        try:
            # Create a directory-level symbolic link pointing to the full genome directory
            if sys.platform.startswith("win"):
                os.symlink(rel_target_path, link_path, target_is_directory=True)
            else:
                os.symlink(rel_target_path, link_path)
            logger.debug(f"Created taxonomy symlink: {link_path} ➔ {rel_target_path}")
        except OSError as e:
            logger.warning(f"Failed to create taxonomy directory symlink at {link_path}: {e}")
