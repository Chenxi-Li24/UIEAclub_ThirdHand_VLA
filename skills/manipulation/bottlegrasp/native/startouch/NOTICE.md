# Startouch bridge provenance and license notice

The contained bridge was written for `bottlegrasp`. Its process boundary,
nonblocking CAN ownership lock, measured-pose completion checks, gripper feedback,
and SDK cleanup lifecycle were adapted from these read-only local references:

- `/home/nieqingcao/TH-Fanxy/web-control/server/startouch_bridge.py`
- `/home/nieqingcao/th0814/TH_MK_D/UIEAclub_ThirdHand_VLA-control-fixed-a-to-b/web-control/server/startouch_bridge.py`
- `/home/nieqingcao/th0814/VA/Reuse/src/bottle_pick/robot/vendor_runtime.py`
- `/home/nieqingcao/th0814/VA/Reuse/native/startouch_bridge.py`

The referenced baseline is distributed under the following license:

> MIT License
>
> Copyright (c) 2026 UIEA Club
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

The vendor Startouch SDK is not committed or redistributed here. The explicit
offline preparation command verifies the source bytes and the MIT declaration
in the pinned `pyproject.toml`, then copies only manifested assets into the
git-ignored `build/startouch_runtime/startouch_sdk` directory. On Ubuntu 20.04,
the native library is the exact `src/libstartouch.so.20` asset committed at SDK
revision `9f0bc8f324ccdf866e20c27bbc7ed5007869db46`. The CPython 3.10 binding was
built twice from two independent clean exports of that revision with a pinned
local toolchain; the outputs matched byte-for-byte. The build and import/API
review are recorded in `REPRODUCIBLE_BUILD.md`.

Authorized real runtime imports only the contained copy. Offline tests and
simulation do not import the vendor SDK or open CAN.

Reference date: 2026-08-24.
