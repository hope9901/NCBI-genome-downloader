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

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

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
    summarizing both NCBI source files and Custom annotation states.
    Protects against massive text file blowup by truncating normal records to top 100,
    while always displaying all failed download records.
    Hierarchically summaries taxons from Kingdom ➔ Phylum ➔ Class.
    Also handles unclassified counts dynamically.
    """
    records = db_manager.get_all_records()
    
    total_count = len(records)
    ncbi_completed = 0
    ncbi_failed = 0
    ncbi_pending = 0
    ncbi_unannotated_total = 0
    unclassified_count = 0
    
    custom_completed = 0
    custom_failed = 0
    custom_pending = 0

    tax_summary = {}

    for acc, info in records.items():
        ncbi = info.get("ncbi", {})
        custom = info.get("custom", {})
        
        # NCBI statistics
        ncbi_status = ncbi.get("download_status", "pending")
        if ncbi_status == "completed":
            ncbi_completed += 1
        elif ncbi_status == "failed":
            ncbi_failed += 1
        else:
            ncbi_pending += 1

        if not ncbi.get("has_annotation"):
            ncbi_unannotated_total += 1

        # Custom pipeline statistics
        custom_status = custom.get("annotation_status", "pending")
        if custom_status == "completed":
            custom_completed += 1
        elif custom_status == "failed":
            custom_failed += 1
        else:
            custom_pending += 1

        # Resolve 6-level taxonomy definitions for unclassified check
        kingdom = info.get("kingdom")
        phylum = info.get("phylum")
        klass = info.get("class")
        order = info.get("order")
        family = info.get("family")
        genus = info.get("genus")

        ranks = [kingdom, phylum, klass, order, family, genus]
        missing_count = sum(1 for r in ranks if not r)

        # Smart Unclassified Check: Both Kingdom and Phylum are missing, or >= 4 ranks are missing
        if (not kingdom and not phylum) or missing_count >= 4:
            unclassified_count += 1
            continue

        # 3-level hierarchical statistics for standard classified taxons (Kingdom ➔ Phylum ➔ Class)
        kingdom_name = kingdom or "Unknown_Kingdom"
        phylum_name = phylum or "Unknown_Phylum"
        klass_name = klass or "Unknown_Class"

        if kingdom_name not in tax_summary:
            tax_summary[kingdom_name] = {"total": 0, "completed": 0, "phyla": {}}
        
        tax_summary[kingdom_name]["total"] += 1
        if ncbi_status == "completed":
            tax_summary[kingdom_name]["completed"] += 1

        phyla_dict = tax_summary[kingdom_name]["phyla"]
        if phylum_name not in phyla_dict:
            phyla_dict[phylum_name] = {"total": 0, "completed": 0, "classes": {}}
        
        phyla_dict[phylum_name]["total"] += 1
        if ncbi_status == "completed":
            phyla_dict[phylum_name]["completed"] += 1

        classes_dict = phyla_dict[phylum_name]["classes"]
        if klass_name not in classes_dict:
            classes_dict[klass_name] = {"total": 0, "completed": 0}
        
        classes_dict[klass_name]["total"] += 1
        if ncbi_status == "completed":
            classes_dict[klass_name]["completed"] += 1

    # Format Overview Report
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("==========================================================================================")
    lines.append(f"NCBI Genome Download & Annotation Overview - {config.TARGET_TAXON} (Updated: {now_str})")
    lines.append("==========================================================================================\n")

    lines.append("[NCBI Source Download Statistics]")
    lines.append(f"  - Total Genomes Registered     : {total_count}")
    lines.append(f"  - Completed NCBI Downloads     : {ncbi_completed}")
    lines.append(f"  - Failed NCBI Downloads        : {ncbi_failed}")
    lines.append(f"  - Pending NCBI Downloads       : {ncbi_pending}")
    lines.append(f"  - Genomes Without NCBI Ann     : {ncbi_unannotated_total}  (Target for Custom Annotation)")
    lines.append(f"  - Unclassified Genomes (Flat)  : {unclassified_count}  (Located in taxonomy/Unclassified/)\n")

    lines.append("[Custom Pipeline Re-annotation Statistics]")
    lines.append(f"  - Completed Custom Annotations : {custom_completed}")
    lines.append(f"  - Failed Custom Annotations    : {custom_failed}")
    lines.append(f"  - Pending Custom Annotations   : {custom_pending}\n")

    lines.append("[Taxonomy Summary (Kingdom ➔ Phylum ➔ Class) [Completed / Total]]")
    for kingdom, k_stats in sorted(tax_summary.items()):
        lines.append(f"  * Kingdom: {kingdom} [{k_stats['completed']} / {k_stats['total']}]")
        for phylum, p_stats in sorted(k_stats["phyla"].items()):
            lines.append(f"    - Phylum: {phylum} [{p_stats['completed']} / {p_stats['total']}]")
            for klass, c_stats in sorted(p_stats["classes"].items()):
                lines.append(f"      + Class: {klass} [{c_stats['completed']} / {c_stats['total']}]")
    lines.append("\n")

    # Table Slicing logic to prevent huge text files
    failed_rows = []
    active_rows = []
    
    header = f"{'Accession':<18} | {'Organism Name':<28} | {'NCBI Status':<12} | NCBI Ann | FNA GFF CDS FAA | {'Custom Status':<13} | GFF CDS FAA"

    for acc, info in sorted(records.items()):
        org_name = info.get("organism_name", "")
        if len(org_name) > 26:
            org_name = org_name[:23] + "..."
        
        ncbi = info.get("ncbi", {})
        custom = info.get("custom", {})

        ncbi_status = ncbi.get("download_status", "pending")
        ncbi_ann = "Y" if ncbi.get("has_annotation") else "N"
        
        fna = "Y" if ncbi.get("has_fna") else "N"
        gff = "Y" if ncbi.get("has_gff") else "N"
        cds = "Y" if ncbi.get("has_cds") else "N"
        faa = "Y" if ncbi.get("has_faa") else "N"

        custom_status = custom.get("annotation_status", "pending")
        c_gff = "Y" if custom.get("has_gff") else "N"
        c_cds = "Y" if custom.get("has_cds") else "N"
        c_faa = "Y" if custom.get("has_faa") else "N"

        row = f"{acc:<18} | {org_name:<28} | {ncbi_status:<12} |    {ncbi_ann}     |  {fna}   {gff}   {cds}   {faa}  | {custom_status:<13} |  {c_gff}   {c_cds}   {c_faa}"
        
        if ncbi_status == "failed" or custom_status == "failed":
            failed_rows.append(row)
        else:
            active_rows.append(row)

    lines.append(f"[Detailed Status Table (Showing All Failed & Top 100 Active Records)]")
    lines.append(header)
    lines.append("-" * len(header))

    # Always show all failures so that the user spots anomalies immediately
    if failed_rows:
        lines.append("--- FAILED RECORDS ---")
        for row in failed_rows:
            lines.append(row)

    # Show active rows with truncation threshold
    lines.append("--- ACTIVE/COMPLETED/PENDING RECORDS ---")
    if len(active_rows) > 100:
        for row in active_rows[:100]:
            lines.append(row)
        lines.append(f"... (Truncated {len(active_rows) - 100} active pending/completed records to prevent massive overview report file size) ...")
    else:
        for row in active_rows:
            lines.append(row)

    report_content = "\n".join(lines)
    
    try:
        with open(overview_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Generated download overview report at {overview_path}")
    except Exception as e:
        logger.error(f"Failed to write overview report: {e}")

def process_single_genome(idx, total_count, accession, info, db_manager, ncbi_client, type_dirs):
    """
    Downloads, extracts, validates MD5, reorganizes files.
    Also links the output directory into the 6-level lineage hierarchy
    (Kingdom ➔ Phylum ➔ Class ➔ Order ➔ Family ➔ Genus) for easy counting and directory browsing.
    """
    folder_name = info.get("folder_name")
    tax_id = info.get("tax_id")
    final_dest_dir = os.path.join(config.ALL_GENOMES_DIR, folder_name)
    temp_extract_dir = os.path.join(config.TMP_DIR, f"{accession}_extracted")

    logger.info(f"Processing ({idx}/{total_count}): {accession} -> {folder_name}")
    print(f"[{idx}/{total_count}] Starting download: {accession} ({info.get('organism_name')})...")

    # Resolve taxonomy lineage (Lazy Loading)
    if not info.get("phylum") and tax_id:
        try:
            logger.debug(f"Lazy-loading taxonomy metadata for TaxID {tax_id}...")
            lineage = ncbi_client.fetch_taxonomy_lineage(tax_id)
            if lineage:
                db_manager.update_taxonomy_info(
                    accession,
                    kingdom=lineage.get("kingdom"),
                    phylum=lineage.get("phylum"),
                    klass=lineage.get("class"),
                    order=lineage.get("order"),
                    family=lineage.get("family"),
                    genus=lineage.get("genus")
                )
        except Exception as texc:
            logger.warning(f"Failed to lazy-load taxonomy for {accession} (TaxID: {tax_id}): {texc}")

    zip_path = None
    try:
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
        if os.path.exists(os.path.join(final_dest_dir, "ncbi")):
            shutil.rmtree(os.path.join(final_dest_dir, "ncbi"))

        # 1. Download zip package
        zip_path = ncbi_client.download_genome_package(accession, config.TMP_DIR)
        
        # 2. Extract and organize files under 'final_dest_dir/ncbi/'
        file_presence = ncbi_client.extract_and_organize(
            accession, zip_path, temp_extract_dir, final_dest_dir, folder_name
        )

        # 3. Create symlinks pointing to final_dest_dir/ncbi/
        ncbi_client.create_symlinks(folder_name, accession, final_dest_dir, type_dirs)

        # 4. Create 6-level taxonomic browse directory links (Kingdom -> Phylum -> Class -> Order -> Family -> Genus)
        latest_record = db_manager.get_genome(accession) or {}
        kingdom = latest_record.get("kingdom")
        phylum = latest_record.get("phylum")
        klass = latest_record.get("class")
        order = latest_record.get("order")
        family = latest_record.get("family")
        genus = latest_record.get("genus")
        ncbi_client.create_taxonomy_symlink(
            folder_name, kingdom, phylum, klass, order, family, genus, final_dest_dir, config.TAXONOMY_DIR
        )

        # 5. Update Database (Thread-safe NCBI status update)
        db_manager.update_ncbi_status(
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
        db_manager.update_ncbi_status(accession, "failed", error_log=error_msg)
        
        ncbi_path = os.path.join(final_dest_dir, "ncbi")
        if os.path.exists(ncbi_path):
            try:
                shutil.rmtree(ncbi_path)
            except OSError:
                pass
        print(f"[{idx}/{total_count}] Failed download: {accession}. Error: {error_msg}")
        return False, accession, error_msg
    finally:
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
    logger.info(f"Starting NCBI {config.TARGET_TAXON} Genome Auto-Download Pipeline...")
    config.init_directories()

    db_manager = JsonDbManager(config.DB_PATH)
    ncbi_client = NcbiDatasetsClient(api_delay=config.API_DELAY, max_retries=config.MAX_RETRIES)

    if not ncbi_client.check_cli_installed():
        logger.critical("Pipeline aborted. 'datasets' CLI is missing.")
        print("[ERROR] NCBI Datasets CLI tool ('datasets') is not installed or not in PATH.", file=sys.stderr)
        return

    # ======================================================================
    # Phase 1: Metadata Sync
    # ======================================================================
    try:
        metadata_list = ncbi_client.fetch_genome_metadata()
    except Exception as e:
        logger.critical(f"Failed to synchronize metadata from NCBI: {e}")
        return

    new_records_count = db_manager.upsert_genomes(metadata_list)
    print(f"Synchronized metadata. Added {new_records_count} new genomes.")

    # ======================================================================
    # Phase 2: Concurrent Multi-Threaded Download & Structuring
    # ======================================================================
    pending_items = db_manager.get_pending_accessions()
    
    workers = config.PARALLEL_WORKERS if hasattr(config, "PARALLEL_WORKERS") else 4
    logger.info(f"Found {len(pending_items)} accessions pending download. Using {workers} parallel workers.")
    print(f"Found {len(pending_items)} accessions to download. Running with {workers} parallel threads...")

    if not pending_items:
        logger.info("No new genomes to download. Pipeline completed successfully.")
        generate_overview_report(db_manager, config.OVERVIEW_PATH)
        return

    type_dirs = {
        "fna": config.FNA_NCBI_DIR,
        "gff": config.GFF_NCBI_DIR,
        "cds": config.CDS_NCBI_DIR,
        "faa": config.FAA_NCBI_DIR
    }

    success_count = 0
    failure_count = 0
    total_items = len(pending_items)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                process_single_genome, idx, total_items, accession, info, db_manager, ncbi_client, type_dirs
            ): accession 
            for idx, (accession, info) in enumerate(pending_items, 1)
        }

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

            if idx % 10 == 0 or idx == total_items:
                generate_overview_report(db_manager, config.OVERVIEW_PATH)

    logger.info(f"Pipeline download phase complete. Success: {success_count}, Failures: {failure_count}")
    print(f"Pipeline complete. Successfully downloaded: {success_count}, Failed: {failure_count}")

    generate_overview_report(db_manager, config.OVERVIEW_PATH)

if __name__ == "__main__":
    run_pipeline()
