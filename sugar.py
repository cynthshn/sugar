#!/usr/bin/python3

import collections
import errno
import os
import psutil
import re
import rich
import rich.markdown
import rich.progress
import rich.prompt
import rich.table
import shutil
import sys
import subprocess
import tempfile
import time

rife_ncnn_vulkan__arg_g = '-1,-1,-1,-1,0'
rife_ncnn_vulkan__arg_j = '3:2,2,2,2,1:5'

def stabilize(input_, gyroflow_path):
    gyroflow = os.path.abspath(gyroflow_path)
    if not os.path.isfile(gyroflow):
        raise FileNotFoundError(
              errno.ENOENT, f'file "{gyroflow_path}" not found')
    markdown('## Gyroflow Preparation')
    input_dir = os.path.abspath(input_)
    tasks = get_effective_dirs(input_dir, 1)
    for task in tasks:
        if not os.path.exists(task.to_working_dir):
            os.makedirs(task.to_working_dir)
    markdown(f'''\
## Stabilization
Now the "gyroflow" program is open, \
please render these videos in the "{input_dir}" directory \
into "PNG Sequence" and \
put them into the subdirectory named "stabilized" \
of the same name as the video \
in the "{os.path.dirname(input_dir)}" directory.

- It is recommended to name PNG Sequences in gyroflow as \
"/PATH/TO/VIDEO_WITHOUT_SUFFIX`/stabilized/`\\_stabilized\\_%05d.png".
- Please keep this program until stabilization process is complete.''')
    os.chdir(os.path.abspath(input_dir))
    with subprocess.Popen([ld_linux, gyroflow],
         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as proc:
        proc.communicate()
    summary(input_dir, 1)
    if rich.prompt.Confirm.ask('''\
Did all the gyroflow jobs be successfully completed?'''):
        tasks = get_effective_dirs(input_dir, 1)
        for task in tasks:
            if os.path.isdir(task.to_working_dir) \
            and get_directory_contents([task.to_working_dir]) > 0:
                with open(task.to_done_file, 'w'):
                    pass
        summary(input_dir, 1)
        markdown('''\
Now you can re-execute this program with the "-2" parameter \
to perform the next step "Color Gradation".''')
    else:
        summary(input_dir, 1)
        markdown('''\
Since this operation is not fully completed, \
consider re-performing this procedure.''')

def color_grade(input_, lut_files):

    import ApplyLUT
    import cv2
    import ffprobe
    import multiprocessing
    import numpy

    markdown('''## Color Gradation''')
    input_dir = os.path.abspath(input_)
    tasks = get_effective_dirs(input_dir, 2)
    regex_digital = re.compile(r'[0-9]{3,}')
    buf = collections.deque()
    active_tasks = []
    working_dirs = []
    preset_map = {}
    preset_ptr = 0
    for idx, task in rich.progress.track(enumerate(tasks, start=1),
                   total=len(tasks), description='Collecting ...'):
        metadata = ffprobe.FFProbe(task.src)
        video0 = metadata.video[0]
        if video0.color_transfer.strip().endswith('2020'):
            log.warning(f'"{task.src}" is HLG video, ignored')
            with open(task.to_done_file, 'w'):
                pass
            continue
        if 'pc' == video0.color_range.strip() \
           and not video0.color_transfer.strip().endswith('709'):
            preset_idx = preset_ptr
            preset_map[preset_ptr] = lut_files
            preset_ptr += 1
        elif not lut_files or len(lut_files) < 2:
            with open(task.to_done_file, 'w'):
                pass
            continue
        else:
            preset_idx = preset_ptr
            preset_map[preset_ptr] = lut_files[1:]
            preset_ptr += 1
        frames = {}
        for from_name in os.listdir(task.from_working_dir):
            root, ext = os.path.splitext(from_name)
            ext = ext.lower()
            if ext not in ['.png', '.jpg', '.jpeg']:
                continue
            match = regex_digital.search(root)
            if match is None:
                continue
            to_name = root[match.start():match.end()] + ext
            to_file = os.path.join(task.to_working_dir, to_name)
            from_file = os.path.join(task.from_working_dir, from_name)
            if to_file in frames:
                log.warning(f'duplicate frames "{to_name}"')
            else:
                frames[to_file] = (from_file, preset_idx)
        if not frames:
            log.warning('nothing to do with '
                        f'"{task.to_working_dir}", ignored')
            continue
        if os.path.exists(task.to_working_dir):
            if not os.path.isdir(task.to_working_dir):
                log.warning(f'"{task.to_working_dir}" '
                            'exists but is not a directory')
                continue
            shutil.rmtree(task.to_working_dir)
            log.warning(f'directory "{task.to_working_dir}" '
                        'has been reset')
        clean_other_files(task.from_working_dir)
        os.mkdir(task.to_working_dir)
        for to_file, (from_file, preset_idx) in sorted(frames.items()):
            buf.append((to_file, from_file, preset_idx))
        active_tasks.append(task)
        working_dirs.append(task.to_working_dir)
    physical_cores = psutil.cpu_count(logical=False)
    total, que = get_que(buf, physical_cores, 5, 500)
    color_gradation = _ColorGradation(preset_map)
    with multiprocessing.Pool(physical_cores) as pool:
        result = pool.map_async(color_gradation.apply_lut, que)
        complete = False
        files = 0
        for i in rich.progress.track(
            range(1, total+1), total=total, description='Grading ...'
        ):
            if complete or result.ready():
                complete = True
                continue
            if files > i:
                continue
            while i > files:
                time.sleep(6)
                files = get_directory_contents(working_dirs)
        while not result.ready():
            time.sleep(1.)
    for task in active_tasks:
        with open(task.to_done_file, 'w'):
            pass
        if os.path.isdir(task.from_working_dir):
            shutil.rmtree(task.from_working_dir)
    summary(input_dir, 2)
    markdown('''\
Once you have completed the above steps, \
re-execute this program with the "-3" parameter \
to perform the next step "LDR Enhancement".''')

class _ColorGradation:

    def __init__(self, preset_map):
        self.preset_map = preset_map

    def apply_lut(self, frames):

        import ApplyLUT
        import cv2
        import numpy

        prev = -1
        luts = None
        for to_file, from_file, preset_idx in frames:
            if preset_idx != prev:
                prev = preset_idx
                luts = []
                for lut_file in self.preset_map[preset_idx]:
                    luts.append(ApplyLUT.ApplyLUT(
                       os.path.abspath(lut_file)))
            img = cv2.imread(from_file)
            for lut in luts:
                tmp = img / 255
                h, w, c = tmp.shape
                seq = numpy.reshape(tmp, (h*w, c)).astype(numpy.float64)
                if seq.max() > 1:
                    seq = seq / 255
                img = numpy.reshape(lut.apply_lut_1d(seq), (h, w, c)) \
                    * 255
            cv2.imwrite(to_file, img)

def ldr_enhance(input_, easyhdr_path):

    import rich.columns
    import rich.syntax
    import QFileDialogPreview

    easyhdr = os.path.abspath(easyhdr_path)
    if not os.path.isfile(easyhdr):
        raise FileNotFoundError(
              errno.ENOENT, f'file "{easyhdr_path}" not found')
    easyhdr_presets_dir = os.path.join(
                          os.path.dirname(easyhdr), 'built-in presets')
    if not os.path.isdir(easyhdr_presets_dir):
        raise NotADirectoryError(
          errno.ENOTDIR, f'"{easyhdr_presets_dir}" is not a directory')
    presets = []
    for name in os.listdir(easyhdr_presets_dir):
        root, ext = os.path.splitext(name)
        if os.path.isfile(os.path.join(easyhdr_presets_dir, name)) \
           and '.ehsx' == ext:
            presets.append(root)
    presets.sort()
    presets = ['/'] + presets
    columns = rich.columns.Columns(
              [f'{i}. {presets[i]}' for i in range(len(presets))],
                       equal=True, expand=True, column_first=True)
    markdown('## LDR Enhancement Configuration')
    input_dir = os.path.abspath(input_)
    tasks = get_effective_dirs(input_dir, 3)
    title = ('%%%%0%dd/%%d' % len(str(len(tasks)))) % len(tasks)
    temp_dir_holder = temprary_directory_holder(suffix='_easyHDR')
    temp_dir = next(temp_dir_holder)
    for idx, task in enumerate(tasks, start=1):
        preset_file = os.path.join(task.dst_dir, 'easyhdr_preset')
        if os.path.isfile(preset_file):
            continue
        image = QFileDialogPreview.open_(
                'Sampling', task.from_working_dir, '*.png *.jpg *.jpeg')
        if image is not None:
            root = os.path.splitext(os.path.basename(task.src))[0]
            ext = os.path.splitext(image)[1]
            temp_view = os.path.join(temp_dir, root+ext)
            shutil.copyfile(image, temp_view)
            with subprocess.Popen(
                    ['/usr/bin/wine-stable', easyhdr, temp_view],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL) as proc:
                proc.communicate()
        markdown('---')
        rich.print(columns)
        markdown('---')
        q = '{title} Select a preset for {video} [0-{last}]'.format(
                  title=title%idx, video=os.path.basename(task.src),
                                                last=len(presets)-1)
        choices = [str(i) for i in range(len(presets))]
        choice = rich.prompt.Prompt.ask(
                 q, choices=choices, show_choices=False)
        if choice != '0':
            preset = presets[int(choice)]
            with open(preset_file, 'w') as f:
                f.write(preset)
    markdown('## easyHDR Preparation')
    tasks = get_effective_dirs(input_dir, 3)
    buf = collections.deque()
    active_tasks = []
    working_dirs = []
    for idx, task in rich.progress.track(enumerate(tasks, start=1),
                   total=len(tasks), description='Collecting ...'):
        preset_file = os.path.join(task.dst_dir, 'easyhdr_preset')
        if not os.path.isfile(preset_file):
            log.warning(f'"{preset_file}" not exists')
            continue
        with open(preset_file) as f:
            preset = f.read()
        if preset not in presets[1:]:
            log.warning(f'unknown presets {preset}')
            continue
        if os.path.exists(task.to_working_dir):
            if not os.path.isdir(task.to_working_dir):
                log.warning(f'"{task.to_working_dir}" '
                            'exists but is not a directory')
                continue
            shutil.rmtree(task.to_working_dir)
            log.warning(f'directory "{task.to_working_dir}" '
                        'has been reset')
        clean_other_files(task.from_working_dir)
        os.mkdir(task.to_working_dir)
        active_tasks.append(task)
        working_dirs.append(task.to_working_dir)
        for name in sorted(os.listdir(task.from_working_dir)):
            buf.append((task.from_working_dir, name, preset))
    physical_cores = psutil.cpu_count(logical=False)
    total, que = get_que(buf, physical_cores, 50, 5000)
    temp_dir_holder = temprary_directory_holder(suffix='_easyHDR')
    temp_dir = next(temp_dir_holder)
    for idx, frames in enumerate(que, start=1):
        ehtx_file = os.path.join(temp_dir, '%05d.ehtx' % idx)
        with open(ehtx_file, 'w') as f:
            f.write(f'''\
<easyHDRbatch BatchListFileVersion="4.3" ProgramVersion="3.16.2">
<Options SaveToDirectory="" SavePolicy="0" SkipExisting="0" />
<Tasks>''')
            for num, (from_working_dir, name, preset) in enumerate(
                                                   frames, start=1):
                path = 'Z:' + os.path.join(from_working_dir, name)
                f.write(f'''\
<Task{num} Name="../enhanced/{name}">\
<Settings UsePreset="2" />\
<PresetSeries><Preset1 Name="{preset} *"/></PresetSeries>\
<Files><File1 Path="{path}"/></Files>\
</Task{num}>''')
            f.write('''
</Tasks></easyHDRbatch>''')
    processes = min(physical_cores, len(os.listdir(temp_dir)))
    procs = []
    for i in range(processes):
        procs.append(subprocess.Popen(['/usr/bin/wine-stable', easyhdr],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    markdown(f'''\
## LDR Enhancement
Now, the "ehtx" files has been generated in a directory named: \
`{temp_dir}`

Now {processes} "easyHDR" program are open, \
click the "batch" button to import these ehtx files, \
and perform batch rendering of video frames.

- You can open more "easyHDR3" programs to increase rendering speed. \
The number of programs you can open \
depends on the number of your CPUs.''')
    rich.print(rich.syntax.Syntax(f'''\
nohup wine-stable "{easyhdr}" > /dev/null 2>&1 &
nohup wine-stable "{easyhdr}" > /dev/null 2>&1 &
nohup wine-stable "{easyhdr}" > /dev/null 2>&1 &''', 'bash'))
    markdown(f'''\
- Please keep this program until easyHDR processes is complete.''')
    os.chdir(temp_dir)
    complete = False
    files = 0
    for i in rich.progress.track(
        range(1, total+1), total=total, description='Rendering ...'
    ):
        if complete:
            continue
        if files > i:
            continue
        if _ldr_enhance__procs_ready(procs):
            complete = True
            continue
        while i > files:
            time.sleep(8)
            files = get_directory_contents(working_dirs)
    while not _ldr_enhance__procs_ready(procs):
        time.sleep(1.)
    summary(input_dir, 3)
    success = rich.prompt.Confirm.ask('''\
Did all the easyHDR jobs be successfully completed?''')
    if success:
        for idx, task in rich.progress.track(
            enumerate(active_tasks, start=1),
            total=len(active_tasks),
            description='Finishing ...'
        ):
            with open(task.to_done_file, 'w'):
                pass
            if os.path.isdir(task.from_working_dir):
                shutil.rmtree(task.from_working_dir)
    summary(input_dir, 3)
    if success:
        rich.print(rich.markdown.Markdown('''\
Now you can re-execute this program with the "-4" parameter \
to perform the next step "Time-lapse Deflickering".'''))
    else:
        rich.print(rich.markdown.Markdown('''\
Since this operation is not fully completed, \
consider re-performing this procedure.'''))

def _ldr_enhance__procs_ready(procs):
    if procs:
        to_remove = []
        for proc in procs:
            if proc.poll() is not None:
                to_remove.append(proc)
        for proc in to_remove:
            procs.remove(proc)
        if procs:
            return False
        else:
            return True
    else:
        return True

def deflicker(input_, deflickering):
    timelapse_deflicker_pl = os.path.abspath(deflickering)
    if not os.path.isfile(timelapse_deflicker_pl):
        raise FileNotFoundError(
              errno.ENOENT, f'file "{timelapse_deflicker_pl}" not found')
    markdown('## Time-lapse Deflicker Configuration')
    input_dir = os.path.abspath(input_)
    tasks = get_effective_dirs(input_dir, 4)
    active_tasks = []
    from_working_dirs = []
    to_working_dirs = []
    total_frames = 0
    for task in rich.progress.track(tasks, total=len(tasks),
                               description='Preparing ...'):
        enhanced = os.path.join(task.dst_dir, WORKING_DIRS[3-1])
        if not os.path.isdir(enhanced):
            log.warning(f'directory "{enhanced}" not exists, '
                        'so it cannot be deflickered, ignored')
            continue
        if os.path.exists(task.to_working_dir):
            if not os.path.isdir(task.to_working_dir):
                log.warning(f'"{task.to_working_dir}" '
                            'exists but is not a directory')
                continue
            shutil.rmtree(task.to_working_dir)
            log.warning(f'directory "{task.to_working_dir}" '
                        'has been reset')
        clean_other_files(task.from_working_dir)
        total_frames += get_directory_contents([task.from_working_dir])
        deflickered = os.path.join(task.from_working_dir, 'Deflickered')
        os.mkdir(deflickered)
        active_tasks.append(task)
        from_working_dirs.append(task.from_working_dir)
        to_working_dirs.append(deflickered)
    logical_cores = psutil.cpu_count(logical=True)
    buf = list(reversed(active_tasks))
    procs = []
    complete = False
    files = 0
    ratio = 30
    total = total_frames * (ratio + 2)
    for i in rich.progress.track(
        range(1, total+1), total=total, description='Deflickering ...'
    ):
        if complete:
            continue
        if files > i:
            continue
        if _deflicker__procs_ready_finish(
           timelapse_deflicker_pl, logical_cores, buf, procs):
            complete = True
            continue
        while i > files:
            if _deflicker__procs_ready_finish(
               timelapse_deflicker_pl, logical_cores, buf, procs):
                complete = True
            time.sleep(6)
            from_frames = get_directory_contents(from_working_dirs) - 1
            done_frames = get_directory_contents(to_working_dirs)
            files = done_frames * (ratio - 1) + from_frames
    while not _deflicker__procs_ready_finish(
          timelapse_deflicker_pl, logical_cores, buf, procs):
        time.sleep(1.)
    summary(input_dir, 4)
    markdown('''\
Once you have completed the above steps, \
re-execute this program with the "-5" parameter \
to perform the next step "Interpolation".''')

def _deflicker__procs_ready_finish(
        timelapse_deflicker_pl, logical_cores, buf, procs
    ):
    to_remove = []
    for elem in procs:
        proc, task = elem
        if proc.poll() is not None:
            deflickered = os.path.join(
                          task.from_working_dir, 'Deflickered')
            os.rename(deflickered, task.to_working_dir)
            with open(task.to_done_file, 'w'):
                pass
            if os.path.isdir(task.from_working_dir):
                shutil.rmtree(task.from_working_dir)
            to_remove.append(elem)
    for elem in to_remove:
        procs.remove(elem)
    while buf and len(procs) < logical_cores:
        task = buf.pop()
        from_working_dir = task.from_working_dir
        args = ['/usr/bin/perl', timelapse_deflicker_pl]
        proc = subprocess.Popen(args, cwd=from_working_dir,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append((proc, task))
    if buf or procs:
        return False
    else:
        return True

def interpolate(input_, interpolation):
    rife_ncnn_vulkan = os.path.abspath(interpolation)
    if not os.path.isfile(rife_ncnn_vulkan):
        raise FileNotFoundError(
              errno.ENOENT, f'file "{rife_ncnn_vulkan}" not found')
    markdown('## Interpolation')
    input_dir = os.path.abspath(input_)
    tasks = get_effective_dirs(input_dir, 5)
    active_tasks = []
    working_dirs = []
    total = 0
    for task in rich.progress.track(tasks, total=len(tasks),
                               description='Preparing ...'):
        if os.path.exists(task.to_working_dir):
            if not os.path.isdir(task.to_working_dir):
                log.warning(f'"{task.to_working_dir}" '
                            'exists but is not a directory')
                continue
            shutil.rmtree(task.to_working_dir)
            log.warning(f'directory "{task.to_working_dir}" '
                        'has been reset')
        clean_other_files(task.from_working_dir)
        total += get_directory_contents([task.from_working_dir])
        os.mkdir(task.to_working_dir)
        active_tasks.append(task)
        working_dirs.append(task.to_working_dir)
    buf = list(reversed(active_tasks))
    procs = []
    complete = False
    files = 0
    for i in rich.progress.track(
        range(1, total*2+1),
        total=total*2,
        description='Interpolating ...'
    ):
        if complete:
            continue
        if files > i:
            continue
        if _interpolate__procs_ready_finish(
               rife_ncnn_vulkan, buf, procs):
            complete = True
            continue
        while i > files:
            time.sleep(6)
            if _interpolate__procs_ready_finish(
                   rife_ncnn_vulkan, buf, procs):
                complete = True
            files = get_directory_contents(working_dirs)
    while not _interpolate__procs_ready_finish(
                  rife_ncnn_vulkan, buf, procs):
        time.sleep(1.)
    summary(input_dir, 5)
    markdown('''\
Once you have completed the above steps, \
re-execute this program with the "-6" parameter \
to perform the next step "Mergence".''')

def _interpolate__procs_ready_finish(rife_ncnn_vulkan, buf, procs):
    to_remove = []
    for elem in procs:
        proc, task = elem
        if proc.poll() is not None:
            with open(task.to_done_file, 'w'):
                pass
            if os.path.isdir(task.from_working_dir):
                shutil.rmtree(task.from_working_dir)
            to_remove.append(elem)
    for elem in to_remove:
        procs.remove(elem)
    while buf and len(procs) < 1:
        task = buf.pop()
        args = [ld_linux, rife_ncnn_vulkan,
                '-g', rife_ncnn_vulkan__arg_g,
                '-j', rife_ncnn_vulkan__arg_j,
                '-i', task.from_working_dir, '-o', task.to_working_dir]
        proc = subprocess.Popen(
               args, cwd=os.path.dirname(rife_ncnn_vulkan),
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append((proc, task))
    if buf or procs:
        return False
    else:
        return True

def merge(input_, crf=12):

    import ffprobe

    markdown('## Mergence')
    input_dir = os.path.abspath(input_)
    tasks = get_effective_dirs(input_dir, 6)
    active_tasks = []
    for idx, task in rich.progress.track(enumerate(tasks, start=1),
                   total=len(tasks), description='Collecting ...'):
        if os.path.exists(task.dst_file):
            continue
        metadata = ffprobe.FFProbe(task.src)
        try:
            video0 = metadata.video[0]
        except IndexError:
            log.warning(f'no video stream found in {task.src}, ignored')
            continue
        active_tasks.append((task, metadata))
    for idx, (task, metadata) in rich.progress.track(
        enumerate(active_tasks, start=1),
        total=len(active_tasks), description='Preparing ...'
    ):
        if os.path.exists(task.to_working_dir):
            if not os.path.isdir(task.to_working_dir):
                log.warning(f'"{task.to_working_dir}" '
                            'exists but is not a directory')
                continue
            shutil.rmtree(task.to_working_dir)
            log.warning(f'directory "{task.to_working_dir}" '
                        'has been reset')
        clean_other_files(task.from_working_dir)
        os.mkdir(task.to_working_dir)
        for audio in enumerate(metadata.audio, start=1):
            audio_m4a = os.path.join(task.to_working_dir, '%05d.m4a')
            bit_rate = '%dk' % int(int(audio[1].bit_rate)/1000)
            args = ['/usr/bin/ffmpeg', '-i', task.src, '-vn',
                    '-c:a', 'aac', '-b:a', bit_rate, audio_m4a]
            with subprocess.Popen(args,
                 stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL) as proc:
                proc.communicate()
    regex_digital = re.compile(r'[0-9]{3,}')
    for idx, (task, metadata) in rich.progress.track(
        enumerate(active_tasks, start=1),
        total=len(active_tasks), description='Merging ...'
    ):
        video0 = metadata.video[0]
        numerator, denominator = video0.avg_frame_rate.split('/')
        for name in os.listdir(task.dst_dir):
            if 'interpolation_done' == name.lower():
                tbr = str(float(numerator)/float(denominator) * 2)
                break
        else:
            tbr = str(float(numerator)/float(denominator))
        for name in os.listdir(task.from_working_dir):
            root, ext = os.path.splitext(name)
            if ext not in ['.png', '.jpg', '.jpeg']:
                continue
            match = regex_digital.search(root)
            if not match:
                continue
            parts = regex_digital.split(root)
            if len(parts) != 2:
                continue
            fmt = f'%0{match.end()-match.start()}d'
            fmt = f'{parts[0]}{fmt}{parts[1]}{ext}'
            fmt = os.path.join(task.from_working_dir, fmt)
            break
        else:
            log.warning('cannot detect frame format in '
                        f'"{task.from_working_dir}"')
        args = ['konsole', '-e',
                '/usr/bin/ffmpeg', '-framerate', tbr, '-i', fmt]
        for name in os.listdir(task.to_working_dir):
            audio_m4a = os.path.join(task.to_working_dir, name)
            args.extend(['-i', audio_m4a])
        args.extend(['-c:a', 'copy', '-crf', str(crf), '-c:v', 'libx265',
                                   '-pix_fmt', 'yuv420p', task.dst_file])
        with subprocess.Popen(args,
             stdout=subprocess.DEVNULL,
             stderr=subprocess.DEVNULL) as proc:
            proc.communicate()
        #shutil.rmtree(task.dst_dir)
    summary(input_dir, 6)

def main():

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
            dest='input_',
            help='input video directory',
           nargs=1,
         metavar='DIRECTORY'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
            '-1',
            dest='stabilization',
            help='step1 - Stabilization',
         metavar='/PATH/TO/BIN/GYROFLOW'
    )
    group.add_argument(
            '-2',
            dest='LUTs',
            help='step2 - apply LUTs',
         metavar='COLOR_CORRECTION_LUT [| LUT_2 | ...]'
    )
    group.add_argument(
            '-3',
            dest='ldr_enhancement',
            help='step3 - LDR Enhancement',
         metavar='/PATH/TO/BIN/easyHDR3.exe'
    )
    group.add_argument(
            '-4',
            dest='deflickering',
            help='step4 - Time-lapse Deflickering',
            metavar='/PATH/TO/BIN/timelapse-deflicker.pl'
    )
    group.add_argument(
            '-5',
            dest='interpolation',
            help='step5 - Interpolation',
         metavar='/PATH/TO/BIN/rife-ncnn-vulkan'
    )
    group.add_argument(
            '-6',
            dest='mergence',
            help='step6 - Mergence',
          action='store_true'
    )
    opts = parser.parse_args()
    try:
        if opts.stabilization:
            stabilize(opts.input_[0], opts.stabilization)
        if opts.LUTs:
            lut_files = []
            for lut_file in opts.LUTs.split('|'):
                lut_files.append(lut_file.strip())
            color_grade(opts.input_[0], lut_files)
        if opts.ldr_enhancement:
            ldr_enhance(opts.input_[0], opts.ldr_enhancement)
        if opts.deflickering:
            deflicker(opts.input_[0], opts.deflickering)
        if opts.interpolation:
            interpolate(opts.input_[0], opts.interpolation)
        if opts.mergence:
            merge(opts.input_[0])
    except FileNotFoundError as e:
        log.error(e.strerror)
        raise
        sys.exit(errno.ENOENT)
    except NotADirectoryError as e:
        log.error(e.strerror)
        raise
        sys.exit(errno.ENOTDIR)
    except KeyboardInterrupt:
        raise
        sys.exit(0)

def summary(input_dir, step):
    assert 0 < step < len(STEPS) + 1
    markdown(f'## {STEPS[step-1]} Summary')
    tasks = get_effective_dirs(input_dir, step)
    table = rich.table.Table(
            show_header=True, header_style='bold magenta')
    table.add_column('Id', justify='right')
    table.add_column('Video')
    table.add_column('Frames', justify='right')
    table.add_column('Usage', justify='right')
    table.add_column('Stage')
    for idx, (src, dst_dir) in enumerate(get_dst_dirs(input_dir),
                                                        start=1):
        src_name = os.path.basename(src)
        src_dir = os.path.dirname(src)
        root, ext = os.path.splitext(src_name)
        if root.endswith('-sugar'):
            continue
        dst_file = os.path.join(src_dir, f'{root}-sugar{ext}')
        if os.path.exists(dst_file):
            last_completed_step = len(STEPS)
            stage = 'All done'
        else:
            for step_i, done_file_name in reversed(list(
                zip(range(len(STEPS)-1), DONE_FILES[:-1])
            )):
                if os.path.exists(os.path.join(dst_dir, done_file_name)):
                    last_completed_step = step_i + 1
                    stage = f'{STEPS[step_i]} ({last_completed_step})'
                    break
            else:
                last_completed_step = 0
                stage = '/'
            to_working_dir = os.path.join(dst_dir, WORKING_DIRS[step-1])
            to_done_file = os.path.join(dst_dir, DONE_FILES[step-1])
        if step == len(STEPS):
            done_files = DONE_FILES[:-1] + [dst_file]
        else:
            done_files = DONE_FILES
        broken = False
        if step < 2:
            from_working_dir = None
            from_done_file = None
        else:
            for working_dir_name, done_file_name in reversed(list(zip(
                        WORKING_DIRS[:step-1], done_files[:step-1]))):
                from_working_dir = os.path.join(
                                   dst_dir, working_dir_name)
                from_done_file = os.path.join(dst_dir, done_file_name)
                if not os.path.exists(from_done_file):
                    continue
                if os.path.isdir(from_working_dir):
                    if 0 == get_directory_contents([from_working_dir]):
                        log.warning(f'The previous working directory '
                                    f'"{from_working_dir}" is empty')
                        continue
                    break
            else:
                broken = True
                from_working_dir = None
                from_done_file = None
        if last_completed_step == len(STEPS):
            inodes, usage = get_directory_usage(dst_file)
            frames = 'N/A'
        elif os.path.isdir(to_working_dir):
            inodes, usage = get_directory_usage(to_working_dir)
            frames = str(inodes)
        else:
            inodes = 0
            frames = 'N/A'
            usage = 'N/A'
        if last_completed_step >= step:
            color = 'green'
        elif broken:
            stage = 'Broken'
            color = 'yellow'
        elif from_working_dir is not None \
             and get_directory_contents([from_working_dir]) != inodes:
            color = 'red'
        else:
            color = None
        if color is not None:
            frames = f'[{color}]{frames}[/{color}]'
            usage = f'[{color}]{usage}[/{color}]'
            stage = f'[{color}]{stage}[/{color}]'
        table.add_row(str(idx), src_name, frames, usage, stage)
    rich.print(table)

def get_effective_dirs(input_dir, step):
    assert 0 < step < len(STEPS) + 1
    effective_dirs = []
    for src, dst_dir in get_dst_dirs(input_dir):
        src_name = os.path.basename(src)
        src_dir = os.path.dirname(src)
        root, ext = os.path.splitext(src_name)
        if root.endswith('-sugar'):
            continue
        dst_file = os.path.join(src_dir, f'{root}-sugar{ext}')
        if os.path.exists(dst_file):
            last_completed_step = len(STEPS)
        else:
            for name in reversed(DONE_FILES):
                if os.path.exists(os.path.join(dst_dir, name)):
                    last_completed_step = DONE_FILES.index(name) + 1
                    break
            else:
                last_completed_step = 0
        if last_completed_step >= step:
            continue
        broken = False
        if step < 2:
            from_working_dir = None
            from_done_file = None
        else:
            for working_dir_name, done_file_name in reversed(list(zip(
                        WORKING_DIRS[:step-1], DONE_FILES[:step-1]))):
                from_working_dir = os.path.join(
                                   dst_dir, working_dir_name)
                from_done_file = os.path.join(dst_dir, done_file_name)
                if not os.path.exists(from_done_file):
                    continue
                if os.path.isdir(from_working_dir):
                    if 0 == get_directory_contents([from_working_dir]):
                        log.warning(f'The previous working directory '
                                    f'"{from_working_dir}" is empty')
                        continue
                    break
            else:
                broken = True
        if broken:
            log.warning(f'The working directory {dst_dir} is broken')
            continue
        to_working_dir = os.path.join(dst_dir, WORKING_DIRS[step-1])
        to_done_file = os.path.join(dst_dir, DONE_FILES[step-1])
        if os.path.exists(to_done_file):
            continue
        if os.path.exists(to_working_dir):
            if not os.path.isdir(to_working_dir):
                log.warning(f'{to_working_dir} exists, '
                            'but it must be a directory, ignored')
                continue
        effective_dirs.append(Task(
           src, dst_file, dst_dir, from_working_dir,
           to_working_dir, to_done_file, last_completed_step))
    return effective_dirs

def clean_other_files(from_working_dir):
    for name in os.listdir(from_working_dir):
        root, ext = os.path.splitext(name)
        if ext not in ['.png', '.jpg', '.jpeg']:
            path = os.path.join(from_working_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

def get_dst_dirs(input_dir):
    if not os.path.isdir(input_dir):
        raise NotADirectoryError(
              errno.ENOTDIR, f'"{input_dir}" is not a directory')
    for name in sorted(os.listdir(input_dir)):
        root, ext = os.path.splitext(name)
        if '.mp4' != ext.lower():
            continue
        src = os.path.join(input_dir, name)
        dst_dir = os.path.join(input_dir, root)
        if os.path.exists(dst_dir):
            if not os.path.isdir(dst_dir):
                log.warning(f'{dst_dir} is not a directory')
                continue
        yield src, dst_dir

def get_directory_contents(dirs):
    with subprocess.Popen(['du', '--max-depth=0', '--inodes'] + dirs,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL) as proc:
        outs = proc.communicate()[0]
    contents = 0
    for row in outs.split(b'\n'):
        if row.strip():
            contents += int(row.split(None, 1)[0]) - 1
    return contents

def get_que(buf, channels, min_, max_):
    total = len(buf)
    que = []
    prev = max_ + 1
    while buf:
        chunk = min(max(int(len(buf) / channels), min_), max_)
        if chunk == prev:
            while buf:
                items = []
                for i in range(chunk):
                    items.append(buf.popleft())
                    if not buf:
                        break
                if items:
                    que.append(items)
            return total, que
        while len(buf) >= chunk * channels:
            for i in range(channels):
                items = []
                for j in range(chunk):
                    items.append(buf.popleft())
                que.append(items)
        prev = chunk
    return total, que

def get_directory_usage(dir_):
    with subprocess.Popen(['du', '--inodes', dir_],
                   stdout=subprocess.PIPE) as proc:
        outs = proc.communicate()[0]
    inodes = int(outs.split(None, 1)[0]) - 1
    with subprocess.Popen(['du', '--max-depth=0', '-h', dir_],
                              stdout=subprocess.PIPE) as proc:
        outs = proc.communicate()[0]
    usage = outs.split(None, 1)[0].decode()
    return inodes, usage

def markdown(*args, **kwargs):
    rich.print(rich.markdown.Markdown(*args, **kwargs))

def temprary_directory_holder(*args, **kwargs):
    with tempfile.TemporaryDirectory(*args, **kwargs) as temp_dir:
        yield temp_dir

def get_logger():

    import logging
    import rich.logging

    logging.basicConfig(
           level='WARNING',
          format='%(message)s',
         datefmt='[%X]',
        handlers=[rich.logging.RichHandler()]
    )
    return logging.getLogger('render')

def get_ld_linux():
    with subprocess.Popen(['/usr/bin/ldd', sys.executable],
                           stdout=subprocess.PIPE) as proc:
        for line in proc.communicate()[0].decode().split('\n'):
            if '/ld-linux' in line:
                return line.strip().split(None, 1)[0]

STEPS = '''Stabilization,Color gradation,LDR enhancement,\
Time-lapse deflickering,Interpolation,Mergence'''.split(',')
WORKING_DIRS = '''stabilized color_graded enhanced deflickered \
interpolated mergence_resources'''.split()
DONE_FILES = '''stabilization_done color_gradation_done \
enhancement_done deflickering_done interpolation_done all_done'''.split()
Task = collections.namedtuple('Task', '''\
src dst_file dst_dir from_working_dir to_working_dir to_done_file \
last_completed_step'''.split())
ld_linux = get_ld_linux()
log = get_logger()

if '__main__' == __name__:
    main()