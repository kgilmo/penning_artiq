Installing ARTIQ
================

Preparing the core device FPGA board
------------------------------------

You may skip those steps if the board is already flashed.

You will need:

* FPGA vendor tools (e.g. Xilinx ISE or Vivado)
* OpenRISC GCC/binutils toolchain (or1k-elf-...)
* Python 3.3+
* Migen and MiSoC (http://m-labs.hk/gateware.html)

After these components are installed, build and flash the bitstream and BIOS by running `from the MiSoC top-level directory`: ::

    $ ./make.py -X /path_to/ARTIQ/soc -t artiq all

Then, build and flash the ARTIQ runtime: ::

    $ cd /path_to/ARTIQ/soc/runtime
    $ make flash

Check that the board boots by running a serial terminal program (you may need to press its FPGA reconfiguration button or power-cycle it to load the bitstream that was newly written into the flash): ::

    $ flterm --port /dev/ttyUSB1
    MiSoC BIOS   http://m-labs.hk
    [...]
    Booting from flash...
    Loading xxxxx bytes from flash...
    Executing booted program.
    ARTIQ runtime built <date/time>

The communication parameters are 115200 8-N-1.

Installing the host-side software
---------------------------------

The main dependency of ARTIQ is LLVM and its Python bindings (http://llvmpy.org). Currently, this installation is tedious because of the OpenRISC support not being merged upstream LLVM and because of incompatibilities between the versions of LLVM that support OpenRISC and the versions of LLVM that support the Python bindings. ::

    git clone https://github.com/openrisc/llvm-or1k
    cd llvm-or1k
    git checkout b3a48efb2c05ed6cedc5395ae726c6a6573ef3ba
    patch -p1 < /path_to/ARTIQ/patches/llvm/*

    cd tools
    git clone https://github.com/openrisc/clang-or1k clang
    cd clang
    git checkout 02d831c7e7dc1517abed9cc96abdfb937af954eb
    patch -p1 < /path_to/ARTIQ/patches/clang/*

    cd ../..
    mkdir build && cd build
    ../configure --prefix=/usr/local/llvm-or1k
    make ENABLE_OPTIMIZED=1 REQUIRES_RTTI=1
    sudo -E make install ENABLE_OPTIMIZED=1 REQUIRES_RTTI=1

    cd ../..
    git clone https://github.com/llvmpy/llvmpy
    cd llvmpy
    git checkout llvm-3.4
    git checkout 7af2f7140391d4f708adf2721e84f23c1b89e97a
    patch -p1 < /path_to/ARTIQ/patches/llvmpy/*
    LLVM_CONFIG_PATH=/usr/local/llvm-or1k/bin/llvm-config sudo -E python setup.py install

.. note::
    ``python`` refers to Python 3. You may need to use the ``python3`` command instead of ``python`` on some distributions.

You may want to use ``checkinstall`` instead of ``make install`` (to register the installation with your package manager) and ``pip3 install --user .`` instead of ``sudo -E python setup.py install``.

You can then install ARTIQ itself: ::

    cd /path_to/ARTIQ
    sudo python setup.py

Alternatively, you can simply add the ARTIQ directory to your ``PYTHONPATH`` environment variable. The advantage of this technique is that you will not need to reinstall ARTIQ when modifying or upgrading it, which is useful during development.