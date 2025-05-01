import requests
import json
import os
import math
import sys
import re
from datetime import datetime
from collections import defaultdict # Needed again for Sonarr aggregation

# --- Configuration ---
CREDS_FILENAME = ".arr_stack_creds.txt"
OUTPUT_SUBDIR = "transcode-candidates-report"
INDEX_REPORT_FILENAME = "index.html"
DETAIL_REPORT_FILENAME_TEMPLATE = "transcode_candidates_{sanitized_name}.html"
ERROR_REPORT_FILENAME = "error_report.html"
# --- End Configuration ---

# --- Utility Functions (Unchanged) ---
def format_bytes(size_bytes):
    if size_bytes is None or size_bytes <= 0: return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    if size_bytes <= 0: return "0 B"
    i = int(math.floor(math.log(size_bytes, 1024)))
    i = max(0, min(i, len(size_name) - 1))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def sanitize_filename(name):
    name = name.replace(' ', '_')
    name = re.sub(r'[^\w\-.]', '', name)
    return name

def get_api_endpoint(instance_type, base_url, endpoint_name):
    base_url = base_url.rstrip('/')
    endpoints = {
        'radarr': {'media': '/api/v3/movie'},
        'sonarr': {'media': '/api/v3/series', 'files': '/api/v3/episodefile'}
    }
    try:
        return f"{base_url}{endpoints[instance_type][endpoint_name]}"
    except KeyError:
        print(f"Warning: Unknown endpoint '{endpoint_name}' for instance type '{instance_type}'")
        return None

def load_credentials(filepath):
    # (Function remains the same)
    creds = {}
    try:
        print(f"Attempting to load credentials from: {filepath}")
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip();
                if not line or line.startswith('#'): continue
                try: key, value = line.split('=', 1); creds[key.strip()] = value.strip()
                except ValueError: print(f"Warning: Skipping invalid line {line_num}: {line}")
        print("Credentials loaded."); return creds
    except FileNotFoundError: print(f"Error: Credentials file not found: '{filepath}'. Exiting."); sys.exit(1)
    except Exception as e: print(f"Error reading credentials file: {e}. Exiting."); sys.exit(1)

def discover_instances(all_creds):
    # (Function remains the same)
    discovered_instances = []; prefixes = set()
    required_suffixes = ['_URL', '_API_KEY', '_INSTANCE_NAME', '_INSTANCE_TYPE', '_TARGET_QUALITY']
    for key in all_creds.keys():
        for suffix in required_suffixes:
            if key.endswith(suffix): prefixes.add(key[:-len(suffix)]); break
    print(f"Found potential instance prefixes: {list(prefixes)}")
    for prefix in prefixes:
        instance_config = {'prefix': prefix}; complete = True
        for suffix in required_suffixes:
            key = f"{prefix}{suffix}"
            if key not in all_creds: print(f"Info: Skipping prefix '{prefix}': missing '{key}'"); complete = False; break
            instance_config[suffix.lower()[1:]] = key
        if complete:
            type_key = instance_config['instance_type']; instance_type = all_creds[type_key].lower()
            if instance_type in ['radarr', 'sonarr']:
                instance_config['type_val'] = instance_type
                discovered_instances.append(instance_config)
                print(f"Found configured instance: {all_creds[instance_config['instance_name']]} (Type: {instance_type})")
            else: print(f"Warning: Skipping instance '{all_creds[instance_config['instance_name']]}': unknown TYPE '{instance_type}'.")
    return discovered_instances

