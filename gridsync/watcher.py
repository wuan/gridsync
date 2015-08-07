# -*- coding: utf-8 -*-

import logging
import os
import threading
import time

from twisted.internet import reactor
from twisted.internet.task import LoopingCall
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from gridsync.sync import sync


class Watcher(PatternMatchingEventHandler):
    def __init__(self, tahoe, local_dir, remote_dircap, polling_frequency=20):
        super(Watcher, self).__init__(ignore_patterns=["*.gridsync-versions*"])
        self.tahoe = tahoe
        self.local_dir = os.path.expanduser(local_dir)
        self.remote_dircap = remote_dircap
        if not os.path.isdir(self.local_dir):
            os.makedirs(self.local_dir)
        self.polling_frequency = polling_frequency
        self.latest_snapshot = 0
        self.do_backup = False

    def on_modified(self, event):
        self.do_backup = True
        logging.debug(event)

    def check_for_backup(self):
        if self.do_backup and not self.tahoe.parent.sync_state:
            self.do_backup = False
            reactor.callInThread(self.wait_for_writes)

    def wait_for_writes(self):
        time.sleep(1)
        if not self.do_backup:
            self.perform_backup()

    def perform_backup(self):
        latest_snapshot = self.get_latest_snapshot()
        if latest_snapshot == self.latest_snapshot:
            # If already we have the latest backup, perform backup
            self.tahoe.parent.sync_state += 1
            self.tahoe.backup(self.local_dir, self.remote_dircap)
            self.tahoe.parent.sync_state -= 1
        else:
            #self.observer.stop() # Pause Observer during sync...
            sync(self.tahoe, self.local_dir, self.remote_dircap)
            #self.observer.start()
        # XXX Race condition
        self.latest_snapshot = self.get_latest_snapshot()

    def check_for_new_snapshot(self):
        logging.debug("Checking for new snapshot...")
        try:
            latest_snapshot = self.get_latest_snapshot()
        except:
            # XXX This needs to be far more robust; 
            # don't assume an exception means no backups...
            logging.warning("Doing (first?) backup; get_latest_snapshot() failed")
            self.tahoe.parent.sync_state += 1
            self.tahoe.backup(self.local_dir, self.remote_dircap)
            self.tahoe.parent.sync_state -= 1
            self.latest_snapshot = self.get_latest_snapshot()
            return
            
        if latest_snapshot == self.latest_snapshot:
            logging.debug("Up to date ({}); nothing to do.".format(latest_snapshot))
        else:
            logging.debug("New snapshot available ({}); syncing...".format(latest_snapshot))
            # XXX self.tahoe.parent.sync_state should probably be a list of
            # syncpair objects to allow introspection
            # check here for sync_state?
            #self.observer.stop() # Pause Observer during sync...
            sync(self.tahoe, self.local_dir, self.remote_dircap)
            #self.observer.start()
            # XXX Race condition; fix
            self.latest_snapshot = latest_snapshot

    def check_for_updates(self):
        try:
            latest_snapshot = self.get_latest_snapshot()
        except:
            # XXX This needs to be far more robust; 
            # don't assume an exception means no backups...
            logging.warning("Doing (first?) backup; get_latest_snapshot() failed")
            self.tahoe.parent.sync_state += 1
            self.tahoe.backup(self.local_dir, self.remote_dircap)
            self.tahoe.parent.sync_state -= 1
            self.latest_snapshot = self.get_latest_snapshot()
            return
            
        if latest_snapshot == self.latest_snapshot:
            logging.debug("Up to date ({}); nothing to do.".format(latest_snapshot))
        else:
            logging.debug("New snapshot available ({}); syncing...".format(latest_snapshot))
            # XXX self.tahoe.parent.sync_state should probably be a list of
            # syncpair objects to allow introspection
            # check here for sync_state?
            #self.observer.stop() # Pause Observer during sync...
            sync(self.tahoe, self.local_dir, self.remote_dircap)
            #self.observer.start()
            # XXX Race condition; fix
            self.latest_snapshot = latest_snapshot
        t = threading.Timer(self.polling_frequency, self.check_for_updates)
        t.setDaemon(True)
        t.start()

    def get_latest_snapshot(self):
        dircap = self.remote_dircap + "/Archives"
        j = self.tahoe.ls_json(dircap)
        snapshots = []
        for snapshot in j[1]['children']:
            snapshots.append(snapshot)
        snapshots.sort()
        return snapshots[-1:][0]
        #latest = snapshots[-1:][0]
        #return utils.utc_to_epoch(latest) 

    def start(self):
        #self.sync()
        if not self.remote_dircap:
            dircap = self.tahoe.mkdir()
            logging.debug("Created dircap for {} ({})".format(self.local_dir, dircap))
            self.remote_dircap = dircap
            self.tahoe.parent.settings[self.tahoe.name]['sync'][self.local_dir] = self.remote_dircap
            logging.debug(self.tahoe.parent.settings)
            self.tahoe.parent.config.save(self.tahoe.parent.settings)

        #self.check_for_updates()
        self.check_for_new_snapshot()
        logging.info("Starting observer in {}".format(self.local_dir))
        self.observer = Observer()
        self.observer.schedule(self, self.local_dir, recursive=True)
        self.observer.start()
        self.local_check_loop = LoopingCall(self.check_for_backup)
        self.local_check_loop.start(1)
        self.remote_check_loop = LoopingCall(self.check_for_new_snapshot)
        self.remote_check_loop.start(self.polling_frequency)

    def stop(self):
        logging.info("Stopping observer in {}".format(self.local_dir))
        self.local_check_loop.stop()
        self.remote_check_loop.stop()
        try:
            self.observer.stop()
            self.observer.join()
        except:
            pass

