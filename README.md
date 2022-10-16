# Brainlife app statistics

This repository contains code to 1) grab all of the apps from brainlife using the cli, 2) identify the branches and containers used within each app and 3) build dataframes containing all of the software packages installed for each container that an app calls.

This is intended to be used 1) as SBOM and 2) in combination with usage statistics to identify how often different software packages are used.

WORK IN PROGRESS

Directory structure:
```
  ./
  ├── apps_df.csv
  ├── brainlife_apps_containers_software.py
  ├── grab_apps_json.sh
  └── README.md

  0 directories, 4 files
```
