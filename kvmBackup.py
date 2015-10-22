#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Fri Oct  9 11:20:46 2015

@author: Paolo Cozzi <paolo.cozzi@ptp.it>
"""

import os
import sys
import yaml
import shutil
import socket
import libvirt
import logging
import tarfile
import argparse
import datetime

#my functions
from Lib import helper, flock

# Logging istance
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# A function to open a config file
def loadConf(file_conf):
    config = yaml.load(open(file_conf))
    
    #read my defined domains
    hostname = socket.gethostname()
    hostname = hostname.split(".")[0]
    
    #try to parse useful data
    mydomains = config[hostname]["domains"]
    
    #get my backup directory
    backupdir = config[hostname]["backupdir"]
    
    return mydomains, backupdir, config
    
#a function to check current day of the week
def checkDay(day):
    now = datetime.datetime.now()
    today = now.strftime("%a")
    
    if today == day:
        return True
        
    return False

def backup(domain, parameters, backupdir):
    """Do all the operation needed for backup"""
    
    #changing directory
    olddir = os.getcwd()
    workdir = os.path.join(backupdir, domain)
    
    #creating directory if not exists
    if not os.path.exists(workdir) and not os.path.isdir(workdir):
        logger.info("Creating directory %s" %(workdir))
        os.mkdir(workdir)
    
    #cange directory
    os.chdir(workdir)
    
    #a timestamp directory in which to put files
    date = datetime.datetime.now().strftime('%Y-%m-%d')
    datadir = os.path.join(workdir, date)
    
    #creating datadir
    logger.debug("Creating directory %s" %(datadir))
    os.mkdir(datadir)
    
    #define the target backup
    ext, tar_mode = '.tar', 'w'
      
    tar_name = domain + ext 
    tar_path = os.path.join( workdir, tar_name )
    tar_path_gz = tar_path + ".gz"
    
    #call rotation directive        
    if os.path.isfile( tar_path_gz ): # if file exists, run rotate
        logger.info('rotating backup files for ' + domain )
        helper.rotate( tar_path_gz, parameters["rotate"] )

    tar = tarfile.open( tar_path, tar_mode )
    
    #create a snapshot instance
    snapshot = helper.Snapshot(domain)

    #call dumpXML
    xml_files = snapshot.dumpXML(path=datadir)
    
    #Add xmlsto archive, and remove original file
    logger.info('Adding XMLs files for domain %s to archive %s' %(domain, tar_path))
    
    for xml_file in xml_files:
        tar.add(xml_file)
        logger.debug("%s added" %(xml_file))
        
        logger.debug("removing %s from %s" %(xml_file, datadir))
        os.remove(xml_file)
        

    #call snapshot
    snapshot.callSnapshot()

    logger.info('Adding image files for %s to archive %s' %(domain, tar_path))

    #copying file
    for disk, source in snapshot.disks.iteritems():
        dest = os.path.join(datadir, os.path.basename(source))
        
        logger.debug("copying %s to %s" %(source, dest))
        shutil.copy2( source, dest )

        logger.debug("Adding %s to archive" %(dest))        
        tar.add(dest)
        
        logger.debug("removing %s from %s" %(dest, datadir))
        os.remove(dest)

    #block commit (and delete snapshot)
    snapshot.doBlockCommit()

    #closing archive
    tar.close()
    
    #Now launcing subprocess with pigz
    helper.packArchive(target=tar_name)
    
    #revoving EMPTY datadir
    os.rmdir(datadir)

    #return to the original directory
    os.chdir(olddir)
    
    logger.info("Backup for %s completed" %(domain))


# A global connection instance
conn = libvirt.open("qemu:///system")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Backup of KVM domains')
    parser.add_argument("-c", "--config", required=True, type=str, help="The config file")
    args = parser.parse_args()
    
    # the program name
    prog_name = os.path.basename(sys.argv[0])
    
    #end of the program
    logger.info("Statring %s" %(prog_name))
    
    lockfile = os.path.splitext(os.path.basename(sys.argv[0]))[0] + ".lock"
    lockfile_path = os.path.join("/var/run", lockfile)
    
    lock = flock.flock(lockfile_path, True).acquire()
    
    if not lock:
        logger.error("Another istance of %s is running. Please wait for its termination or kill the running application" %(sys.argv[0]))
        sys.exit(-1)
    
    #get all domain names
    domains = [domain.name() for domain in conn.listAllDomains()]
    
    #parse configuration file
    mydomains, backupdir, config = loadConf(args.config)
    
    #test for directory existance
    if not os.path.exists(backupdir) and os.path.isdir(backupdir) is False:
        logger.info("Creating directory %s" %(backupdir))
        os.mkdir(backupdir)
    
    #debug
    #pprint.pprint(mydomains)
    
    for domain_name, parameters in mydomains.iteritems():
        #check if bakcup is needed
        domain_backup = False
        
        for day in parameters["day_of_week"]:
            if checkDay(day) is True:
                logger.info("Ready for back up of %s" %(domain_name))
                domain_backup = True
                
                #do backup stuff
                backup(domain_name, parameters, backupdir)
                
                #breaking cicle
                break
            
        if domain_backup is False:
            logger.debug("Ignoring %s domain" %(domain_name))
            
    #end of the program
    logger.info("%s completed successfully" %(prog_name))


