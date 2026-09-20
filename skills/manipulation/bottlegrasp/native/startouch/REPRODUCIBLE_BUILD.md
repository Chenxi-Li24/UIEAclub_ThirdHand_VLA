# Startouch CPython 3.10 rebuild evidence

This record covers an offline provenance and compatibility review performed on
2026-08-24. It neither connects to nor authorizes robot hardware.

## Inputs

- SDK repository: `$HOME/arm/startouch_sdk`
- clean exported commit: `9f0bc8f324ccdf866e20c27bbc7ed5007869db46`
- host: Ubuntu 20.04.6 LTS, x86-64
- CMake 3.16.3: `/usr/bin/cmake`, SHA-256
  `74ebabcb488d3e42e2bd7b56eaba7e719c44bf1846ec6adf35c375ef7af594c3`
- GCC/G++ 9.4.0: `/usr/bin/c++`, SHA-256
  `0c0b987719385f8e242819dfef6a3e97b4b2540ce4035dbc11565df2966bd69e`
- GNU ld 2.34: `/usr/bin/ld`, SHA-256
  `476b24d5cc1fef54f80412d06e7430b2dcf4e2b6f1525ee17e6eaaf16b28a00f`
- Python 3.10.20: `$HOME/miniconda3/envs/LumosTouch/bin/python`,
  SHA-256 `05756c2b5ee66b9d87e251c6a28c33af13165540ceab736c928bde63bb1039c0`
- pybind11 3.0.4; installed `RECORD` SHA-256
  `3e06adb20a9f3f2507dd18d4beba28bf793d3b064aeb91cc18ce4376732e6132`
- Eigen 3.3.7-2, libc6-dev 2.31-0ubuntu9.18

The source-defining hashes were:

- `pyproject.toml`: `f3cd28ab486ceed5b0c5f2e863640ac9b5b3d257da288a787dd44bcdff8905ed`
- `CMakeLists.txt`: `bad43d0ae60756d1ec4f2548126eb9b44531c3dbe4734a886580d53ffc8eb50d`
- `src/pybind_0825testfast.cpp`:
  `bb6af89571ad998d04a4beda63d2bda8240628eb99acbc334c039557db71bfe8`

## Procedure

The commit was exported with `git archive` into two independent directories
under this project's ignored `build/` tree. Each export was configured with:

```text
/usr/bin/cmake -S <clean-source> -B <independent-build> \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_SKIP_RPATH=TRUE \
  -Dpybind11_DIR=$HOME/miniconda3/envs/LumosTouch/lib/python3.10/site-packages/pybind11/share/cmake/pybind11 \
  -DPYTHON_EXECUTABLE=$HOME/miniconda3/envs/LumosTouch/bin/python
/usr/bin/cmake --build <independent-build> --parallel 2
```

## Results and review

- both clean CPython 3.10 bindings matched byte-for-byte: SHA-256
  `a681d5b4aefd063c6d2efe6454d914af92abeeab224af1722155c38e46bb055d`
- the Ubuntu 20 vendor library is the commit's `src/libstartouch.so.20`:
  SHA-256 `8284d216ab4e7b0195ffaf8e7fc70ee160b834511b9c05e77c0ba33ad545e24b`
- `CMAKE_SKIP_RPATH=TRUE` removed the external SDK path from the binding
- candidate and prior local binding both report SDK 0.1.7 and expose identical
  public module, `ArmController`, and wrapper `SingleArm` APIs
- an import-only `strace` observed no `AF_CAN` socket and no network/CAN data
  send or receive calls

The project-contained runtime is prepared from one clean build export and
revalidates every copied asset, the transformed safety config, and this complete
provenance object before the real bridge may import the SDK.