# --- Instance Processing Function ---
def process_instance(instance_config, all_creds, processing_errors):
    """Fetches and processes data for a single *arr instance, appending errors to list."""
    # (Initial setup remains the same)
    instance_type = instance_config['type_val']
    url = all_creds[instance_config['url']]
    api_key = all_creds[instance_config['api_key']]
    instance_name = all_creds[instance_config['instance_name']]
    target_quality = all_creds[instance_config['target_quality']]

    print(f"\n--- Processing Instance: {instance_name} ({instance_type}) ---")
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    results = {'name': instance_name, 'instance_type': instance_type, 'target_quality': target_quality, 'status': 'error', 'error_message': 'Initialization error', 'candidates': [], 'count': 0, 'total_size_bytes': 0}
    if instance_type == 'sonarr': results['series_count'] = 0 # Add specific counter for Sonarr series

    try:
        if instance_type == 'radarr':
            # --- Radarr Processing (Calculate size for detail report) ---
            api_endpoint = get_api_endpoint(instance_type, url, 'media')
            print(f"Connecting to: {url}")
            response = requests.get(api_endpoint, headers=headers, timeout=180)
            response.raise_for_status()
            movies = response.json()
            print(f"Fetched {len(movies)} movies. Filtering for quality '{target_quality}'...")

            candidates_list = []
            total_movie_size = 0
            movie_count = 0
            for movie in movies:
                if movie.get('hasFile', False) and (movie_file_info := movie.get('movieFile')):
                    quality_info = movie_file_info.get('quality')
                    file_size = movie_file_info.get('size')
                    if quality_info and (quality_details := quality_info.get('quality')):
                        quality_name = quality_details.get('name')
                        if quality_name and quality_name.lower() == target_quality.lower():
                            candidates_list.append({
                                'title': movie.get('title', 'N/A'), 'year': movie.get('year', 'N/A'),
                                'size_bytes': file_size, 'formatted_size': format_bytes(file_size)
                            })
                            movie_count += 1
                            if file_size: total_movie_size += file_size

            results.update({
                'status': 'success', 'candidates': candidates_list,
                'count': movie_count, # Number of movies
                'total_size_bytes': total_movie_size, # Total size of these movies
                'error_message': None
            })
            print(f"Found {movie_count} candidate movies totaling {format_bytes(total_movie_size)}.")

        elif instance_type == 'sonarr':
            # --- Sonarr Processing (Reinstating episode count/size aggregation) ---
            series_endpoint = get_api_endpoint(instance_type, url, 'media')
            ep_file_endpoint_base = get_api_endpoint(instance_type, url, 'files')

            print(f"Connecting to: {url} (Fetching Series)")
            series_response = requests.get(series_endpoint, headers=headers, timeout=120)
            series_response.raise_for_status()
            all_series = series_response.json()
            print(f"Fetched {len(all_series)} series. Checking each for matching episode files...")

            # --- MODIFIED: Use defaultdict to aggregate per series ---
            series_candidates_agg = defaultdict(lambda: {'count': 0, 'total_size_bytes': 0, 'title': 'N/A', 'year': None})
            total_matching_ep_count = 0
            total_matching_ep_size = 0
            series_checked_count = 0
            instance_had_item_errors = False

            for series in all_series:
                series_id = series.get('id')
                series_title = series.get('title', 'N/A')
                series_year = series.get('year', None)
                series_checked_count += 1

                if not series_id: print(f"Warning: Skipping series with no ID: {series_title}"); continue
                if series_checked_count % 50 == 0: print(f"  Checked {series_checked_count}/{len(all_series)} series...")

                try:
                    ep_file_url = f"{ep_file_endpoint_base}?seriesId={series_id}"
                    ep_files_response = requests.get(ep_file_url, headers=headers, timeout=30)
                    ep_files_response.raise_for_status()
                    episode_files = ep_files_response.json()

                    series_had_match = False # Track if this series gets added
                    for ep_file in episode_files:
                        quality_info = ep_file.get('quality')
                        file_size = ep_file.get('size')
                        if quality_info and (quality_details := quality_info.get('quality')):
                            quality_name = quality_details.get('name')
                            if quality_name and quality_name.lower() == target_quality.lower():
                                # --- MODIFIED: Aggregate counts and sizes ---
                                if not series_had_match: # First match for this series
                                    series_candidates_agg[series_id]['title'] = series_title
                                    series_candidates_agg[series_id]['year'] = series_year
                                    series_had_match = True

                                series_candidates_agg[series_id]['count'] += 1
                                if file_size: series_candidates_agg[series_id]['total_size_bytes'] += file_size

                                # Increment overall instance totals
                                total_matching_ep_count += 1
                                if file_size: total_matching_ep_size += file_size
                                # No break here - we want to count *all* matching episodes now

                except requests.exceptions.RequestException as e:
                    error_msg = f"Could not fetch/process episode files: {e}"
                    print(f"Warning: {error_msg} for series ID {series_id} ({series_title})")
                    processing_errors.append({'instance_name': instance_name, 'item_type': 'Series Episode Files', 'item_name': f"{series_title} (ID: {series_id})", 'error_message': str(e)})
                    instance_had_item_errors = True
                except Exception as e:
                    error_msg = f"Unexpected error processing files: {e}"
                    print(f"Warning: {error_msg} for series ID {series_id} ({series_title})")
                    processing_errors.append({'instance_name': instance_name, 'item_type': 'Series Episode Files Processing', 'item_name': f"{series_title} (ID: {series_id})", 'error_message': str(e)})
                    instance_had_item_errors = True

            print(f"Finished checking all series.")
            # --- MODIFIED: Format results from aggregated data ---
            candidates_list = []
            for series_id, data in series_candidates_agg.items():
                 candidates_list.append({
                     'title': data['title'], 'year': data['year'],
                     'episode_count': data['count'], # Per-series match count
                     'size_bytes': data['total_size_bytes'], # Per-series size sum
                     'formatted_size': format_bytes(data['total_size_bytes'])
                 })

            results.update({
                'status': 'success' if not instance_had_item_errors else 'warning', # Use warning if non-fatal errors occurred
                'candidates': candidates_list, # List of dicts per matching series
                'count': total_matching_ep_count, # Total matching EPISODES in instance
                'series_count': len(series_candidates_agg), # Total SERIES with matches
                'total_size_bytes': total_matching_ep_size, # Total size of matching EPISODES
                'error_message': None
            })
            print(f"Found {total_matching_ep_count} candidate episodes in {len(series_candidates_agg)} series, totaling {format_bytes(total_matching_ep_size)}.")
            if instance_had_item_errors: print("Note: Some errors occurred while fetching/processing episode files (see error report).")


    # --- Error Handling (append instance level errors) ---
    except requests.exceptions.RequestException as e: results['error_message'] = f"Request/Connection Error: {e}"
    except json.JSONDecodeError as e: results['error_message'] = f"JSON Decode Error: {e}"
    except Exception as e: results['error_message'] = f"Unexpected error during {instance_type} processing: {e}"

    if results['status'] == 'error':
        print(f"Error processing instance {instance_name}: {results['error_message']}")
        processing_errors.append({'instance_name': instance_name, 'item_type': 'Instance', 'item_name': instance_name, 'error_message': results['error_message']})

    return results


