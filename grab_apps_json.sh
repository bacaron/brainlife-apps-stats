#!/bin/bash

topDir=$1
bl_user=$2
bl_pass=$3

# login to bl cli
bl login --user ${bl_user} --pass ${bl_pass}

# create apps.json
bl app query -l 1000000 -j > ${topDir}/apps.json
