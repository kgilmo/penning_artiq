import os
import sys
import unittest
import logging

from artiq.language import *
from artiq.protocols.file_db import FlatFileDB
from artiq.master.worker_db import DBHub, ResultDB
from artiq.frontend.artiq_run import (
    DummyScheduler, DummyWatchdog, SimpleParamLogger)


artiq_root = os.getenv("ARTIQ_ROOT")
logger = logging.getLogger(__name__)


@unittest.skipUnless(artiq_root, "no ARTIQ_ROOT")
class ExperimentCase(unittest.TestCase):
    def setUp(self):
        self.ddb = FlatFileDB(os.path.join(artiq_root, "ddb.pyon"))
        self.pdb = FlatFileDB(os.path.join(artiq_root, "pdb.pyon"))
        self.rdb = ResultDB(lambda description: None, lambda mod: None)
        self.dbh = DBHub(self.ddb, self.pdb, self.rdb)

    def execute(self, cls, **kwargs):
        expid = {
            "file": sys.modules[cls.__module__].__file__,
            "experiment": cls.__name__,
            "arguments": kwargs
        }
        sched = DummyScheduler(expid)
        try:
            try:
                exp = cls(self.dbh, scheduler=sched, **kwargs)
            except KeyError as e:
                # skip if ddb does not match requirements
                raise unittest.SkipTest(*e.args)
            self.rdb.build()
            exp.run()
            exp.analyze()
            return self.rdb.data.read
        finally:
            self.dbh.close_devices()