# --- HTML Generation Functions ---
def generate_detail_report(instance_result, output_dir):
    """Generates the HTML detail report for a single instance."""
    # (Setup remains the same)
    instance_name = instance_result['name']
    instance_type = instance_result['instance_type']
    target_quality = instance_result.get('target_quality', 'N/A')
    candidates = instance_result['candidates']
    status = instance_result['status'] # 'success', 'warning', or 'error'
    error_message = instance_result.get('error_message', '') # General error
    item_count = instance_result['count'] # Movie count or Episode count
    total_size_bytes = instance_result['total_size_bytes'] # Movie size or Episode size

    sanitized_name = sanitize_filename(instance_name)
    filename = DETAIL_REPORT_FILENAME_TEMPLATE.format(sanitized_name=sanitized_name)
    filepath = os.path.join(output_dir, filename)

    print(f"Generating detail report for '{instance_name}' -> {filepath}")

    # Determine labels / counts for summary box
    if instance_type == 'radarr':
        item_label_plural = "Movies"
        count_label = f"Total Candidate {item_label_plural}"
        display_count = item_count
    elif instance_type == 'sonarr':
        item_label_plural = "Series"
        # Use series_count for the main count in the summary box
        display_count = instance_result.get('series_count', 0)
        count_label = f"Total Candidate {item_label_plural}"
    else: # Fallback
        item_label_plural = "Items"; display_count = item_count; count_label = "Total Candidate Items"

    # HTML Head & Style (unchanged)
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Transcode Candidates - {instance_name}</title><style>body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }} h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }} table {{ border-collapse: collapse; width: 90%; margin: 25px auto; box-shadow: 0 2px 5px rgba(0,0,0,0.1); background-color: #fff; }} th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }} th {{ background-color: #3498db; color: white; font-weight: bold; }} tr:nth-child(even) {{ background-color: #f9f9f9; }} tr:hover {{ background-color: #ecf0f1; }} .summary {{ margin: 30px auto; padding: 15px; background-color: #eaf2f8; border-left: 5px solid #3498db; width: 88%; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }} .summary p {{ margin: 8px 0; font-size: 1.1em; }} .error {{ color: red; font-weight: bold;}} .footer {{ margin-top: 30px; text-align: center; font-size: 0.9em; color: #777; }}</style></head><body><h1>Transcode Candidates Report</h1><h2>Instance: {instance_name} ({instance_type.capitalize()})</h2><p><em>Target Quality for Candidates: {target_quality}</em></p><p><a href="{INDEX_REPORT_FILENAME}">&laquo; Back to Summary</a></p>"""

    if status == 'error': # Instance level error
        html += f"<p class='error'>Error processing this instance: {error_message}</p>"
    else: # Success or Warning (had item errors)
        # --- MODIFIED: Table headers ---
        html += "<table><thead><tr>"
        if instance_type == 'radarr':
            html += "<th>Movie Title</th><th>Year</th><th>File Size</th>"
        elif instance_type == 'sonarr':
            # Show per-series aggregation
            html += "<th>Series Title</th><th>Year</th><th># Matching Eps</th><th>Total Size of Eps</th>"
        else:
             html += "<th>Item Title</th><th>Year</th>"
        html += "</tr></thead><tbody>"

        # --- MODIFIED: Table rows ---
        if candidates:
            candidates.sort(key=lambda x: x['title'])
            for item in candidates:
                escaped_title = item['title'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                year_str = str(item.get('year', '----'))
                html += "<tr>"
                html += f"<td>{escaped_title}</td><td>{year_str}</td>"
                if instance_type == 'radarr':
                    html += f"<td>{item['formatted_size']}</td>"
                elif instance_type == 'sonarr':
                    # Show per-series aggregation results
                    html += f"<td>{item['episode_count']}</td><td>{item['formatted_size']}</td>"
                html += "</tr>"
        else:
             colspan = 4 if instance_type == 'sonarr' else (3 if instance_type == 'radarr' else 2)
             html += f"""<tr><td colspan="{colspan}" style="text-align: center;">No candidate {item_label_plural.lower()} found matching the criteria.</td></tr>"""

        # --- MODIFIED: Summary box ---
        html += f"""
        </tbody>
    </table>
    <div class="summary">
        <p><strong>Instance Summary</strong></p>
        <p>{count_label}: {display_count}</p>"""
        # Add episode count specifically for Sonarr
        if instance_type == 'sonarr':
             html += f"<p>Total Matching Episodes: {item_count}</p>" # item_count is total eps here
        # Add size line (total movie size for Radarr, total matching ep size for Sonarr)
        html += f"""<p>Total Size of Candidates: {format_bytes(total_size_bytes)}</p>
    </div>"""

    # --- Footer ---
    html += f"""
    <div class="footer">
        Report generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    </div>
</body>
</html>"""

    # (File writing remains the same)
    try:
        with open(filepath, 'w', encoding='utf-8') as f: f.write(html)
        print(f"Successfully generated detail report: {filepath}")
        return filename
    except IOError as e: print(f"Error writing detail report '{filepath}': {e}"); return None


# --- NEW FUNCTION: Generate Error Report (Unchanged) ---
def generate_error_report(errors, output_dir):
    if not errors: print("\nNo processing errors recorded."); return False
    filepath = os.path.join(output_dir, ERROR_REPORT_FILENAME)
    print(f"\nGenerating error report -> {filepath}")
    errors_by_instance = defaultdict(list)
    for error in errors: errors_by_instance[error['instance_name']].append(error)
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Processing Error Report</title><style>body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }} h1 {{ color: #2c3e50; border-bottom: 2px solid #c0392b; padding-bottom: 10px; }} h2 {{ color: #c0392b; margin-top: 30px; border-bottom: 1px solid #e74c3c; padding-bottom: 5px;}} table {{ border-collapse: collapse; width: 95%; margin: 15px 0; background-color: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }} th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; word-wrap: break-word; }} th {{ background-color: #e74c3c; color: white; font-weight: bold; }} .footer {{ margin-top: 30px; text-align: center; font-size: 0.9em; color: #777; }}</style></head><body><h1>Processing Error Report</h1><p><a href="{INDEX_REPORT_FILENAME}">&laquo; Back to Summary</a></p>"""
    for instance_name, instance_errors in errors_by_instance.items():
        html += f"<h2>Errors for Instance: {instance_name}</h2><table><thead><tr><th style='width:15%;'>Item Type</th><th style='width:30%;'>Item Name</th><th style='width:55%;'>Error Message</th></tr></thead><tbody>"
        for error in instance_errors:
            item_name = str(error.get('item_name', 'N/A')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            error_msg = str(error.get('error_message', 'N/A')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            item_type = str(error.get('item_type', 'N/A')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html += f"""<tr><td>{item_type}</td><td>{item_name}</td><td>{error_msg}</td></tr>"""
        html += """</tbody></table>"""
    html += f"""<div class="footer">Report generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div></body></html>"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f: f.write(html)
        print(f"Successfully generated error report: {filepath}"); return True
    except IOError as e: print(f"Error writing error report '{filepath}': {e}"); return False


# --- MODIFIED FUNCTION: generate_index_report ---
def generate_index_report(all_results, output_dir, errors_found):
    """Generates the main index HTML report linking to detail pages."""
    filepath = os.path.join(output_dir, INDEX_REPORT_FILENAME)
    print(f"\nGenerating index report -> {filepath}")

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Transcode Candidates Summary</title><style>body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }} h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }} table {{ border-collapse: collapse; width: 90%; margin: 25px auto; box-shadow: 0 2px 5px rgba(0,0,0,0.1); background-color: #fff; }} th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }} th {{ background-color: #3498db; color: white; font-weight: bold; }} tr:nth-child(even) {{ background-color: #f9f9f9; }} tr:hover {{ background-color: #ecf0f1; }} .error-row td {{ background-color: #fdd; color: #c33; }} .warning-row td {{ background-color: #fff3cd; }} .error-link {{ color: red; font-weight: bold; margin-left: 20px; }} .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #ccc; text-align: center; font-size: 0.9em; color: #777; }} .footer p {{ margin: 5px 0;}}</style></head><body><h1>Items Requiring Transcoding - Summary</h1><p><em>Report Date: {datetime.now().strftime("%Y-%m-%d")}</em>"""
    if errors_found: html += f""" <a class="error-link" href="{ERROR_REPORT_FILENAME}">View Processing Errors</a>"""
    html += """</p><table><thead><tr><th>Instance Name</th><th>Type</th><th>Candidate Count</th><th>Total Size of Candidates</th><th>Status</th></tr></thead><tbody>""" # Added Size column back

    grand_total_items = 0 # Movies or Series count
    grand_total_size_bytes = 0
    successful_instances = 0

    if all_results:
        for result in sorted(all_results, key=lambda x: x['name']):
            instance_name = result['name']
            instance_type = result['instance_type'].capitalize()
            status = result['status']
            detail_filename = result.get('detail_filename')
            error_msg = result.get('error_message', '')

            display_count_str = "N/A"
            formatted_size = "N/A"
            row_class = ""

            if status == 'error': row_class = " class='error-row'"
            elif status == 'warning': row_class = " class='warning-row'" # Style for partial success

            if status != 'error':
                successful_instances += 1
                size_bytes = result['total_size_bytes']
                grand_total_size_bytes += size_bytes
                formatted_size = format_bytes(size_bytes)

                if result['instance_type'] == 'radarr':
                    item_count = result['count'] # Movie count
                    grand_total_items += item_count
                    display_count_str = f"{item_count} Movies"
                elif result['instance_type'] == 'sonarr':
                    item_count = result.get('series_count', 0) # Series count
                    episode_count = result['count'] # Episode count
                    grand_total_items += item_count
                    display_count_str = f"{item_count} Series ({episode_count} Eps)" # Show both counts
                else: # Fallback
                    item_count = result['count']
                    grand_total_items += item_count
                    display_count_str = f"{item_count} Items"


            html += f"<tr{row_class}>"
            if status != 'error' and detail_filename: html += f"""<td><a href="{detail_filename}">{instance_name}</a></td>"""
            else: html += f"<td>{instance_name}</td>"
            html += f"""<td>{instance_type}</td><td>{display_count_str}</td><td>{formatted_size}</td><td>{status.capitalize()}{f': {error_msg}' if status == 'error' else ''}</td></tr>""" # Added size cell
    else:
        html += """<tr><td colspan="5" style="text-align: center;">No instances processed.</td></tr>""" # Colspan 5 now

    # Updated Footer
    html += f"""</tbody></table><div class="footer"><p><strong>Overall Summary ({successful_instances} Successful Instances):</strong></p><p>Total Candidate Items (Movies/Series): {grand_total_items}</p><p>Combined Size Across All Instances: {format_bytes(grand_total_size_bytes)}</p><p style="margin-top: 15px;">Report generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p></div></body></html>"""

    # (File writing remains the same)
    try:
        with open(filepath, 'w', encoding='utf-8') as f: f.write(html)
        print(f"Successfully generated index report: {filepath}")
    except IOError as e: print(f"Error writing index report '{filepath}': {e}")


# --- Main Execution ---
if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    creds_filepath = os.path.join(script_dir, CREDS_FILENAME)
    output_dir = os.path.join(script_dir, OUTPUT_SUBDIR)

    try: os.makedirs(output_dir, exist_ok=True); print(f"Output directory: {output_dir}")
    except OSError as e: print(f"Error creating output dir '{output_dir}': {e}. Exiting."); sys.exit(1)

    all_creds = load_credentials(creds_filepath)
    discovered_instances = discover_instances(all_creds)
    processed_results = []
    processing_errors = [] # Initialize error list

    if not discovered_instances: print("\nNo configured instances discovered.")
    else:
        print(f"\nProcessing {len(discovered_instances)} discovered instances...")
        for config in discovered_instances:
            instance_result = process_instance(config, all_creds, processing_errors) # Pass error list
            # Generate detail report if instance didn't completely fail on connection/auth etc.
            if instance_result['status'] != 'error':
                 detail_filename = generate_detail_report(instance_result, output_dir)
                 if detail_filename: instance_result['detail_filename'] = detail_filename
            processed_results.append(instance_result)

    # Generate reports
    errors_found = generate_error_report(processing_errors, output_dir)
    if processed_results:
        generate_index_report(processed_results, output_dir, errors_found)
    else:
        print("\nNo instances processed, skipping index report generation.")

    print("\nScript finished.")
