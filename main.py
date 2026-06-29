import os
import sys
import logging
import shutil
import concurrent.futures
from datetime import datetime
import config
from db_manager import JsonDbManager
from ncbi_client import NcbiDatasetsClient

# Initialize Logging
def setup_logging(log_path):
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("fungi_pipeline")
    logger.setLevel(logging.DEBUG)

    # File Handler
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_logging(config.LOG_PATH)

def generate_overview_report(db_manager, overview_path):
    """
    Reads the database and generates a structured overview text report
    with taxonomic lineage summaries and a detailed download status table.
    """
    records = db_manager.get_all_records()
    
    total_count = len(records)
    completed_count = 0
    failed_count = 0
    pending_count = 0

    # Hierarchical taxonomic summary structure: Phylum -> Class -> [completed, total]
    tax_summary = {}

    for acc, info in records.items():
        status = info.get("download_status")
        if status == "completed":
            completed_count += 1
        elif status == "failed":
            failed_count += 1
        else:
            pending_count += 1

        phylum = info.get("phylum") or "Unknown_Phylum"
        klass = info.get("class") or "Unknown_Class"

        if phylum not in tax_summary:
            tax_summary[phylum] = {"total": 0, "completed": 0, "classes": {}}
        
        tax_summary[phylum]["total"] += 1
        if status == "completed":
            tax_summary[phylum]["completed"] += 1

        classes_dict = tax_summary[phylum]["classes"]
        if klass not in classes_dict:
            classes_dict[klass] = {"total": 0, "completed": 0}
        
        classes_dict[klass]["total"] += 1
        if status == "completed":
            classes_dict[klass]["completed"] += 1

    # Format Overview Report
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("======================================================================")
    lines.append(f"Fungi Genome Download Overview (Updated: {now_str})")
    lines.append("======================================================================\n")

    lines.append("[Total Download Statistics]")
    lines.append(f"  - Total Fungal Genomes Registered : {total_count}")
    lines.append(f"  - Completed Downloads            : {completed_count}")
    lines.append(f"  - Failed Downloads               : {failed_count}")
    lines.append(f"  - Pending/Queue Downloads        : {pending_count}\n")

    lines.append("[Taxonomy Summary (Phylum ➔ Class) [Completed / Total]]")
    for phylum, p_stats in sorted(tax_summary.items()):
        lines.append(f"  - {phylum} [{p_stats['completed']} / {p_stats['total']}]")
        for klass, c_stats in sorted(p_stats["classes"].items()):
            lines.append(f"    * {klass} [{c_stats['completed']} / {c_stats['total']}]")
    lines.append("\n")

    lines.append("[Detailed Download Status Table]")
    header = f"{'Accession':<18} | {'Organism Name':<30} | {'Phylum':<15} | {'Class':<15} | FNA | GFF | CDS | FAA | {'Status':<10}"
    lines.append(header)
    lines.append("-" * len(header))

    for acc, info in sorted(records.items()):
        org_name = info.get("organism_name", "")
        if len(org_name) > 28:
            org_name = org_name[:25] + "..."
        
        phylum = info.get("phylum") or "Unknown"
        if len(phylum) > 13: phylum = phylum[:12] + "."
            
        klass = info.get("class") or "Unknown"
        if len(klass) > 13: klass = klass[:12] + "."

        fna = "Y" if info.get("has_fna") else "N"
        gff = "Y" if info.get("has_gff") else "N"
        cds = "Y" if info.get("has_cds") else "N"
        faa = "Y" if info.get("has_faa") else "N"
        status = info.get("download_status", "pending")

        row = f"{acc:<18} | {org_name:<30} | {phylum:<15} | {klass:<15} |  {fna}  |  {gff}  |  {cds}  |  {faa}  | {status:<10}"
        lines.append(row)

    report_content = "\n".join(lines)
    
    # Save report
    try:
        with open(overview_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Generated download overview report at {overview_path}")
    except Exception as e:
        logger.error(f"Failed to write overview report: {e}")

def process_single_genome(idx, total_count, accession, info, db_manager, ncbi_client, type_dirs):
    """
    Core download worker logic: Downloads, extracts, validates MD5, reorganizes files, 
    creates symbolic links, and updates JSON DB. Run concurrently in ThreadPoolExecutor.
    """
    folder_name = info.get("folder_name")
    final_dest_dir = os.path.join(config.ALL_GENOMES_DIR, folder_name)
    temp_extract_dir = os.path.join(config.TMP_DIR, f"{accession}_extracted")

    logger.info(f"Processing ({idx}/{total_count}): {accession} -> {folder_name}")
    print(f"[{idx}/{total_count}] Starting download: {accession} ({info.get('organism_name')})...")

    zip_path = None
    try:
        # Pre-clean leftover directories from previous failed attempts
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
        if os.path.exists(final_dest_dir):
            shutil.rmtree(final_dest_dir)

        # 1. Download zip package
        zip_path = ncbi_client.download_genome_package(accession, config.TMP_DIR)
        
        # 2. Extract and organize files (Includes MD5 Checksum Verification)
        file_presence = ncbi_client.extract_and_organize(
            accession, zip_path, temp_extract_dir, final_dest_dir, folder_name
        )

        # 3. Create symlinks for existing files
        ncbi_client.create_symlinks(folder_name, accession, final_dest_dir, type_dirs)

        # 4. Update Database (Thread-safe)
        db_manager.update_download_status(
            accession, "completed",
            has_fna=file_presence["has_fna"],
            has_gff=file_presence["has_gff"],
            has_cds=file_presence["has_cds"],
            has_faa=file_presence["has_faa"]
        )
        logger.info(f"Successfully processed {accession}")
        print(f"[{idx}/{total_count}] Successfully downloaded and verified: {accession}")
        return True, accession, None

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed pipeline operation for {accession}: {error_msg}")
        db_manager.update_download_status(accession, "failed", error_log=error_msg)
        
        # Delete any partially downloaded/extracted files on failure to ensure clean slate
        if os.path.exists(final_dest_dir):
            try:
                shutil.rmtree(final_dest_dir)
            except OSError:
                pass
        print(f"[{idx}/{total_count}] Failed download: {accession}. Error: {error_msg}")
        return False, accession, error_msg
    finally:
        # Clean up zip and temp extract dir
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        if os.path.exists(temp_extract_dir):
            try:
                shutil.rmtree(temp_extract_dir)
            except OSError:
                pass

def run_pipeline():
    logger.info("Starting Fungi Genome Auto-Download Pipeline...")
    config.init_directories()

    # Instantiate managers
    db_manager = JsonDbManager(config.DB_PATH)
    ncbi_client = NcbiDatasetsClient(api_delay=config.API_DELAY, max_retries=config.MAX_RETRIES)

    if not ncbi_client.check_cli_installed():
        logger.critical("Pipeline aborted. 'datasets' CLI is missing.")
        print("[ERROR] NCBI Datasets CLI tool ('datasets') is not installed or not in PATH.", file=sys.stderr)
        return

    # ======================================================================
    # Phase 1: Metadata Sync & Taxonomy Lineage Collection
    # ======================================================================
    try:
        metadata_list = ncbi_client.fetch_fungal_metadata()
    except Exception as e:
        logger.critical(f"Failed to synchronize metadata from NCBI: {e}")
        return

    logger.info("Resolving taxonomic lineages (Phylum/Class/Order...)")
    print("Resolving taxonomic lineages for retrieved genomes...")
    
    unique_tax_ids = list(set(item.get("tax_id") for item in metadata_list if item.get("tax_id")))
    logger.info(f"Identified {len(unique_tax_ids)} unique TaxIDs to resolve.")

    tax_info_map = {}
    for idx, tax_id in enumerate(unique_tax_ids, 1):
        print(f"Resolving taxonomy {idx}/{len(unique_tax_ids)} (ID: {tax_id})...", end="\r")
        lineage = ncbi_client.fetch_taxonomy_lineage(tax_id)
        tax_info_map[tax_id] = lineage
    print()

    # Map taxonomy info back to metadata list
    for item in metadata_list:
        tax_id = item.get("tax_id")
        if tax_id and tax_id in tax_info_map:
            lineage = tax_info_map[tax_id]
            item["phylum"] = lineage.get("phylum")
            item["class"] = lineage.get("class")
            item["order"] = lineage.get("order")
            item["family"] = lineage.get("family")
            item["genus"] = lineage.get("genus")

    new_records_count = db_manager.upsert_genomes(metadata_list)
    print(f"Synchronized metadata. Added {new_records_count} new genomes.")

    # ======================================================================
    # Phase 2: Concurrent Multi-Threaded Download & Structuring
    # ======================================================================
    pending_items = db_manager.get_pending_accessions()
    logger.info(f"Found {len(pending_items)} accessions pending download. Using {config.PARALLEL_WORKERS} parallel workers.")
    print(f"Found {len(pending_items)} accessions to download. Running with {config.PARALLEL_WORKERS} parallel threads...")

    if not pending_items:
        logger.info("No new genomes to download. Pipeline completed successfully.")
        generate_overview_report(db_manager, config.OVERVIEW_PATH)
        return

    type_dirs = {
        "fna": config.FNA_DIR,
        "gff": config.GFF_DIR,
        "cds": config.CDS_DIR,
        "faa": config.FAA_DIR
    }

    success_count = 0
    failure_count = 0
    total_items = len(pending_items)

    # Execute download workers in a thread pool for concurrency
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.PARALLEL_WORKERS) as executor:
        # Submit all tasks
        futures = {
            executor.submit(
                process_single_genome, idx, total_items, accession, info, db_manager, ncbi_client, type_dirs
            ): accession 
            for idx, (accession, info) in enumerate(pending_items, 1)
        }

        # Monitor progress as futures complete
        for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            accession = futures[fut]
            try:
                success, acc, err = fut.result()
                if success:
                    success_count += 1
                else:
                    failure_count += 1
            except Exception as exc:
                logger.error(f"Thread execution generated an exception for {accession}: {exc}")
                failure_count += 1

            # Update the overview report periodically
            if idx % 10 == 0 or idx == total_items:
                generate_overview_report(db_manager, config.OVERVIEW_PATH)

    logger.info(f"Pipeline download phase complete. Success: {success_count}, Failures: {failure_count}")
    print(f"Pipeline complete. Successfully downloaded: {success_count}, Failed: {failure_count}")

    # Final overview report generation
    generate_overview_report(db_manager, config.OVERVIEW_PATH)

if __name__ == "__main__":
    run_pipeline()
