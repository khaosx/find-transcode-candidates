# *Arr Transcode Candidate Reporter

## Description

This Python script scans multiple instances of Radarr and Sonarr (configured via a central credentials file) to identify media files matching specific quality profiles, often indicating candidates for transcoding (e.g., finding large Remux files). It generates a multi-page HTML report summarizing the findings and providing detailed lists per instance, along with an error report page if issues occur during processing.

## Features

* **Multi-Instance Support:** Scans multiple Radarr and Sonarr instances defined in a single configuration file.
* **Dynamic Discovery:** Automatically detects and processes all fully configured instances from the credentials file.
* **Configurable Quality:** Target quality profile (e.g., `Remux-1080p`, `WEBDL-2160p`) can be set independently for each instance.
* **HTML Reporting:** Generates a user-friendly, multi-page HTML report:
    * `index.html`: Summary page listing all processed instances, candidate counts, total sizes (where applicable), status, and links to detail pages. Includes an overall summary footer.
    * `transcode_candidates_{InstanceName}.html`: Detail page for each instance, listing the specific movies (Radarr) or series (Sonarr) identified as candidates.
    * `error_report.html`: Lists any errors encountered during processing, grouped by instance (only generated if errors occur).
* **Error Tracking:** Captures and reports both instance-level connection/API errors and item-level processing errors (e.g., failure to fetch episode files for a specific Sonarr series).

## Prerequisites

* **Python 3:** Version 3.7 or higher is recommended (due to f-string usage). Check with `python3 --version`.
* **Requests Library:** A Python library for making HTTP requests. Install it using pip:
    ```bash
    pip install requests
    # or
    pip3 install requests
    ```

## Setup

1.  **Get the Script:** Clone this repository or download the `transcode_candidate_reporter.py` script.
2.  **Create Credentials File:**
    * Locate the example credentials file: `.arr_stack_creds.txt.example`.
    * **Copy** or **rename** this file to `.arr_stack_creds.txt` in the **same directory** as the Python script.
    * **Edit `.arr_stack_creds.txt`** and replace the placeholder values with your **actual** URLs, API Keys, desired Instance Names, and Target Quality profiles for each of your Radarr and Sonarr instances. See the Configuration section below for details.
3.  **Security (IMPORTANT):** If you are using Git, **immediately add `.arr_stack_creds.txt` to your `.gitignore` file** to prevent accidentally committing your sensitive credentials. Add this line to `.gitignore`:
    ```
    .arr_stack_creds.txt
    ```

## Configuration (`.arr_stack_creds.txt`)

This file stores the connection details and settings for each *Arr instance the script should scan.

* Use the format `KEY=VALUE` with no spaces around the `=`.
* Lines starting with `#` are ignored comments.
* For **each instance** you want to process, you **must** define the following 5 keys, using a consistent prefix (e.g., `RADARR_`, `SONARR4K_`, `MYNAS_SONARR_`):

    * `PREFIX_URL`: The full URL to the instance (e.g., `http://192.168.1.10:7878`).
    * `PREFIX_API_KEY`: The API key found in the instance's settings (Settings -> General -> Security).
    * `PREFIX_INSTANCE_NAME`: A user-friendly name for reporting (e.g., `Radarr 4K`, `Sonarr TV`).
    * `PREFIX_INSTANCE_TYPE`: Must be either `radarr` or `sonarr` (lowercase).
    * `PREFIX_TARGET_QUALITY`: The exact quality profile name (case-insensitive match) to identify candidates within this instance (e.g., `Remux-1080p`, `Bluray-2160p`).

* **Example Snippet:**
    ```plaintext
    # --- Default Radarr ---
    RADARR_URL=http://YOUR_DEFAULT_RADARR_URL:PORT
    RADARR_API_KEY=YOUR_DEFAULT_RADARR_API_KEY
    RADARR_INSTANCE_NAME=Radarr Default HD
    RADARR_INSTANCE_TYPE=radarr
    RADARR_TARGET_QUALITY=Remux-1080p
    ```
* Refer to the `.arr_stack_creds.txt.example` file for the full structure and more examples.

## Running the Script

Navigate to the directory containing the script and the credentials file in your terminal and run:

```bash
python3 transcode_candidate_reporter.py
