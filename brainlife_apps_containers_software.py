#!/usr/bin/env python3

import os,sys
import pandas as pd
import numpy as np
import subprocess
import shutil
import json

# this will create an apps dataframe from the apps_json
def create_apps_dateframe(apps_json,outpath):

    df = pd.DataFrame()

    df['app'] = [ f['github'].split('/')[1] for f in apps ]
    df['owner'] = [ f['github'].split('/')[0] for f in apps ]
    df['doi'] = [ f['doi'] for f in apps ]
    df['brainlife_id'] = [ f['_id'] for f in apps ]

    if outpath:
        df.to_csv(outpath,index=False)

    return df

# identify docker containers for github repository information for brainlife apps.
def identify_docker_containers(owner,repo,branch,main_file):

    print('identifying docker containers used in %s/%s:%s' %(owner,repo,branch))

    current_dir = os.getcwd()

    # clone the github repo
    print('cloning repository')
    subprocess.run(["git","clone","https://github.com/"+owner+"/"+repo,"-b",branch],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

    # cd into the directory
    os.chdir(repo)

    # grab the singularity calls
    print('grabbing containers')
    tmp_line = subprocess.run(["awk","/docker:/",main_file],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8').split('\n')[:-1]

    # clean up container names
    containers = [ "docker://"+f.split('docker://')[1].split(' ')[0] for f in tmp_line ]

    # remove duplicates
    containers = [ containers[i] for i in range(len(containers)) if i == containers.index(containers[i]) ]

    # change dir to previous pwd and remove cloned directory
    os.chdir(current_dir)
    shutil.rmtree(repo)

    return containers

# identifies all app branches
def identify_app_branches(owner,repo):

    print('identifying branches for repository %s/%s' %(owner,repo))

    # use git ls-remote to identify all the branches for a repo
    tmp_branches = subprocess.run(["git","ls-remote","--heads","https://github.com/"+owner+"/"+repo],stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode('utf-8').split('\n')[:-1]

    # clean up
    branches = [ f.split('/heads/')[1] for f in tmp_branches ]

    return branches

# builds a dataframe of the app containers. will call identify_app_branches and identify_docker_containers
def build_app_branches_df(owner,repo,main_file):

    print('identifying app branches and docker containers for app %s/%s' %(owner,repo))

    df = pd.DataFrame(columns=['app','owner','branch','containers'])

    # grab app repo branches from git
    branches = identify_app_branches(owner,repo)

    # grab app containers for each branch
    for i in branches:
        tmp = pd.DataFrame()
        containers = identify_docker_containers(owner,repo,i,main_file)
        tmp['app'] = [ repo for f in range(len(containers)) ]
        tmp['owner'] = [ owner for f in range(len(containers)) ]
        tmp['branch'] = [ i for f in range(len(containers)) ]
        tmp['containers'] = containers

        df = pd.concat([df,tmp])
        df = df.reset_index(drop=True)

    return df

# sometimes if container is a python container exclusively, this will cause failure. need to catch thi
def check_if_python(tmp):

    if 'Run a python command' in tmp.stdout.decode('utf-8'):
        tmp.stdout = tmp.stdout.decode('utf-8').replace('\nUsage: docker run <imagename> COMMAND\n\nCommands\n\npython     : Run a python command\nbash       : Start a bash shell\nvtk_ccmake : Prepare VTK to build with ccmake. This happens in the container (not during image build)\nvtk_make   : Build the VTK library\nhelp       : Show this message\n\n','').encode()

    return tmp

# sometimes fsl containers output a warning message that screws with the code. this will
# remove that message
def check_fsl_citation(tmp):

    if 'Some packages in this Docker container are non-free' in tmp.stdout.decode('utf-8'):
        tmp.stdout = tmp.stdout.decode('utf-8').replace('Some packages in this Docker container are non-free\nIf you are considering commercial use of this container, please consult the relevant license:\nhttps://fsl.fmrib.ox.ac.uk/fsl/fslwiki/Licence\n','').encode()

    return tmp

# this wraps both the check functions to make easier to reimplement
def check_fsl_python(tmp):

    tmp = check_fsl_citation(tmp)

    tmp = check_if_python(tmp)

    return tmp

# will find exact file location of a specific text file. useful for finding fslversion file
def find_filename(container,check_filename):

    tmp = subprocess.run(["docker","run","--rm",container.split('docker://')[1],"find","/","-type","f","-name",check_filename],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

    return tmp

# this function will check for common neuroimaging packages that have install locations not identified by syft. will probably need to continually update this with 
# new software and versions 
def check_neuroimage_package(df,package,container,check_command,check_file):

    if check_command == 'find':
        tmp = subprocess.run(["docker","run","--rm",container.split('docker://')[1],"find","/","-type","f","-name",check_file],stdout=subprocess.PIPE,stderr=subprocess.PIPE)        
    else:
        tmp = subprocess.run(["docker","run","--rm",container.split('docker://')[1],check_command,check_file],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

    tmp = check_fsl_python(tmp)

    found_by = 'manual-inspection'

    if package == 'qsiprep' or package == 'fmriprep' or package == 'mriqc':
        package_version = subprocess.run(["docker","run","--rm",container.split('docker://')[1],package,check_command],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        package_version = check_fsl_python(package_version).stdout.decode('utf-8').strip('\n').split(' ')
        package_version = [ f for f in package_version if f != package ][-1]
        if package_version:
            df = df.append({'package': package, 'version': package_version, 'found_by': found_by},ignore_index=True)
    elif package == 'freesurfer-stats':
        if tmp.stdout.decode('utf-8'):
            filepath = check_file+'/Pipfile'
            tmp_vs = subprocess.run(["docker","run","--rm",container.split('docker://')[1],"cat",filepath],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            tmp_vs = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')
            package_version = [ tmp_vs[f+1] for f in range(len(tmp_vs)) if 'freesurfer-stats' in tmp_vs[f] ][0].split(' ')[1]
            df = df.append({'package': package, 'version': package_version, 'found_by': found_by},ignore_index=True)
    else:    
        if not tmp.stdout.decode('utf-8').split(':')[-1] == '\n' and not tmp.stdout.decode('utf-8').split(':')[-1] == '':
            if package == 'freesurfer':
                filepath = tmp.stdout.decode('utf-8').split(' ')[-1].replace('\n','')
                if '/bin' in filepath:
                    filepath = filepath.split('/bin')[0]
                filepath = filepath+'/VERSION'
                tmp_vs = subprocess.run(["docker","run","--rm",container.split('docker://')[1],"cat",filepath],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

                package_version = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')[-1]
                if not package_version:
                    tmp_vs = subprocess.run(["docker","run","--rm",container.split('docker://')[1],"mri_vol2vol","--version"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

                    package_version = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')[0].split(' ')[-1]
                    if package_version == 'info)':
                        package_version = 'dev'
            
            elif package == 'connectome_workbench':
                tmp_vs = subprocess.run(["docker","run","--rm",container.split('docker://')[1],check_file,"-version"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                tmp_vs = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')

                package_version = [ f for f in tmp_vs if 'Version:' in f ][0].split('Version:')[1].strip(' ')
            
            elif package == 'mrtrix':
                tmp_vs = subprocess.run(["docker","run","--rm",container.split('docker://')[1],check_file,"--version"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

                tmp_vs = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')

                package_version = [ f for f in tmp_vs if check_file in f ][0].replace('==','').strip(' ').split(' ')[1]
            
            elif package == 'dsistudio':
                tmp_vs = subprocess.run(["docker","run","--rm",container.split('docker://')[1],check_file,"--version"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                package_version = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')[0].split(': ')[-1]

            elif package == 'pynets':
                tmp_vs = subprocess.run(["docker","run","--rm",container.split('docker://')[1],check_file,"--version"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)

                package_version = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')[0].split(' ')[1]
            
            elif package == 'fsl':
                tmp_vs = find_filename(container,'fslversion')
                tmp_vs = check_fsl_python(tmp_vs).stdout.decode('utf-8').split('\n')[:-1]

                package_version = subprocess.run(["docker","run","--rm",container.split('docker://')[1],"cat",tmp_vs[-1]],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                package_version = check_fsl_python(package_version).stdout.decode('utf-8').split('\n')[0]
                
            df = df.append({'package': package, 'version': package_version, 'found_by': found_by},ignore_index=True)

    return df

# use this function to create tables of installed binaries using syft
def identify_binaries(container):

    print('identifying installed binaries for container %s' %container)
    # runs syft in shell and returns the output, which is a comma-separated table stored as a list
    tmp = subprocess.run(["syft", container.split('docker://')[1], "--scope", "all-layers", "-o", "template", "-t", "csv.tmpl"],stdout=subprocess.PIPE).stdout.decode('utf-8').split('\n')[:-1]

    # builds the dataframe
    df = pd.DataFrame([ f.replace('"','').split(',') for f in tmp[1:] ],columns=["package","version","found_by"])
    
    # check for common neuroimaging softwares with odd install locations not identifyed by syft
    print('checking for neuroimaging packages syft missed')
    packages_to_check = ['freesurfer','connectome_workbench','mrtrix','dsistudio','pynets','freesurfer-stats','fsl']
    # current_packages = df.package.unique().tolist()

    if 'qsiprep' in container:
        i = 'qsiprep'
        check_command = '--version'
        check_file = ''      
        df = check_neuroimage_package(df,i,container,check_command,check_file)
    elif 'fmriprep' in container:
        i = 'fmriprep'
        check_command = '--version'
        check_file = ''
        df = check_neuroimage_package(df,i,container,check_command,check_file)
    elif 'mriqc' in container:
        i = 'mriqc'
        check_command = '--version'
        check_file = ''
        df = check_neuroimage_package(df,i,container,check_command,check_file)
    else:
        for i in packages_to_check:
            check_command = 'whereis'
            print('checking for %s install' %i)
            if i == 'freesurfer':
                check_file = 'mri_vol2vol'
            elif i == 'connectome_workbench':
                check_file = 'wb_command'
            elif i == 'mrtrix':
                check_file = 'mrconvert'
            elif i == 'dsistudio':
                check_file = 'dsi_studio'
            elif i == 'pynets':
                check_file = 'pynets'
            elif i == 'freesurfer-stats':
                check_file = '/freesurfer-stats'
                check_command = 'ls'
            elif i == 'fsl':
                check_file = 'fslversion'
                check_command = 'find'
            
            # if i not in current_packages:
            df = check_neuroimage_package(df,i,container,check_command,check_file)

    # adds the container name as a new column to allow for merging with other containers
    df['containers'] = [ container for f in range(len(df)) ]

    # removes the singularity image to avoid memory issues
    subprocess.run(["docker","rmi", container.split('docker://')[1]])
    
    return df

def main():

    with open('config.json','r') as config_f:
        config = json.load(config_f)

    apps_json_inpath = config['apps_json_inpath']
    apps_df_outpath = config['apps_df_outpath']

    # load the apps dataframe. this is our input set of apps to 1) identify docker containers for and 2) identify installed software packages in docker container
    if os.path.isfile('apps.csv'):
        apps = pd.read_csv('apps.csv')
    else:
        with open(apps_json_inpath,'r') as apps_f:
            apps_json = json.load(apps_f)

            # create apps dataframe
            apps = create_apps_dateframe(apps_json,'apps.csv')

    # build list of owners and repos to loop through
    owners = apps.owner.tolist()
    repos = apps.app.tolist()

    # build_app_branches_df(owner,repo,main_file)
    apps_branches_containers = pd.DataFrame()
    for i in range(len(repos)):
        apps_branches_containers = pd.concat([apps_branches_containers,build_app_branches_df(owners[i],repos[i],'main')])

    apps_branches_containers = apps_branches_containers.reset_index(drop=True)

    # merge containers with apps dataframe
    apps = pd.merge(apps,apps_branches_containers,on=['app','owner'])
    apps = apps.reset_index(drop=True)

    # build list of containers
    containers = sorted(apps.containers.unique().tolist())

    # loop through containers and identify installed packages
    apps_software = pd.DataFrame()
    for i in containers:
        apps_software = pd.concat([apps_software,identify_binaries(i)])

    apps_software = apps_software.reset_index(drop=True)

    # merge binaries with apps
    apps = pd.merge(apps,apps_software,on='containers')
    apps = apps.reset_index(drop=True)

    # save apps updated apps dataframe
    apps.to_csv(apps_df_outpath,index=False)

if __name__ == '__main__':
    main()
