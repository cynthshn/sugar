sugar
=====

This project has a script named *sugar.py* that does not require installation, you just need to download it and run it directly.

.. code-block::

    git clone https://github.com/cynthshn/sugar.git

Requirements
------------

This script requires some python packages and some external programs.

These python packages can be installed via pip.

.. code-block::

    cv2 ffprobe numpy psutil PyQt5 rich

And the python package `PyApplyLUT`_ needs to be compiled manually, please refer to `Python uses .cube LUT files to apply filters to images`_.

At the same time, the following software needs to be installed: `gyroflow`_, `easyHDR 3`_, `rife-ncnn-vulkan`_ and `timelapse-deflicker`_. Considering that `easyHDR 3`_ is a Windows program, it needs to be installed through `wine`_.

sugar.py
--------

To batch enhance videos, please place the videos in a directory and then execute the script *sugar.py*.

.. code-block::

    usage: sugar.py [-h]
                    (-1 /PATH/TO/BIN/GYROFLOW | -2 COLOR_CORRECTION_LUT [| LUT_2 | ...] | -3 /PATH/TO/BIN/easyHDR3.exe | -4 /PATH/TO/BIN/timelapse-deflicker.pl | -5 /PATH/TO/BIN/rife-ncnn-vulkan | -6)
                    DIRECTORY

    positional arguments:
    DIRECTORY             input video directory

    options:
    -h, --help            show this help message and exit
    -1 /PATH/TO/BIN/GYROFLOW
                            step1 - Stabilization
    -2 COLOR_CORRECTION_LUT [| LUT_2 | ...]
                            step2 - apply LUTs
    -3 /PATH/TO/BIN/easyHDR3.exe
                            step3 - LDR Enhancement
    -4 /PATH/TO/BIN/timelapse-deflicker.pl
                            step4 - Time-lapse Deflickering
    -5 /PATH/TO/BIN/rife-ncnn-vulkan
                            step5 - Interpolation
    -6                    step6 - Mergence

Please use parameters -1 to -6 in order to execute steps *Stabilization*, *Color Gradation*, *LDR Enhancement*, *Time-lapse Deflickering*, *Frame Interpolation* and *Mergence* in sequence. After all steps are completed, these enhanced videos will be saved in the same directory with the name *ORIGINAL-FILENAME-sugar.mp4*.

.. _PyApplyLUT: https://github.com/CKboss/PyApplyLUT
.. _Python uses .cube LUT files to apply filters to images: https://www.cnblogs.com/JiangOil/p/15362009.html
.. _gyroflow: https://gyroflow.xyz/
.. _easyHDR 3: https://www.easyhdr.com/
.. _timelapse-deflicker: https://github.com/cyberang3l/timelapse-deflicker
.. _rife-ncnn-vulkan: https://github.com/nihui/rife-ncnn-vulkan
.. _wine: https://www.winehq.org/
