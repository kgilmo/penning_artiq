import sys, os

from artiq.protocols.file_db import FlatFileDB
from artiq.master.worker_db import DeviceManager

from artiq.coredevice.core import Core, CompileError

def main():
    with open(sys.argv[1]) as f:
        testcase_code = compile(f.read(), f.name, "exec")
        testcase_vars = {'__name__': 'testbench'}
        exec(testcase_code, testcase_vars)

    ddb_path = os.path.join(os.path.dirname(sys.argv[1]), "ddb.pyon")

    try:
        core = Core(dmgr=DeviceManager(FlatFileDB(ddb_path)))
        core.run(testcase_vars["entrypoint"], (), {})
        print(core.comm.get_log())
        core.comm.clear_log()
    except CompileError as error:
        print("\n".join(error.__cause__.diagnostic.render(only_line=True)))

if __name__ == "__main__":
    main()