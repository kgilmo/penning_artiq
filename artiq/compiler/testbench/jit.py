import os, sys, fileinput, ctypes
from pythonparser import diagnostic
from llvmlite_artiq import binding as llvm
from .. import Module
from ..targets import NativeTarget

def main():
    libartiq_personality = os.getenv('LIBARTIQ_PERSONALITY')
    if libartiq_personality is not None:
        llvm.load_library_permanently(libartiq_personality)

    def process_diagnostic(diag):
        print("\n".join(diag.render()))
        if diag.level in ("fatal", "error"):
            exit(1)

    engine = diagnostic.Engine()
    engine.process = process_diagnostic

    source = "".join(fileinput.input())
    source = source.replace("#ARTIQ#", "")
    mod = Module.from_string(source.expandtabs(), engine=engine)

    target = NativeTarget()
    llmod = mod.build_llvm_ir(target)
    llparsedmod = llvm.parse_assembly(str(llmod))
    llparsedmod.verify()

    llmachine = llvm.Target.from_triple(target.triple).create_target_machine()
    lljit = llvm.create_mcjit_compiler(llparsedmod, llmachine)
    llmain = lljit.get_pointer_to_global(llparsedmod.get_function(llmod.name + ".__modinit__"))
    ctypes.CFUNCTYPE(None)(llmain)()

if __name__ == "__main__":
    main()